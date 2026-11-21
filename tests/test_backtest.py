from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from advisor.backtest.walk_forward import (
    WalkForwardBacktester,
    _metrics_from_returns,
    _simulate_hold,
)
from advisor.config import Settings
from advisor.models import SymbolInfo


def test_simulate_hold_hits_stop_first():
    idx = pd.date_range("2024-01-02", periods=5, freq="B")
    path = pd.DataFrame(
        {
            "Open": [100, 99, 98, 97, 96],
            "High": [101, 100, 99, 105, 97],  # day 4 would hit target but after stop day
            "Low": [99, 97, 94, 96, 95],  # day 3 hits stop 95
            "Close": [100, 98, 95, 104, 96],
            "Volume": [1e6] * 5,
        },
        index=idx,
    )
    px, reason, ts = _simulate_hold(path, entry_price=100, stop=95, target=104, horizon_days=5)
    assert reason == "stop"
    assert px == 95


def test_metrics_from_returns():
    total, dd, sharpe = _metrics_from_returns([0.01, -0.005, 0.02], periods_per_year=25.2)
    assert total > 0
    assert dd <= 0


def test_walk_forward_with_injected_histories(monkeypatch):
    """Backtest extremo con datos sintéticos (sin red)."""
    rng = np.random.default_rng(7)
    n = 420
    idx = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq="B")

    def _mk(drift: float) -> pd.DataFrame:
        rets = rng.normal(loc=drift, scale=0.012, size=n)
        close = 100 * np.cumprod(1 + rets)
        return pd.DataFrame(
            {
                "Open": close * 0.99,
                "High": close * 1.015,
                "Low": close * 0.985,
                "Close": close,
                "Volume": rng.integers(2e5, 9e5, size=n),
            },
            index=idx,
        )

    histories = {
        "SPY": _mk(0.0004),
        "AAA": _mk(0.0010),
        "BBB": _mk(0.0002),
        "CCC": _mk(-0.0001),
    }
    symbols = [
        SymbolInfo(ticker="AAA", name="A", sector="Tech"),
        SymbolInfo(ticker="BBB", name="B", sector="Health"),
        SymbolInfo(ticker="CCC", name="C", sector="Energy"),
    ]

    class FakeAdapter:
        benchmark = "SPY"

        def load_universe(self):
            return symbols + [SymbolInfo(ticker="SPY", name="SPY", sector="ETF")]

        def get_history(self, tickers, lookback_days):
            return {t: histories[t].tail(lookback_days).copy() for t in tickers if t in histories}

    settings = Settings(
        universe_path=Settings().universe_path,
        commission_rate=0.0,
        slippage_bps=5.0,
        min_edge_net_pct=0.001,
        horizon_days=10,
    )
    bt = WalkForwardBacktester(settings)
    monkeypatch.setattr(
        "advisor.backtest.walk_forward.YahooMarketDataAdapter",
        lambda settings: FakeAdapter(),
    )
    result = bt.run(
        lookback_days=400,
        train_bars=180,
        step_days=10,
        horizon_days=10,
        max_positions=2,
    )
    assert result.n_rebalances > 0
    assert isinstance(result.expectancy_net, float)
    assert result.round_trip_cost_pct > 0
