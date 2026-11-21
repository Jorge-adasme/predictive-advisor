from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

import pandas as pd

from advisor.adapters.base import MarketDataAdapter
from advisor.adapters.universe import load_universe
from advisor.adapters.yahoo import YahooMarketDataAdapter
from advisor.config import Settings
from advisor.models import SymbolInfo


class AlpacaMarketDataAdapter(MarketDataAdapter):
    """Market data USA via Alpaca; fallback a Yahoo si no hay keys/feed."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.benchmark, self._symbols = load_universe(settings.universe_path)
        self._yahoo = YahooMarketDataAdapter(settings)
        self._client = None
        if settings.alpaca_api_key and settings.alpaca_secret_key:
            try:
                from alpaca.data.historical import StockHistoricalDataClient

                self._client = StockHistoricalDataClient(
                    api_key=settings.alpaca_api_key,
                    secret_key=settings.alpaca_secret_key,
                )
            except Exception:
                self._client = None

    def load_universe(self) -> list[SymbolInfo]:
        return list(self._symbols)

    def get_history(
        self,
        tickers: Iterable[str],
        lookback_days: int,
    ) -> dict[str, pd.DataFrame]:
        tickers_list = list(dict.fromkeys(tickers))
        if self._client is None:
            # Reusa Yahoo con el mismo universe_path (USA)
            return self._yahoo.get_history(tickers_list, lookback_days)

        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame

            end = datetime.now(timezone.utc)
            start = end - timedelta(days=max(lookback_days + 40, 120))
            req = StockBarsRequest(
                symbol_or_symbols=tickers_list,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
            )
            bars = self._client.get_stock_bars(req)
            raw = bars.df
            if raw is None or raw.empty:
                return self._yahoo.get_history(tickers_list, lookback_days)

            histories: dict[str, pd.DataFrame] = {}
            if isinstance(raw.index, pd.MultiIndex):
                for ticker in tickers_list:
                    if ticker not in raw.index.get_level_values(0):
                        continue
                    frame = raw.xs(ticker, level=0).copy()
                    histories[ticker] = self._normalize(frame).tail(lookback_days)
            else:
                # Un solo símbolo
                ticker = tickers_list[0]
                histories[ticker] = self._normalize(raw.copy()).tail(lookback_days)
            # Completa faltantes con Yahoo
            missing = [t for t in tickers_list if t not in histories]
            if missing:
                histories.update(self._yahoo.get_history(missing, lookback_days))
            return histories
        except Exception:
            return self._yahoo.get_history(tickers_list, lookback_days)

    @staticmethod
    def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
        rename = {
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
        out = frame.rename(columns=rename)
        cols = ["Open", "High", "Low", "Close", "Volume"]
        missing = [c for c in cols if c not in out.columns]
        if missing:
            return pd.DataFrame()
        out = out[cols].dropna(subset=["Close"]).copy()
        out.index = pd.to_datetime(out.index)
        if getattr(out.index, "tz", None) is not None:
            out.index = out.index.tz_convert(None)
        return out.sort_index()
