from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from advisor.advisory.pipeline import AdvisoryPipeline
from advisor.config import Settings, get_settings
from advisor.execution.paper_broker import PaperBroker
from advisor.execution.trail_store import TrailStore
from advisor.models import Action
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

        if portfolio.get("halted"):
            return AutopilotResult(
                ts=datetime.now(timezone.utc).isoformat(),
                actions=[],
                portfolio=portfolio,
                market=analysis.get("market"),
                message=f"Autopilot en pausa: {portfolio.get('halt_reason')}",
                mode=self.mode,
            )

        daily_pnl = float(portfolio.get("daily_pnl", 0.0) or 0.0)
        equity = float(portfolio.get("equity", 0.0) or 0.0)
        if equity > 0 and daily_pnl <= -equity * self.settings.max_daily_loss_pct:
            portfolio = self.broker.halt("max_daily_loss")
            return AutopilotResult(
                ts=datetime.now(timezone.utc).isoformat(),
                actions=actions,
                portfolio=portfolio,
                market=analysis.get("market"),
                message=(
                    f"Se alcanzó max pérdida diaria "
                    f"(−{self.settings.max_daily_loss_pct:.0%}). Autopilot detenido."
                ),
                mode=self.mode,
            )

        price_map = {
            item["prediction"]["ticker"]: float(item["prediction"]["last_price"])
            for item in analysis.get("ranking", []) + analysis.get("recommendations", [])
        }

        actions.extend(self._manage_open_risk(portfolio, price_map))

        portfolio = self.broker.status()
        if portfolio.get("halted"):
            return AutopilotResult(
                ts=datetime.now(timezone.utc).isoformat(),
                actions=actions,
                portfolio=portfolio,
                market=analysis.get("market"),
                message="Autopilot detenido por kill-switch.",
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

        return AutopilotResult(
            ts=datetime.now(timezone.utc).isoformat(),
            actions=actions,
            portfolio=portfolio,
            market=analysis.get("market"),
            message=message,
            mode=self.mode,
        )
