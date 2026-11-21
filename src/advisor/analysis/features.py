from __future__ import annotations

import numpy as np
import pandas as pd


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Features técnicos/factoriales orientados a edge táctico."""
    out = df.copy()
    close = out["Close"]
    high = out["High"] if "High" in out.columns else close
    low = out["Low"] if "Low" in out.columns else close
    volume = out["Volume"].replace(0, np.nan)

    out["ret_1d"] = close.pct_change()
    out["ret_5d"] = close.pct_change(5)
    out["ret_10d"] = close.pct_change(10)
    out["ret_20d"] = close.pct_change(20)
    out["ret_60d"] = close.pct_change(60)

    out["sma_20"] = close.rolling(20).mean()
    out["sma_50"] = close.rolling(50).mean()
    out["sma_200"] = close.rolling(200).mean()

    out["momentum"] = close / close.shift(60) - 1
    out["momentum_20"] = close / close.shift(20) - 1
    out["trend_strength"] = (out["sma_20"] / out["sma_50"] - 1).clip(-0.2, 0.2)
    out["above_200"] = (close > out["sma_200"]).astype(float)

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    out["rsi_14"] = 100 - (100 / (1 + rs))

    out["volatility_20d"] = out["ret_1d"].rolling(20).std() * np.sqrt(252)
    vol_std = volume.rolling(20).std().replace(0, np.nan)
    out["volume_z"] = ((volume - volume.rolling(20).mean()) / vol_std).fillna(0.0)

    # Liquidez aproximada: volumen USD/CLP relativo
    dollar_vol = (close * volume).rolling(20).mean()
    out["liquidity_score"] = np.log1p(dollar_vol.replace(0, np.nan))

    # ATR(14)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr_14"] = tr.rolling(14).mean()
    out["atr_pct"] = out["atr_14"] / close

    # ADX-lite (tendencia usable vs chop)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr = out["atr_14"].replace(0, np.nan)
    plus_di = 100 * pd.Series(plus_dm, index=out.index).rolling(14).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=out.index).rolling(14).mean() / atr
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0)
    out["adx_14"] = dx.rolling(14).mean()

    out["zscore_20"] = (close - out["sma_20"]) / close.rolling(20).std()
    out["gap_1d"] = close / prev_close - 1

    # Quality proxy: estabilidad de retornos (Sharpe rolling)
    out["quality"] = out["ret_1d"].rolling(60).mean() / out["ret_1d"].rolling(60).std()

    # Reversal corto (contrarian 5d) para no perseguir extremos
    out["reversal_5d"] = -out["ret_5d"]

    return out


def align_relative_strength(
    asset_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
) -> pd.DataFrame:
    """Agrega residual/relative strength vs benchmark."""
    out = compute_features(asset_df)
    b = compute_features(benchmark_df)[["ret_1d", "ret_20d", "ret_60d"]].rename(
        columns={
            "ret_1d": "b_ret_1d",
            "ret_20d": "b_ret_20d",
            "ret_60d": "b_ret_60d",
        }
    )
    out = out.join(b, how="left")
    out["rs_20"] = out["ret_20d"] - out["b_ret_20d"]
    out["rs_60"] = out["ret_60d"] - out["b_ret_60d"]
    # Beta rough + residual 20d
    cov = out["ret_1d"].rolling(60).cov(out["b_ret_1d"])
    var = out["b_ret_1d"].rolling(60).var().replace(0, np.nan)
    out["beta_60"] = cov / var
    out["residual_1d"] = out["ret_1d"] - out["beta_60"] * out["b_ret_1d"]
    out["residual_mom_20"] = out["residual_1d"].rolling(20).sum()
    return out


def latest_feature_row(
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None = None,
) -> pd.Series | None:
    featured = (
        align_relative_strength(df, benchmark_df)
        if benchmark_df is not None and not benchmark_df.empty
        else compute_features(df)
    )
    required = [
        "Close",
        "momentum",
        "momentum_20",
        "trend_strength",
        "rsi_14",
        "volatility_20d",
        "quality",
        "volume_z",
        "zscore_20",
        "sma_20",
        "sma_50",
        "sma_200",
        "atr_pct",
        "adx_14",
        "reversal_5d",
    ]
    featured = featured.dropna(subset=[c for c in required if c in featured.columns])
    if featured.empty:
        return None
    return featured.iloc[-1]
