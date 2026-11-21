from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from advisor.config import Settings
from advisor.models import MarketSnapshot, Prediction, Regime
from advisor.prediction.scoring import score_symbol
from advisor.risk.engine import build_trade_plan
from advisor.models import SymbolInfo


def _synthetic_history(n: int = 260, drift: float = 0.001) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rets = rng.normal(loc=drift, scale=0.012, size=n)
    close = 100 * np.cumprod(1 + rets)
    idx = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": close * 0.99,
            "High": close * 1.01,
            "Low": close * 0.98,
            "Close": close,
            "Volume": rng.integers(100000, 500000, size=n),
        },
        index=idx,
    )


def test_score_symbol_returns_prediction():
    symbol = SymbolInfo(ticker="TEST.SN", name="Test", sector="Test")
    pred = score_symbol(symbol, _synthetic_history(), Regime.NEUTRAL, horizon_days=5)
    assert pred is not None
    assert 0 <= pred.probability_up <= 1
    assert pred.last_price > 0


def test_build_trade_plan_filters_weak_edge():
    settings = Settings(min_edge_net_pct=0.05, commission_rate=0.01, slippage_bps=20)
    pred = Prediction(
        ticker="TEST.SN",
        name="Test",
        sector="Test",
        as_of=datetime.now(timezone.utc),
        horizon_days=5,
        last_price=100,
        expected_return=0.01,
        probability_up=0.55,
        confidence=0.4,
        score=0.2,
        reasons=["x"],
        risks=[],
    )
    market = MarketSnapshot(
        as_of=datetime.now(timezone.utc),
        benchmark="IPSA.SN",
        regime=Regime.NEUTRAL,
        regime_score=0.0,
        benchmark_return_20d=0.01,
        benchmark_volatility_20d=0.2,
    )
    plan = build_trade_plan(pred, market, settings)
    assert plan is not None
    assert plan.action.value == "avoid"
