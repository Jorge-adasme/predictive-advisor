from __future__ import annotations

from datetime import datetime, timedelta, timezone

from advisor.events.earnings import EarningsInfo
from advisor.news.semantic import blend_sentiment, semantic_score
from advisor.config import Settings
from advisor.models import MarketSnapshot, Prediction, Regime
from advisor.risk.engine import build_trade_plan


def test_semantic_bull_vs_bear():
    bull = semantic_score("stocks rally to record highs after rate cut optimism")
    bear = semantic_score("markets crash on war fears and recession panic selloff")
    assert bull > bear


def test_blend_sentiment_uses_both():
    blended, lex, sem = blend_sentiment(
        "Federal Reserve rate cut fuels equity rally and strong growth",
        semantic_weight=0.55,
    )
    assert blended > 0
    assert lex != 0 or sem != 0


def test_earnings_blackout_blocks_buy():
    settings = Settings(earnings_enabled=True, min_edge_net_pct=0.001, slippage_bps=5)
    pred = Prediction(
        ticker="AAPL",
        name="Apple",
        sector="Tech",
        as_of=datetime.now(timezone.utc),
        horizon_days=10,
        last_price=100,
        expected_return=0.03,
        probability_up=0.7,
        confidence=0.7,
        score=0.8,
        factors={
            "atr_pct": 0.02,
            "meta_label_prob": 0.7,
            "ic_spearman": 0.1,
            "ir_proxy": 0.8,
            "cross_sectional_z": 0.5,
            "empirical_hit_rate": 0.6,
            "calibration_quality": 0.5,
            "news_factor": 0.2,
            "news_urgency": 0.1,
            "earnings_blackout": 1.0,
        },
    )
    market = MarketSnapshot(
        as_of=datetime.now(timezone.utc),
        benchmark="SPY",
        regime=Regime.RISK_ON,
        regime_score=1.0,
        benchmark_return_20d=0.03,
        benchmark_volatility_20d=0.15,
    )
    plan = build_trade_plan(pred, market, settings)
    assert plan is not None
    assert plan.action.value == "avoid"
    assert "earnings" in plan.invalidation.lower()


def test_earnings_info_dict():
    info = EarningsInfo(
        ticker="MSFT",
        next_earnings=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        days_to_earnings=1.0,
        in_blackout=True,
        blackout_reason="test",
    )
    assert info.to_dict()["in_blackout"] is True
