from __future__ import annotations

from pathlib import Path

from advisor.adapters.universe import load_universe
from advisor.config import ROOT_DIR


def test_alpaca_universe_is_broad_and_unique():
    path = ROOT_DIR / "configs" / "universe_alpaca_us.json"
    benchmark, symbols = load_universe(path)
    assert benchmark == "SPY"
    assert len(symbols) >= 200
    tickers = [s.ticker for s in symbols]
    assert len(tickers) == len(set(tickers))
    # Cobertura mínima de sectores / ETFs Alpaca
    sectors = {s.sector for s in symbols}
    assert "Tech" in sectors
    assert "ETF" in sectors
    assert "Financials" in sectors
    assert "SPY" in tickers
    assert "QQQ" in tickers
