from __future__ import annotations

from typing import Iterable

import pandas as pd
import yfinance as yf

from advisor.adapters.base import MarketDataAdapter
from advisor.adapters.universe import load_universe
from advisor.config import Settings
from advisor.models import SymbolInfo


class YahooMarketDataAdapter(MarketDataAdapter):
    """Adapter inicial con Yahoo Finance (sufijo .SN para BCS)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.benchmark, self._symbols = load_universe(settings.universe_path)

    def load_universe(self) -> list[SymbolInfo]:
        return list(self._symbols)

    def get_history(
        self,
        tickers: Iterable[str],
        lookback_days: int,
    ) -> dict[str, pd.DataFrame]:
        requested = list(dict.fromkeys(tickers))
        downloadable = [t for t in requested if t != "CHILE_PROXY"]
        histories: dict[str, pd.DataFrame] = {}
        if not downloadable:
            return histories

        period_days = max(lookback_days + 40, 120)
        raw = yf.download(
            tickers=downloadable,
            period=f"{period_days}d",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )

        if raw.empty:
            return histories

        if len(downloadable) == 1:
            ticker = downloadable[0]
            frame = self._normalize_frame(raw.copy())
            if not frame.empty:
                histories[ticker] = frame.tail(lookback_days)
        else:
            for ticker in downloadable:
                if ticker not in raw.columns.get_level_values(0):
                    continue
                frame = self._normalize_frame(raw[ticker].copy())
                if not frame.empty:
                    histories[ticker] = frame.tail(lookback_days)

        if "CHILE_PROXY" in requested or self.benchmark == "CHILE_PROXY":
            proxy = self._build_chile_proxy(histories)
            if proxy is not None and not proxy.empty:
                histories["CHILE_PROXY"] = proxy.tail(lookback_days)
        return histories

    @staticmethod
    def _build_chile_proxy(histories: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
        closes = []
        for ticker, frame in histories.items():
            if ticker.endswith(".SN") and "Close" in frame.columns:
                closes.append(frame["Close"].rename(ticker))
        if len(closes) < 5:
            return None
        panel = pd.concat(closes, axis=1).dropna(how="all")
        # Retorno promedio equal-weight → índice sintético tipo IPSA líquido
        rets = panel.pct_change(fill_method=None).mean(axis=1)
        index = (1 + rets.fillna(0)).cumprod() * 1000
        # Volumen sintético estable para no romper features
        volume = panel.notna().sum(axis=1) * 1_000_000
        out = pd.DataFrame(
            {
                "Open": index,
                "High": index * 1.001,
                "Low": index * 0.999,
                "Close": index,
                "Volume": volume,
            },
            index=panel.index,
        )
        return out.dropna()

    @staticmethod
    def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.rename(columns=str.title)
        required = ["Open", "High", "Low", "Close", "Volume"]
        missing = [col for col in required if col not in frame.columns]
        if missing:
            return pd.DataFrame()
        out = frame[required].dropna(subset=["Close"]).copy()
        out.index = pd.to_datetime(out.index)
        out = out.sort_index()
        return out
