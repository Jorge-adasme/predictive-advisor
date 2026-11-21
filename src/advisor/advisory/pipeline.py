from __future__ import annotations

from advisor.adapters.alpaca_data import AlpacaMarketDataAdapter
from advisor.adapters.btg import BTGChileAdapter
from advisor.adapters.yahoo import YahooMarketDataAdapter
from advisor.analysis.regime import detect_regime
from advisor.config import Settings, get_settings
from advisor.models import Action, Recommendation
from advisor.ai.decision_agent import DecisionAgent
from advisor.events.earnings import EarningsCalendar
from advisor.news.engine import NewsEngine
from advisor.portfolio.audit import AuditLog
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

        earnings_map = {}
        earnings_dict = None
        if self.settings.earnings_enabled:
            try:
                earnings_map = EarningsCalendar(self.settings).snapshot(
                    [s.ticker for s in symbols]
                )
                earnings_dict = {k: v.to_dict() for k, v in earnings_map.items()}
            except Exception:
                earnings_map = {}
                earnings_dict = None

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
            earn = earnings_map.get(symbol.ticker)
            pred = score_symbol(
                symbol=symbol,
                history=hist,
                regime=market.regime,
                horizon_days=self.settings.horizon_days,
                benchmark_history=benchmark_df,
                news_factor=nf,
                news_weight=self.settings.news_weight,
                news_urgency=nu,
                earnings_blackout=bool(earn.in_blackout) if earn else False,
                days_to_earnings=earn.days_to_earnings if earn else None,
            )
            if pred is not None:
                predictions.append(pred)

        predictions = apply_cross_sectional_ranks(predictions)

        all_recs: list[Recommendation] = []
        for pred in predictions:
            plan = build_trade_plan(pred, market, self.settings)
            if plan is None:
                # Fallback: nunca silenciar un activo del universo
                from advisor.risk.engine import _avoid_plan

                plan = _avoid_plan(
                    pred,
                    pred.expected_return - self.settings.round_trip_cost_pct,
                    "Sin plan operable.",
                )
            all_recs.append(Recommendation(prediction=pred, plan=plan, market=market, rank=0))

        ranking = []
        for idx, rec in enumerate(all_recs[: max(top_n * 2, top_n)], start=1):
            ranking.append(rec.model_copy(update={"rank": idx}))

        # Compras ejecutables (autopilot)
        actionable = [
            r.model_copy()
            for r in all_recs
            if r.plan.action == Action.BUY and r.plan.position_pct > 0
        ]
        actionable = sorted(
            actionable,
            key=lambda r: (float(r.plan.edge_net_pct), float(r.prediction.score)),
            reverse=True,
        )[:top_n]
        for idx, rec in enumerate(actionable, start=1):
            actionable[idx - 1] = rec.model_copy(update={"rank": idx})

        # Oportunidades amplias: BUY + HOLD (cualquier chance razonable)
        opportunities = [
            r.model_copy()
            for r in all_recs
            if r.plan.action in {Action.BUY, Action.HOLD} and r.plan.position_pct > 0
        ]
        opportunities = sorted(
            opportunities,
            key=lambda r: (float(r.plan.edge_net_pct), float(r.prediction.score)),
            reverse=True,
        )[:top_n]
        for idx, rec in enumerate(opportunities, start=1):
            opportunities[idx - 1] = rec.model_copy(update={"rank": idx})

        # "No invertir": AVOID primero; si faltan, completa con peores HOLD
        avoid_hard = [r for r in all_recs if r.plan.action == Action.AVOID]
        avoid_hard = sorted(
            avoid_hard,
            key=lambda r: (
                float(r.prediction.score),
                float(r.prediction.expected_return),
                float(r.prediction.factors.get("news_factor", 0.0)),
                float(r.plan.edge_net_pct),
            ),
        )
        opp_tickers = {r.prediction.ticker for r in opportunities}
        weak_holds = [
            r
            for r in all_recs
            if r.plan.action == Action.HOLD and r.prediction.ticker not in opp_tickers
        ]
        weak_holds = sorted(
            weak_holds,
            key=lambda r: (float(r.prediction.score), float(r.plan.edge_net_pct)),
        )
        avoid_pool = list(avoid_hard) + list(weak_holds)
        # Garantiza al menos top_n visibles en UI
        if len(avoid_pool) < max(5, top_n // 2):
            leftovers = [
                r
                for r in sorted(
                    all_recs,
                    key=lambda r: (float(r.prediction.score), float(r.plan.edge_net_pct)),
                )
                if r.prediction.ticker not in opp_tickers
                and all(r.prediction.ticker != a.prediction.ticker for a in avoid_pool)
            ]
            avoid_pool.extend(leftovers)
        do_not_invest = []
        for idx, rec in enumerate(avoid_pool[:top_n], start=1):
            do_not_invest.append(rec.model_copy(update={"rank": idx}))

        n_buy = len(actionable)
        n_opp = len(opportunities)
        n_avoid = len(do_not_invest)
        message = (
            f"{n_opp} oportunidades ({n_buy} buy / {n_opp - n_buy} watch) · "
            f"{n_avoid} a evitar · escaneados {len(predictions)}."
        )

        board: list[Recommendation] = list(opportunities)
        for rec in do_not_invest:
            if all(rec.prediction.ticker != x.prediction.ticker for x in board):
                board.append(rec)
        recommendations = [
            r.model_copy(update={"rank": i}) for i, r in enumerate(board[: top_n * 2], start=1)
        ]

        market_dict = market.model_dump(mode="json")
        opp_payload = [r.model_dump(mode="json") for r in opportunities]
        avoid_payload = [r.model_dump(mode="json") for r in do_not_invest]
        actionable_payload = [r.model_dump(mode="json") for r in actionable]

        # Capa IA: decide buy/hold/avoid y puede vetar autopilot
        ai_decisions: list[dict] = []
        ai_meta = {"enabled": False, "provider": "off"}
        if self.settings.ai_enabled:
            agent = DecisionAgent(self.settings)
            decide_pool = opp_payload[: min(10, len(opp_payload))] + avoid_payload[: min(8, len(avoid_payload))]
            # dedupe tickers
            seen: set[str] = set()
            unique_pool = []
            for it in decide_pool:
                tk = it["prediction"]["ticker"]
                if tk in seen:
                    continue
                seen.add(tk)
                unique_pool.append(it)
            decisions = agent.decide_many(
                market=market_dict,
                news=news_dict,
                items=unique_pool,
                max_items=12,
            )
            ai_decisions = [d.to_dict() for d in decisions]
            by_tk = {d["ticker"]: d for d in ai_decisions}

            def _attach(rows: list[dict]) -> list[dict]:
                out = []
                for row in rows:
                    tk = row["prediction"]["ticker"]
                    if tk in by_tk:
                        row = {**row, "ai": by_tk[tk]}
                    out.append(row)
                return out

            opp_payload = _attach(opp_payload)
            avoid_payload = _attach(avoid_payload)
            actionable_payload = _attach(actionable_payload)
            # Autopilot solo ideas que la IA aprueba (si gate activo)
            if self.settings.ai_gate_autopilot:
                actionable_payload = [
                    r
                    for r in actionable_payload
                    if (r.get("ai") or {}).get("approve_trade") is True
                ]
            ai_meta = {
                "enabled": True,
                "provider": agent.provider,
                "gate_autopilot": self.settings.ai_gate_autopilot,
                "n_decisions": len(ai_decisions),
            }
            message = (
                f"{message} · IA({ai_meta['provider']}): "
                f"{sum(1 for d in ai_decisions if d['action']=='buy')} buy / "
                f"{sum(1 for d in ai_decisions if d['action']=='hold')} hold / "
                f"{sum(1 for d in ai_decisions if d['action']=='avoid')} avoid."
            )

        result = {
            "market": market_dict,
            "recommendations": [r.model_dump(mode="json") for r in recommendations],
            "ranking": [r.model_dump(mode="json") for r in ranking],
            "actionable": actionable_payload,
            "opportunities": opp_payload,
            "do_not_invest": avoid_payload,
            "ai_decisions": ai_decisions,
            "ai": ai_meta,
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
            "earnings": earnings_dict,
            "message": message,
            "error": None,
            "disclaimer": (
                "Herramienta de apoyo a la decisión. No garantiza rentabilidad. "
                "Evalúa costos, liquidez y tu perfil de riesgo antes de operar."
            ),
        }
        try:
            AuditLog(self.settings).record(
                "analyze",
                source="pipeline",
                summary=message,
                payload={
                    "scanned": len(predictions),
                    "opportunities": len(opp_payload),
                    "avoid": len(avoid_payload),
                    "actionable": len(actionable_payload),
                    "regime": (market_dict or {}).get("regime"),
                    "ai": ai_meta,
                },
            )
        except Exception:
            pass
        return result

    def draft_order(self, recommendation: Recommendation) -> dict:
        return self.btg.create_order_draft(recommendation.plan.model_dump(mode="json"))
