from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from advisor.config import Settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PaperBroker:
    """Broker simulado con costos round-trip estimados BTG."""

    def __init__(self, settings: Settings, path: Path | None = None):
        self.settings = settings
        self.path = path or (settings.data_dir / "paper_portfolio.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(self._empty_state())

    def _empty_state(self) -> dict[str, Any]:
        return {
            "cash": 10_000_000.0,  # CLP paper
            "equity_start": 10_000_000.0,
            "positions": {},
            "closed": [],
            "orders": [],
            "daily_pnl": 0.0,
            "day": _now().date().isoformat(),
            "halted": False,
            "halt_reason": "",
            "updated_at": _now().isoformat(),
        }

    def _read(self) -> dict[str, Any]:
        state = json.loads(self.path.read_text(encoding="utf-8"))
        today = _now().date().isoformat()
        if state.get("day") != today:
            state["day"] = today
            state["daily_pnl"] = 0.0
            if state.get("halt_reason") == "max_daily_loss":
                state["halted"] = False
                state["halt_reason"] = ""
            self._write(state)
        return state

    def _write(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _now().isoformat()
        self.path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def status(self) -> dict[str, Any]:
        state = self._read()
        positions = state.get("positions", {})
        market_value = sum(float(p["qty"]) * float(p["last_price"]) for p in positions.values())
        equity = float(state["cash"]) + market_value
        return {
            "mode": "paper",
            "cash": round(float(state["cash"]), 2),
            "equity": round(equity, 2),
            "equity_start": round(float(state["equity_start"]), 2),
            "open_positions": len(positions),
            "positions": positions,
            "daily_pnl": round(float(state.get("daily_pnl", 0.0)), 2),
            "total_pnl": round(equity - float(state["equity_start"]), 2),
            "halted": bool(state.get("halted", False)),
            "halt_reason": state.get("halt_reason", ""),
            "orders": state.get("orders", [])[-20:],
            "closed": state.get("closed", [])[-20:],
            "updated_at": state.get("updated_at"),
        }

    def halt(self, reason: str) -> dict[str, Any]:
        state = self._read()
        state["halted"] = True
        state["halt_reason"] = reason
        self._write(state)
        return self.status()

    def resume(self) -> dict[str, Any]:
        state = self._read()
        state["halted"] = False
        state["halt_reason"] = ""
        self._write(state)
        return self.status()

    def mark_price(self, ticker: str, price: float) -> None:
        state = self._read()
        pos = state["positions"].get(ticker)
        if not pos:
            return
        pos["last_price"] = float(price)
        self._write(state)

    def buy(
        self,
        ticker: str,
        price: float,
        position_pct: float,
        stop: float,
        target: float,
        reason: str,
    ) -> dict[str, Any]:
        state = self._read()
        if state.get("halted"):
            return {"ok": False, "error": f"Autopilot detenido: {state.get('halt_reason')}"}
        if ticker in state["positions"]:
            return {"ok": False, "error": f"Ya hay posición abierta en {ticker}"}

        equity = float(state["cash"]) + sum(
            float(p["qty"]) * float(p["last_price"]) for p in state["positions"].values()
        )
        notional = equity * float(position_pct)
        if notional <= 0 or price <= 0:
            return {"ok": False, "error": "Tamaño/precio inválido"}

        # Aplica mitad del costo round-trip a la entrada
        entry_cost_pct = self.settings.round_trip_cost_pct / 2.0
        fill_price = price * (1 + entry_cost_pct)
        qty = notional / fill_price
        cash_needed = qty * fill_price
        if cash_needed > float(state["cash"]):
            return {"ok": False, "error": "Cash insuficiente"}

        state["cash"] = float(state["cash"]) - cash_needed
        state["positions"][ticker] = {
            "ticker": ticker,
            "qty": qty,
            "entry_price": fill_price,
            "last_price": fill_price,
            "stop": float(stop),
            "target": float(target),
            "opened_at": _now().isoformat(),
            "reason": reason,
        }
        order = {
            "ts": _now().isoformat(),
            "side": "buy",
            "ticker": ticker,
            "qty": qty,
            "price": fill_price,
            "reason": reason,
        }
        state["orders"].append(order)
        self._write(state)
        return {"ok": True, "order": order, "portfolio": self.status()}

    def sell(self, ticker: str, price: float, reason: str) -> dict[str, Any]:
        state = self._read()
        pos = state["positions"].get(ticker)
        if not pos:
            return {"ok": False, "error": f"No hay posición en {ticker}"}

        exit_cost_pct = self.settings.round_trip_cost_pct / 2.0
        fill_price = float(price) * (1 - exit_cost_pct)
        qty = float(pos["qty"])
        proceeds = qty * fill_price
        entry_cost = qty * float(pos["entry_price"])
        pnl = proceeds - entry_cost

        state["cash"] = float(state["cash"]) + proceeds
        state["daily_pnl"] = float(state.get("daily_pnl", 0.0)) + pnl
        closed = {
            "ts": _now().isoformat(),
            "ticker": ticker,
            "qty": qty,
            "entry_price": float(pos["entry_price"]),
            "exit_price": fill_price,
            "pnl": pnl,
            "reason": reason,
        }
        state["closed"].append(closed)
        order = {
            "ts": _now().isoformat(),
            "side": "sell",
            "ticker": ticker,
            "qty": qty,
            "price": fill_price,
            "reason": reason,
            "pnl": pnl,
        }
        state["orders"].append(order)
        del state["positions"][ticker]

        # Kill-switch por pérdida diaria
        equity_start = float(state["equity_start"])
        max_loss = equity_start * self.settings.max_daily_loss_pct
        if float(state["daily_pnl"]) <= -max_loss:
            state["halted"] = True
            state["halt_reason"] = "max_daily_loss"

        self._write(state)
        return {"ok": True, "order": order, "closed": closed, "portfolio": self.status()}
