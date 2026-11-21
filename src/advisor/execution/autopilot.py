from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from advisor.advisory.pipeline import AdvisoryPipeline
from advisor.config import Settings, get_settings
from advisor.execution.paper_broker import PaperBroker
from advisor.execution.trail_store import TrailStore
from advisor.models import Action
from advisor.risk.trailing import ratchet_stop


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


class Autopilot:
    """Ejecuta automáticamente ideas con edge neto positivo."""

    def __init__(self, settings: Settings | None = None, mode: str = "alpaca"):
        self.settings = settings or get_settings()
        self.mode = mode.lower()
        self.pipeline = AdvisoryPipeline(self.settings)
        self.broker = build_broker(self.settings, self.mode)
        self.trails = TrailStore(self.settings)

    def _manage_open_risk(self, portfolio: dict, price_map: dict[str, float]) -> list[dict]:
        """Actualiza trailing/BE y ejecuta salidas stop/target."""
        actions: list[dict] = []
        positions = dict(portfolio.get("positions") or {})

        # En Alpaca el status puede no traer stop local → usar TrailStore
        for ticker, pos in list(positions.items()):
            px = price_map.get(ticker)
            if px is None:
                # intenta last_price de la posición
                px = float(pos.get("last_price") or pos.get("current_price") or 0)
            if not px:
                continue
            if hasattr(self.broker, "mark_price"):
                self.broker.mark_price(ticker, px)

            entry = float(pos.get("entry_price") or pos.get("avg_entry_price") or px)
            stop = float(pos.get("stop") or 0.0)
            target = float(pos.get("target") or 0.0)
            initial_stop = float(pos.get("initial_stop") or stop)

            stored = self.trails.get(ticker)
            if stored:
                stop = float(stored.get("stop") or stop)
                initial_stop = float(stored.get("initial_stop") or initial_stop)
                entry = float(stored.get("entry") or entry)
                target = float(stored.get("target") or target)

            if stop <= 0 or initial_stop <= 0:
                continue

            atr = None
            # atr_pct en factors no está en posición; trailing ATR usa gap aproximado
            update = ratchet_stop(
                entry=entry,
                current_stop=stop,
                mark_price=px,
                initial_stop=initial_stop,
                breakeven_at_r=self.settings.breakeven_at_r,
                trail_at_r=self.settings.trail_at_r,
                cost_buffer_pct=self.settings.round_trip_cost_pct / 2.0,
                atr=atr,
                atr_mult=self.settings.trail_atr_mult,
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
                    }
                )
                stop = update.stop

            if stop > 0 and px <= stop:
                result = self.broker.sell(ticker, px, reason=f"stop_loss|{update.event or 'initial'}")
                self.trails.remove(ticker)
                actions.append({"type": "exit", **result})
            elif target > 0 and px >= target:
                result = self.broker.sell(ticker, px, reason="take_profit")
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

        # Kill-switch por drawdown diario Alpaca/local (default −2% equity)
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

        open_tickers = set(portfolio.get("positions", {}).keys())
        max_positions = 4
        for item in analysis.get("actionable", []):
            if len(open_tickers) >= max_positions:
                break
            pred = item["prediction"]
            plan = item["plan"]
            ticker = pred["ticker"]
            if ticker in open_tickers:
                continue
            if plan["action"] != Action.BUY.value:
                continue
            if float(plan["edge_net_pct"]) < self.settings.min_edge_net_pct:
                continue
            if float(pred["probability_up"]) < 0.55:
                continue

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
                    f"|regime={analysis['market']['regime']}"
                    f"|mode={self.mode}"
                ),
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
                )

        portfolio = self.broker.status()
        if not actions:
            message = (
                "Sin operaciones: no hay edge suficiente o ya está posicionado. "
                "Capital protegido."
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
