from __future__ import annotations

import numpy as np
import pandas as pd

from advisor.analysis.features import align_relative_strength, compute_features


def _signal_series(featured: pd.DataFrame, regime_weight_momentum: float = 0.25) -> pd.Series:
    """Proxy histórico del score para calibración rolling."""
    mom = (featured["momentum"] / 0.2).clip(-1.5, 1.5)
    trend = (featured["trend_strength"] / 0.04).clip(-1.5, 1.5)
    rs = featured.get("rs_20", pd.Series(0, index=featured.index))
    rs_n = (rs / 0.08).clip(-1.5, 1.5)
    quality = (featured["quality"] / 0.4).clip(-1.5, 1.5)
    adx = ((featured.get("adx_14", 20) - 20) / 20).clip(-1.0, 1.5)
    return (
        regime_weight_momentum * mom
        + 0.20 * trend
        + 0.25 * rs_n
        + 0.20 * quality
        + 0.10 * adx
    )


def calibrate_from_history(
    history: pd.DataFrame,
    horizon_days: int,
    benchmark_df: pd.DataFrame | None = None,
    min_samples: int = 40,
) -> dict[str, float]:
    """Estima E[r] y hit-rate empíricos evitando look-ahead estricto al final.

    Usa señales retardadas y forward returns del mismo activo.
    """
    featured = (
        align_relative_strength(history, benchmark_df)
        if benchmark_df is not None and not benchmark_df.empty
        else compute_features(history)
    ).dropna()

    if len(featured) < min_samples + horizon_days + 5:
        return {
            "empirical_expected_return": np.nan,
            "empirical_hit_rate": np.nan,
            "sample_size": 0.0,
            "calibration_quality": 0.0,
        }

    signal = _signal_series(featured)
    fwd = featured["Close"].pct_change(horizon_days).shift(-horizon_days)
    panel = pd.DataFrame({"signal": signal, "fwd": fwd}).dropna()

    if len(panel) < min_samples:
        return {
            "empirical_expected_return": np.nan,
            "empirical_hit_rate": np.nan,
            "sample_size": float(len(panel)),
            "calibration_quality": 0.0,
        }

    latest_signal = float(signal.iloc[-1])
    # Vecinos: señales parecidas históricamente
    dist = (panel["signal"] - latest_signal).abs()
    k = max(min_samples, int(len(panel) * 0.15))
    neighbors = panel.loc[dist.nsmallest(k).index, "fwd"]

    empiric_er = float(neighbors.mean())
    empiric_hit = float((neighbors > 0).mean())
    # Calidad: más muestras + menor dispersión => mejor
    dispersion = float(neighbors.std()) if len(neighbors) > 2 else 1.0
    quality = float(np.clip((len(neighbors) / 80) * (0.05 / max(dispersion, 0.01)), 0.05, 1.0))

    return {
        "empirical_expected_return": empiric_er,
        "empirical_hit_rate": empiric_hit,
        "sample_size": float(len(neighbors)),
        "calibration_quality": quality,
    }
