from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from advisor.advisory.pipeline import AdvisoryPipeline
from advisor.config import Settings, get_settings
from advisor.execution.paper_broker import PaperBroker
from advisor.models import Action


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

        # Kill-switch por drawdown diario Alpaca/local
        daily_pnl = float(portfolio.get("daily_pnl", 0.0) or 0.0)
        equity = float(portfolio.get("equity", 0.0) or 0.0)
        if equity > 0 and daily_pnl <= -equity * self.settings.max_daily_loss_pct:
            portfolio = self.broker.halt("max_daily_loss")
            return AutopilotResult(
                ts=datetime.now(timezone.utc).isoformat(),
                actions=actions,
                portfolio=portfolio,
                market=analysis.get("market"),
                message="Se alcanzó max pérdida diaria. Autopilot detenido.",
                mode=self.mode,
            )

        price_map = {
            item["prediction"]["ticker"]: float(item["prediction"]["last_price"])
            for item in analysis.get("ranking", []) + analysis.get("recommendations", [])
        }

        # Salidas stop/target (para paper local; en Alpaca bracket suele manejarlo)
        for ticker, pos in list(portfolio.get("positions", {}).items()):
            px = price_map.get(ticker)
            if px is None:
                continue
            if hasattr(self.broker, "mark_price"):
                self.broker.mark_price(ticker, px)
            stop = float(pos.get("stop") or 0.0)
            target = float(pos.get("target") or 0.0)
            # En Alpaca no siempre persistimos stop/target locales
            if stop > 0 and px <= stop:
                result = self.broker.sell(ticker, px, reason="stop_loss")
                actions.append({"type": "exit", **result})
            elif target > 0 and px >= target:
                result = self.broker.sell(ticker, px, reason="take_profit")
                actions.append({"type": "exit", **result})

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
                    f"|regime={analysis['market']['regime']}"
                    f"|mode={self.mode}"
                ),
            )
            actions.append({"type": "entry", "ticker": ticker, **result})
            if result.get("ok"):
                open_tickers.add(ticker)

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
