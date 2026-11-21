from __future__ import annotations

import numpy as np
import pandas as pd


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Features técnicos/factoriales simples y robustos para MVP."""
    out = df.copy()
    close = out["Close"]
    volume = out["Volume"].replace(0, np.nan)

    out["ret_1d"] = close.pct_change()
    out["ret_5d"] = close.pct_change(5)
    out["ret_20d"] = close.pct_change(20)
    out["ret_60d"] = close.pct_change(60)

    out["sma_20"] = close.rolling(20).mean()
    out["sma_50"] = close.rolling(50).mean()
    out["sma_200"] = close.rolling(200).mean()

    out["momentum"] = close / close.shift(60) - 1
    out["trend_strength"] = (out["sma_20"] / out["sma_50"] - 1).clip(-0.2, 0.2)

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    out["rsi_14"] = 100 - (100 / (1 + rs))

    out["volatility_20d"] = out["ret_1d"].rolling(20).std() * np.sqrt(252)
    vol_std = volume.rolling(20).std().replace(0, np.nan)
    out["volume_z"] = ((volume - volume.rolling(20).mean()) / vol_std).fillna(0.0)

    # Mean-reversion suave
    out["zscore_20"] = (close - out["sma_20"]) / close.rolling(20).std()

    # Quality proxy: estabilidad de retornos
    out["quality"] = (
        out["ret_1d"].rolling(60).mean() / out["ret_1d"].rolling(60).std()
    )

    return out


def latest_feature_row(df: pd.DataFrame) -> pd.Series | None:
    featured = compute_features(df)
    required = [
        "Close",
        "momentum",
        "trend_strength",
        "rsi_14",
        "volatility_20d",
        "quality",
        "volume_z",
        "zscore_20",
        "sma_20",
        "sma_50",
        "sma_200",
    ]
    featured = featured.dropna(subset=[c for c in required if c in featured.columns])
    if featured.empty:
        return None
    return featured.iloc[-1]
