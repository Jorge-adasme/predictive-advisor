from __future__ import annotations

from advisor.adapters.alpaca_data import AlpacaMarketDataAdapter
from advisor.config import Settings
from advisor.config import ROOT_DIR


def test_alpaca_adapter_falls_back_without_keys():
    settings = Settings(
        alpaca_api_key="",
        alpaca_secret_key="",
        universe_path=ROOT_DIR / "configs" / "universe_alpaca_us.json",
        lookback_days=120,
    )
    adapter = AlpacaMarketDataAdapter(settings)
    symbols = adapter.load_universe()
    assert any(s.ticker == "AAPL" for s in symbols)
    hist = adapter.get_history(["AAPL", "SPY"], lookback_days=80)
    assert "AAPL" in hist
    assert not hist["AAPL"].empty
