from __future__ import annotations

from datetime import datetime, timezone

from advisor.models import Action, MarketSnapshot, Prediction, Recommendation, Regime, TradePlan


def _rec(ticker: str, action: Action, edge: float, score: float) -> Recommendation:
    now = datetime.now(timezone.utc)
    market = MarketSnapshot(
        as_of=now,
        benchmark="SPY",
        regime=Regime.NEUTRAL,
        regime_score=0.0,
        benchmark_return_20d=0.0,
        benchmark_volatility_20d=0.1,
    )
    pred = Prediction(
        ticker=ticker,
        name=ticker,
        sector="Tech",
        as_of=now,
        horizon_days=10,
        last_price=100.0,
        expected_return=edge,
        probability_up=0.55,
        confidence=0.5,
        score=score,
    )
    plan = TradePlan(
        ticker=ticker,
        action=action,
        entry_price=100.0,
        stop_price=97.0,
        target_price=105.0,
        position_pct=0.05,
        risk_reward=1.5,
        edge_net_pct=edge,
        invalidation="t",
        horizon_days=10,
    )
    return Recommendation(prediction=pred, plan=plan, market=market, rank=0)


def test_quality_sort_buy_before_hold_before_avoid():
    rows = [
        _rec("C", Action.AVOID, 0.02, 0.9),
        _rec("B", Action.HOLD, 0.01, 0.4),
        _rec("A", Action.BUY, 0.005, 0.3),
        _rec("D", Action.BUY, 0.02, 0.2),
    ]

    def quality(r: Recommendation) -> tuple:
        action_rank = {Action.BUY: 3, Action.HOLD: 2, Action.AVOID: 0}[r.plan.action]
        return (
            action_rank,
            float(r.plan.edge_net_pct),
            float(r.prediction.score),
        )

    ordered = sorted(rows, key=quality, reverse=True)
    assert [r.prediction.ticker for r in ordered] == ["D", "A", "B", "C"]
