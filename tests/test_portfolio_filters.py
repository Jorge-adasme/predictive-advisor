from __future__ import annotations

from advisor.risk.portfolio_filters import sector_capacity_ok, select_diversified
from advisor.risk.trailing import should_partial_take, should_time_stop


def test_sector_capacity():
    assert sector_capacity_ok("Tech", [], max_per_sector=1)
    assert not sector_capacity_ok("Tech", ["Tech"], max_per_sector=1)
    assert sector_capacity_ok("Tech", ["Tech"], max_per_sector=2)


def test_select_diversified_skips_same_sector():
    cands = [
        ({"ticker": "AAPL", "sector": "Tech"}, {"x": 1}),
        ({"ticker": "MSFT", "sector": "Tech"}, {"x": 2}),
        ({"ticker": "JPM", "sector": "Financials"}, {"x": 3}),
    ]
    chosen = select_diversified(cands, open_sectors=[], max_positions=3, max_per_sector=1)
    tickers = [p["ticker"] for p, _ in chosen]
    assert tickers == ["AAPL", "JPM"]


def test_partial_and_time_stop_helpers():
    assert should_partial_take(
        entry=100, mark_price=104.5, initial_stop=97, already_taken=False, partial_at_r=1.5
    )
    assert not should_partial_take(
        entry=100, mark_price=104.5, initial_stop=97, already_taken=True, partial_at_r=1.5
    )
    assert should_time_stop(
        entry=100,
        mark_price=100.5,
        initial_stop=97,
        days_held=7,
        horizon_days=10,
        time_stop_frac=0.7,
        min_r=0.3,
    )
