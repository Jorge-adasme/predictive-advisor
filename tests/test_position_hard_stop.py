from __future__ import annotations

from datetime import datetime, timezone

from advisor.config import Settings
from advisor.models import MarketSnapshot, Prediction, Regime
from advisor.risk.engine import build_trade_plan


def test_plan_respects_hard_position_loss():
    settings = Settings(max_position_loss_pct=0.025, min_stop_pct=0.08, atr_stop_mult=4.0)
    pred = Prediction(
        ticker="TEST",
        name="Test",
        sector="Tech",
        as_of=datetime.now(timezone.utc),
        horizon_days=10,
        last_price=100.0,
        expected_return=0.02,
        probability_up=0.6,
        confidence=0.6,
        score=0.4,
        factors={"atr_pct": 0.05, "meta_label_prob": 0.6},
        reasons=[],
        risks=[],
    )
    market = MarketSnapshot(
        as_of=datetime.now(timezone.utc),
        benchmark="SPY",
        regime=Regime.NEUTRAL,
        regime_score=0.0,
        benchmark_return_20d=0.01,
        benchmark_volatility_20d=0.15,
    )
    plan = build_trade_plan(pred, market, settings)
    assert plan is not None
    assert plan.action.value == "buy"
    # Stop no puede estar bajo el tope duro −2.5%
    assert plan.stop_price >= 100.0 * (1 - 0.025) - 1e-6
