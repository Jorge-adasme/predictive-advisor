from __future__ import annotations

from advisor.adapters.alpaca_data import AlpacaMarketDataAdapter
from advisor.adapters.btg import BTGChileAdapter
from advisor.adapters.yahoo import YahooMarketDataAdapter
from advisor.analysis.regime import detect_regime
from advisor.config import Settings, get_settings
from advisor.models import Action, Recommendation
from advisor.news.engine import NewsEngine
from advisor.prediction.ranking import apply_cross_sectional_ranks
from advisor.prediction.scoring import score_symbol
from advisor.risk.engine import build_trade_plan


def build_market_data_adapter(settings: Settings):
    broker = (settings.broker or "alpaca").lower()
    if broker in {"alpaca", "alpaca_paper", "alpaca_live"}:
        return AlpacaMarketDataAdapter(settings)
    return YahooMarketDataAdapter(settings)


class AdvisoryPipeline:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.market_data = build_market_data_adapter(self.settings)
        self.btg = BTGChileAdapter()

    def analyze(self, top_n: int | None = None) -> dict:
        top_n = top_n or self.settings.top_n
        symbols = self.market_data.load_universe()
        tickers = [s.ticker for s in symbols] + [self.market_data.benchmark]
        histories = self.market_data.get_history(tickers, self.settings.lookback_days)

        benchmark_df = histories.get(self.market_data.benchmark)
        if benchmark_df is None or benchmark_df.empty:
            for _, df in histories.items():
                if not df.empty:
                    benchmark_df = df
                    break

        if benchmark_df is None or benchmark_df.empty:
            return {
                "market": None,
                "recommendations": [],
                "ranking": [],
                "actionable": [],
                "scanned": 0,
                "broker": self.settings.broker,
                "btg_status": self.btg.status().__dict__,
                "message": None,
                "error": "No se pudieron descargar datos de mercado.",
            }

        news_pulse = None
        news_dict = None
        if self.settings.news_enabled:
            try:
                news_pulse = NewsEngine(self.settings).pulse(symbols)
                news_dict = news_pulse.to_dict()
            except Exception:
                news_pulse = None
                news_dict = None

        market = detect_regime(
            benchmark_df,
            self.market_data.benchmark,
            news=news_dict,
        )

        predictions = []
        for symbol in symbols:
            hist = histories.get(symbol.ticker)
            if hist is None or hist.empty:
                continue
            nf = 0.0
            nu = 0.0
            if news_pulse is not None:
                nf = news_pulse.factor_for(symbol.ticker, symbol.sector)
                nu = news_pulse.market_urgency
            pred = score_symbol(
                symbol=symbol,
                history=hist,
                regime=market.regime,
                horizon_days=self.settings.horizon_days,
                benchmark_history=benchmark_df,
                news_factor=nf,
                news_weight=self.settings.news_weight,
                news_urgency=nu,
            )
            if pred is not None:
                predictions.append(pred)

        predictions = apply_cross_sectional_ranks(predictions)

        all_recs: list[Recommendation] = []
        for pred in predictions:
            plan = build_trade_plan(pred, market, self.settings)
            if plan is None:
                continue
            all_recs.append(Recommendation(prediction=pred, plan=plan, market=market, rank=0))

        ranking = []
        for idx, rec in enumerate(all_recs[:top_n], start=1):
            ranking.append(rec.model_copy(update={"rank": idx}))

        actionable = [
            r.model_copy()
            for r in all_recs
            if r.plan.action == Action.BUY
            and r.plan.edge_net_pct >= self.settings.min_edge_net_pct
            and r.plan.position_pct > 0
        ][:top_n]
        for idx, rec in enumerate(actionable, start=1):
            actionable[idx - 1] = rec.model_copy(update={"rank": idx})

        if actionable:
            message = f"{len(actionable)} idea(s) con edge neto positivo tras costos."
            recommendations = actionable
        else:
            message = (
                "Hoy el sistema recomienda NO abrir operaciones: "
                "no hay edge neto suficiente después de costos/régimen. "
                "No operar también es una decisión rentable."
            )
            recommendations = ranking

        return {
            "market": market.model_dump(mode="json"),
            "recommendations": [r.model_dump(mode="json") for r in recommendations],
            "ranking": [r.model_dump(mode="json") for r in ranking],
            "actionable": [r.model_dump(mode="json") for r in actionable],
            "scanned": len(predictions),
            "broker": self.settings.broker,
            "cost_model": {
                "round_trip_cost_pct": self.settings.round_trip_cost_pct,
                "min_edge_net_pct": self.settings.min_edge_net_pct,
                "risk_per_trade": self.settings.risk_per_trade,
                "horizon_days": self.settings.horizon_days,
                "currency": self.settings.base_currency,
            },
            "btg_status": self.btg.status().__dict__,
            "news": news_dict,
            "message": message,
            "error": None,
        }

    def draft_order(self, recommendation: Recommendation) -> dict:
        return self.btg.create_order_draft(recommendation.plan.model_dump(mode="json"))
