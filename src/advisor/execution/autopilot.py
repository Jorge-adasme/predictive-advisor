from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from advisor.advisory.pipeline import AdvisoryPipeline
from advisor.config import Settings, get_settings
from advisor.execution.paper_broker import PaperBroker
from advisor.execution.trail_store import TrailStore
from advisor.models import Action
from advisor.portfolio.audit import AuditLog
from advisor.risk.portfolio_filters import select_diversified
from advisor.risk.trailing import (
    progress_in_r,
    ratchet_stop,
    should_partial_take,
    should_time_stop,
)


@dataclass
class AutopilotResult:
    ts: str
    actions: list[dict]
    portfolio: dict
    market: dict | None
    message: str
    mode: str


def build_broker(settings: Settings, mode: str):
    mode = mode.lower()
    if mode in {"alpaca", "alpaca_paper", "alpaca_live"}:
        from advisor.execution.alpaca_broker import AlpacaBroker

        return AlpacaBroker(settings)
    if mode in {"paper", "local_paper"}:
        return PaperBroker(settings)
    raise ValueError("mode debe ser 'alpaca' o 'paper'")


def _days_held(opened_at: str | None) -> int:
    if not opened_at:
        return 0
    try:
        opened = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
        return max((datetime.now(timezone.utc) - opened).days, 0)
    except Exception:
        return 0


class Autopilot:
    """Ejecuta automáticamente ideas con edge neto positivo."""

    def __init__(self, settings: Settings | None = None, mode: str = "alpaca"):
        self.settings = settings or get_settings()
        self.mode = mode.lower()
        self.pipeline = AdvisoryPipeline(self.settings)
        self.broker = build_broker(self.settings, self.mode)
        self.trails = TrailStore(self.settings)

    def _manage_open_risk(self, portfolio: dict, price_map: dict[str, float]) -> list[dict]:
        """Trailing/BE, partial TP, time-stop y salidas stop/target."""
        actions: list[dict] = []
        positions = dict(portfolio.get("positions") or {})
        s = self.settings

        for ticker, pos in list(positions.items()):
            px = price_map.get(ticker)
            if px is None:
                px = float(pos.get("last_price") or pos.get("current_price") or 0)
            if not px:
                continue
            if hasattr(self.broker, "mark_price"):
                self.broker.mark_price(ticker, px)

            entry = float(pos.get("entry_price") or pos.get("avg_entry_price") or px)
            stop = float(pos.get("stop") or 0.0)
            target = float(pos.get("target") or 0.0)
            initial_stop = float(pos.get("initial_stop") or stop)
            partial_taken = bool(pos.get("partial_taken"))
            horizon = int(pos.get("horizon_days") or s.horizon_days)

            stored = self.trails.get(ticker)
            if stored:
                stop = float(stored.get("stop") or stop)
                initial_stop = float(stored.get("initial_stop") or initial_stop)
                entry = float(stored.get("entry") or entry)
                target = float(stored.get("target") or target)
                partial_taken = bool(stored.get("partial_taken", partial_taken))
                horizon = int(stored.get("horizon_days") or horizon)

            if stop <= 0 or initial_stop <= 0:
                continue

            # 1) Partial take-profit a +1.5R
            if should_partial_take(
                entry=entry,
                mark_price=px,
                initial_stop=initial_stop,
                already_taken=partial_taken,
                partial_at_r=s.partial_tp_at_r,
            ):
                result = self.broker.sell(
                    ticker,
                    px,
                    reason="partial_tp",
                    fraction=s.partial_tp_fraction,
                )
                actions.append({"type": "partial", **result})
                if result.get("ok"):
                    self.trails.mark_partial(ticker)
                    be = entry * (1 + s.round_trip_cost_pct / 2.0)
                    self.trails.update_stop(ticker, max(stop, be), event="partial_be")
                    stop = max(stop, be)
                    partial_taken = True

            # 2) Time-stop: sin progreso suficiente cerca del horizonte
            held = _days_held(pos.get("opened_at") or (stored or {}).get("opened_at"))
            if should_time_stop(
                entry=entry,
                mark_price=px,
                initial_stop=initial_stop,
                days_held=held,
                horizon_days=horizon,
                time_stop_frac=s.time_stop_frac,
                min_r=s.time_stop_min_r,
            ):
                result = self.broker.sell(ticker, px, reason="time_stop", fraction=1.0)
                self.trails.remove(ticker)
                actions.append({"type": "exit", **result})
                continue

            # 3) Trailing / break-even
            update = ratchet_stop(
                entry=entry,
                current_stop=stop,
                mark_price=px,
                initial_stop=initial_stop,
                breakeven_at_r=s.breakeven_at_r,
                trail_at_r=s.trail_at_r,
                cost_buffer_pct=s.round_trip_cost_pct / 2.0,
                atr=None,
                atr_mult=s.trail_atr_mult,
            )
            if update.event:
                if hasattr(self.broker, "update_stop"):
                    self.broker.update_stop(ticker, update.stop, event=update.event)
                self.trails.update_stop(ticker, update.stop, event=update.event or "")
                actions.append(
                    {
                        "type": "trail",
                        "ok": True,
                        "ticker": ticker,
                        "stop": update.stop,
                        "event": update.event,
                        "price": px,
                        "progress_r": round(progress_in_r(entry, px, initial_stop), 2),
                    }
                )
                stop = update.stop

            # 4) Stop / target hard exits
            if stop > 0 and px <= stop:
                result = self.broker.sell(
                    ticker, px, reason=f"stop_loss|{update.event or 'initial'}", fraction=1.0
                )
                self.trails.remove(ticker)
                actions.append({"type": "exit", **result})
            elif target > 0 and px >= target:
                result = self.broker.sell(ticker, px, reason="take_profit", fraction=1.0)
                self.trails.remove(ticker)
                actions.append({"type": "exit", **result})

        return actions

    def _position_mark(self, pos: dict, price_map: dict[str, float], ticker: str) -> float:
        px = price_map.get(ticker)
        if px is None:
            px = float(pos.get("last_price") or pos.get("current_price") or pos.get("entry_price") or 0)
        return float(px or 0)

    def _unrealized_pnl(self, pos: dict, mark: float) -> float:
        if pos.get("unrealized_pl") is not None:
            try:
                return float(pos["unrealized_pl"])
            except Exception:
                pass
        entry = float(pos.get("entry_price") or pos.get("avg_entry_price") or 0)
        qty = float(pos.get("qty") or 0)
        return (mark - entry) * qty

    def _close_positions_for_kill_switch(
        self,
        portfolio: dict,
        price_map: dict[str, float],
        *,
        losers_only: bool,
    ) -> list[dict]:
        """Cierra perdedoras (o todo) al disparar pérdida diaria máxima."""
        actions: list[dict] = []
        positions = dict(portfolio.get("positions") or {})
        reason = "kill_switch_loser" if losers_only else "kill_switch_flatten"
        for ticker, pos in list(positions.items()):
            mark = self._position_mark(pos, price_map, ticker)
            if mark <= 0:
                continue
            pnl = self._unrealized_pnl(pos, mark)
            if losers_only and pnl >= 0:
                continue
            result = self.broker.sell(ticker, mark, reason=reason, fraction=1.0)
            actions.append(
                {
                    "type": "exit",
                    "ticker": ticker,
                    "kill_switch": True,
                    "unrealized_pnl": round(pnl, 2),
                    **result,
                }
            )
            if result.get("ok"):
                self.trails.remove(ticker)
        return actions

    def run_once(self, top_n: int | None = None) -> AutopilotResult:
        top_n = top_n or self.settings.top_n
        actions: list[dict] = []
        analysis = self.pipeline.analyze(top_n=top_n)

        try:
            portfolio = self.broker.status()
        except Exception as exc:
            return AutopilotResult(
                ts=datetime.now(timezone.utc).isoformat(),
                actions=[],
                portfolio={},
                market=None,
                message=f"No se pudo leer portafolio ({self.mode}): {exc}",
                mode=self.mode,
            )

        if analysis.get("error"):
            return AutopilotResult(
                ts=datetime.now(timezone.utc).isoformat(),
                actions=[],
                portfolio=portfolio,
                market=None,
                message=analysis["error"],
                mode=self.mode,
            )

        price_map = {
            item["prediction"]["ticker"]: float(item["prediction"]["last_price"])
            for item in analysis.get("ranking", []) + analysis.get("recommendations", [])
        }
        # Completa precios con marks del portafolio
        for t, pos in (portfolio.get("positions") or {}).items():
            if t not in price_map:
                px = float(pos.get("last_price") or pos.get("current_price") or 0)
                if px > 0:
                    price_map[t] = px

        # Siempre gestiona stops/trailing aunque el bot esté en pausa
        actions.extend(self._manage_open_risk(portfolio, price_map))
        portfolio = self.broker.status()

        daily_pnl = float(portfolio.get("daily_pnl", 0.0) or 0.0)
        equity = float(portfolio.get("equity", 0.0) or 0.0)
        hit_daily_loss = (
            equity > 0 and daily_pnl <= -equity * self.settings.max_daily_loss_pct
        )

        if hit_daily_loss and not portfolio.get("halted"):
            # 1) Cierra perdedoras (o flatten)  2) pausa nuevas compras
            if self.settings.halt_flatten_all:
                actions.extend(
                    self._close_positions_for_kill_switch(
                        portfolio, price_map, losers_only=False
                    )
                )
            elif self.settings.halt_close_losers:
                actions.extend(
                    self._close_positions_for_kill_switch(
                        portfolio, price_map, losers_only=True
                    )
                )
            portfolio = self.broker.halt("max_daily_loss")
            closed_n = sum(1 for a in actions if a.get("kill_switch") and a.get("ok"))
            try:
                from advisor.portfolio.audit import AuditLog

                AuditLog(self.settings).record(
                    "kill_switch",
                    level="warn",
                    source=f"autopilot:{self.mode}",
                    summary=(
                        f"Pérdida diaria ≤ −{self.settings.max_daily_loss_pct:.0%}. "
                        f"Pausa compras · cerradas={closed_n}"
                    ),
                    payload={
                        "daily_pnl": daily_pnl,
                        "equity": equity,
                        "close_losers": self.settings.halt_close_losers,
                        "flatten_all": self.settings.halt_flatten_all,
                        "actions": actions[-closed_n:] if closed_n else [],
                    },
                )
            except Exception:
                pass
            return AutopilotResult(
                ts=datetime.now(timezone.utc).isoformat(),
                actions=actions,
                portfolio=portfolio,
                market=analysis.get("market"),
                message=(
                    f"Kill-switch diario (−{self.settings.max_daily_loss_pct:.0%}): "
                    f"autopilot pausado"
                    + (
                        f" y se cerraron {closed_n} posición(es) en pérdida."
                        if closed_n
                        else (
                            " (sin posiciones perdedoras que cerrar)."
                            if self.settings.halt_close_losers
                            and not self.settings.halt_flatten_all
                            else "."
                        )
                    )
                ),
                mode=self.mode,
            )

        if portfolio.get("halted"):
            return AutopilotResult(
                ts=datetime.now(timezone.utc).isoformat(),
                actions=actions,
                portfolio=portfolio,
                market=analysis.get("market"),
                message=(
                    f"Autopilot en pausa: {portfolio.get('halt_reason')}. "
                    "Stops/trailing siguen activos; no hay compras nuevas."
                ),
                mode=self.mode,
            )

        open_positions = portfolio.get("positions", {}) or {}
        open_tickers = set(open_positions.keys())
        open_sectors = [
            str(p.get("sector") or self.trails.sector_of(t) or "Unknown")
            for t, p in open_positions.items()
        ]

        regime = (analysis.get("market") or {}).get("regime", "neutral")
        max_positions = self.settings.max_positions
        if regime == "risk_on":
            max_positions = min(max_positions + 1, 6)
        elif regime == "risk_off":
            max_positions = max(2, max_positions - 1)

        slots = max(max_positions - len(open_tickers), 0)
        candidates = []
        for item in analysis.get("actionable", []):
            pred = item["prediction"]
            plan = item["plan"]
            ticker = pred["ticker"]
            if ticker in open_tickers:
                continue
            if plan["action"] != Action.BUY.value:
                continue
            if float(plan["edge_net_pct"]) < self.settings.min_edge_net_pct:
                continue
            if float(pred["probability_up"]) < 0.51:
                continue
            # Gate IA: si está activo, exige approve_trade
            if self.settings.ai_enabled and self.settings.ai_gate_autopilot:
                ai = item.get("ai") or {}
                if not ai.get("approve_trade"):
                    actions.append(
                        {
                            "type": "ai_veto",
                            "ok": True,
                            "ticker": ticker,
                            "reason": (ai.get("summary") or "IA no aprueba la compra"),
                            "ai_action": ai.get("action"),
                            "conviction": ai.get("conviction"),
                        }
                    )
                    continue
            candidates.append((pred, plan))

        chosen = select_diversified(
            candidates,
            open_sectors=open_sectors,
            max_positions=slots,
            max_per_sector=self.settings.max_per_sector,
        )

        for pred, plan in chosen:
            ticker = pred["ticker"]
            result = self.broker.buy(
                ticker=ticker,
                price=float(plan["entry_price"]),
                position_pct=float(plan["position_pct"]),
                stop=float(plan["stop_price"]),
                target=float(plan["target_price"]),
                reason=(
                    f"auto_edge={plan['edge_net_pct']:.4f}"
                    f"|prob={pred['probability_up']:.2f}"
                    f"|stop_pct={plan.get('stop_pct', 0):.2%}"
                    f"|sector={pred.get('sector', 'Unknown')}"
                    f"|regime={regime}"
                    f"|mode={self.mode}"
                ),
                horizon_days=int(plan.get("horizon_days") or self.settings.horizon_days),
                sector=str(pred.get("sector") or "Unknown"),
            )
            actions.append({"type": "entry", "ticker": ticker, **result})
            if result.get("ok"):
                open_tickers.add(ticker)
                self.trails.upsert(
                    ticker,
                    entry=float(plan["entry_price"]),
                    stop=float(plan["stop_price"]),
                    initial_stop=float(plan["stop_price"]),
                    target=float(plan["target_price"]),
                    horizon_days=int(plan.get("horizon_days") or self.settings.horizon_days),
                    sector=str(pred.get("sector") or "Unknown"),
                )

        portfolio = self.broker.status()
        if not actions:
            message = (
                "Sin operaciones: no hay edge suficiente, sector saturado "
                "o ya está posicionado. Capital protegido."
            )
        else:
            done = [a for a in actions if a.get("ok")]
            message = f"Autopilot ({self.mode}) ejecutó {len(done)} acción(es)."

        try:
            AuditLog(self.settings).record(
                "autopilot",
                source=f"autopilot:{self.mode}",
                level="info" if actions else "info",
                summary=message,
                payload={
                    "mode": self.mode,
                    "n_actions": len(actions),
                    "entries": [a for a in actions if a.get("type") == "entry"],
                    "exits": [a for a in actions if a.get("type") in {"exit", "partial"}],
                    "ai_vetoes": [a for a in actions if a.get("type") == "ai_veto"],
                    "regime": (analysis.get("market") or {}).get("regime"),
                },
            )
        except Exception:
            pass

        return AutopilotResult(
            ts=datetime.now(timezone.utc).isoformat(),
            actions=actions,
            portfolio=portfolio,
            market=analysis.get("market"),
            message=message,
            mode=self.mode,
        )
