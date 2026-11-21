from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from advisor.config import Settings


class AlpacaBroker:
    """Ejecución real en Alpaca Paper/Live via API oficial."""

    def __init__(self, settings: Settings):
        self.settings = settings
        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            raise ValueError(
                "Faltan ADVISOR_ALPACA_API_KEY / ADVISOR_ALPACA_SECRET_KEY"
            )
        from alpaca.trading.client import TradingClient

        self.client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=bool(settings.alpaca_paper),
        )
        self._halted = False
        self._halt_reason = ""

    def status(self) -> dict[str, Any]:
        account = self.client.get_account()
        positions = self.client.get_all_positions()
        pos_map = {}
        for p in positions:
            pos_map[p.symbol] = {
                "ticker": p.symbol,
                "qty": float(p.qty),
                "entry_price": float(p.avg_entry_price),
                "last_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "side": str(p.side),
            }
        equity = float(account.equity)
        last_equity = float(account.last_equity)
        return {
            "mode": "alpaca_paper" if self.settings.alpaca_paper else "alpaca_live",
            "cash": float(account.cash),
            "equity": equity,
            "equity_start": last_equity,
            "buying_power": float(account.buying_power),
            "open_positions": len(pos_map),
            "positions": pos_map,
            "daily_pnl": equity - last_equity,
            "total_pnl": equity - last_equity,
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "account_status": str(account.status),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def halt(self, reason: str) -> dict[str, Any]:
        self._halted = True
        self._halt_reason = reason
        return self.status()

    def resume(self) -> dict[str, Any]:
        self._halted = False
        self._halt_reason = ""
        return self.status()

    def mark_price(self, ticker: str, price: float) -> None:
        # Alpaca marca solo; no hay estado local que actualizar.
        return None

    def buy(
        self,
        ticker: str,
        price: float,
        position_pct: float,
        stop: float,
        target: float,
        reason: str,
    ) -> dict[str, Any]:
        if self._halted:
            return {"ok": False, "error": f"Autopilot detenido: {self._halt_reason}"}

        # Evita duplicar posición
        try:
            existing = {p.symbol for p in self.client.get_all_positions()}
            if ticker in existing:
                return {"ok": False, "error": f"Ya hay posición abierta en {ticker}"}
        except Exception:
            pass

        account = self.client.get_account()
        equity = float(account.equity)
        notional = max(equity * float(position_pct), 1.0)

        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
        from alpaca.trading.requests import (
            MarketOrderRequest,
            StopLossRequest,
            TakeProfitRequest,
        )

        # Bracket: entrada market + TP/SL
        req = MarketOrderRequest(
            symbol=ticker,
            notional=round(notional, 2),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(float(target), 2)),
            stop_loss=StopLossRequest(stop_price=round(float(stop), 2)),
        )
        try:
            order = self.client.submit_order(req)
            return {
                "ok": True,
                "order": {
                    "id": str(order.id),
                    "symbol": order.symbol,
                    "side": str(order.side),
                    "status": str(order.status),
                    "notional": notional,
                    "stop": float(stop),
                    "target": float(target),
                    "reason": reason,
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
                "portfolio": self.status(),
            }
        except Exception as exc:
            # Fallback: market simple si bracket no aplica (p.ej. fractional constraints)
            try:
                simple = MarketOrderRequest(
                    symbol=ticker,
                    notional=round(notional, 2),
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                )
                order = self.client.submit_order(simple)
                return {
                    "ok": True,
                    "order": {
                        "id": str(order.id),
                        "symbol": order.symbol,
                        "side": str(order.side),
                        "status": str(order.status),
                        "notional": notional,
                        "stop": float(stop),
                        "target": float(target),
                        "reason": reason + "|simple_fallback",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "warning": f"Bracket falló ({exc}); se envió market simple.",
                    },
                    "portfolio": self.status(),
                }
            except Exception as exc2:
                return {"ok": False, "error": str(exc2)}

    def sell(self, ticker: str, price: float, reason: str) -> dict[str, Any]:
        if self._halted and reason not in {"stop_loss", "take_profit", "kill_switch"}:
            return {"ok": False, "error": f"Autopilot detenido: {self._halt_reason}"}
        try:
            order = self.client.close_position(ticker)
            return {
                "ok": True,
                "order": {
                    "id": str(getattr(order, "id", "")),
                    "symbol": ticker,
                    "side": "sell",
                    "status": str(getattr(order, "status", "submitted")),
                    "price": float(price),
                    "reason": reason,
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
                "portfolio": self.status(),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
