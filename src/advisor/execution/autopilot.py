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


class Autopilot:
    """Ejecuta automáticamente solo ideas con edge neto positivo (paper por defecto).

    Objetivo: maximizar expectancy neta con protección de capital.
    No garantiza ganancias en cada operación.
    """

    def __init__(self, settings: Settings | None = None, mode: str = "paper"):
        if mode != "paper":
            raise ValueError(
                "Por ahora solo mode='paper'. Live BTG requiere API/partner oficial."
            )
        self.settings = settings or get_settings()
        self.pipeline = AdvisoryPipeline(self.settings)
        self.broker = PaperBroker(self.settings)

    def run_once(self, top_n: int | None = None) -> AutopilotResult:
        top_n = top_n or self.settings.top_n
        actions: list[dict] = []
        analysis = self.pipeline.analyze(top_n=top_n)
        portfolio = self.broker.status()

        if analysis.get("error"):
            return AutopilotResult(
                ts=datetime.now(timezone.utc).isoformat(),
                actions=[],
                portfolio=portfolio,
                market=None,
                message=analysis["error"],
            )

        if portfolio.get("halted"):
            return AutopilotResult(
                ts=datetime.now(timezone.utc).isoformat(),
                actions=[],
                portfolio=portfolio,
                market=analysis.get("market"),
                message=f"Autopilot en pausa: {portfolio.get('halt_reason')}",
            )

        # 1) Actualiza marks y gestiona salidas (stop/target)
        price_map = {
            item["prediction"]["ticker"]: float(item["prediction"]["last_price"])
            for item in analysis.get("ranking", []) + analysis.get("recommendations", [])
        }
        for ticker, pos in list(portfolio.get("positions", {}).items()):
            px = price_map.get(ticker)
            if px is None:
                continue
            self.broker.mark_price(ticker, px)
            stop = float(pos["stop"])
            target = float(pos["target"])
            if px <= stop:
                result = self.broker.sell(ticker, px, reason="stop_loss")
                actions.append({"type": "exit", **result})
            elif px >= target:
                result = self.broker.sell(ticker, px, reason="take_profit")
                actions.append({"type": "exit", **result})

        portfolio = self.broker.status()
        if portfolio.get("halted"):
            return AutopilotResult(
                ts=datetime.now(timezone.utc).isoformat(),
                actions=actions,
                portfolio=portfolio,
                market=analysis.get("market"),
                message="Se alcanzó max pérdida diaria. Autopilot detenido.",
            )

        # 2) Entradas nuevas solo BUY con edge neto
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
            message = f"Autopilot ejecutó {len(done)} acción(es)."

        return AutopilotResult(
            ts=datetime.now(timezone.utc).isoformat(),
            actions=actions,
            portfolio=portfolio,
            market=analysis.get("market"),
            message=message,
        )
