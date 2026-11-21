from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

import pandas as pd

from advisor.models import SymbolInfo


class MarketDataAdapter(ABC):
    """Contrato para fuentes de market data (Yahoo, BTG, etc.)."""

    @abstractmethod
    def load_universe(self) -> list[SymbolInfo]:
        raise NotImplementedError

    @abstractmethod
    def get_history(
        self,
        tickers: Iterable[str],
        lookback_days: int,
    ) -> dict[str, pd.DataFrame]:
        """Devuelve OHLCV por ticker, index datetime ascendente."""
        raise NotImplementedError
