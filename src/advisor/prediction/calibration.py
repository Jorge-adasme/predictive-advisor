from __future__ import annotations

import numpy as np
import pandas as pd

from advisor.analysis.features import align_relative_strength, compute_features


def _signal_series(featured: pd.DataFrame) -> pd.Series:
    """Proxy histórico alineado al ensemble v2."""
    mom = (featured.get("mom_12_1", featured["momentum"]) / 0.25).clip(-1.5, 1.5)
    mom_vs = (featured.get("mom_vol_scaled", featured["momentum"] / 0.2) / 1.2).clip(-1.5, 1.5)
    trend = (featured["trend_strength"] / 0.04).clip(-1.5, 1.5)
    rs = featured.get("rs_20", pd.Series(0.0, index=featured.index))
    rs_n = (rs / 0.08).clip(-1.5, 1.5)
    quality = (featured["quality"] / 0.4).clip(-1.5, 1.5)
    adx = ((featured.get("adx_14", 20) - 20) / 20).clip(-1.0, 1.5)
    macd = (featured.get("macd_hist", 0) / 0.01).clip(-1.5, 1.5)
    return (
        0.22 * mom
        + 0.16 * mom_vs
        + 0.14 * trend
        + 0.20 * rs_n
        + 0.12 * quality
        + 0.08 * adx
        + 0.08 * macd
    )


def calibrate_from_history(
    history: pd.DataFrame,
    horizon_days: int,
    benchmark_df: pd.DataFrame | None = None,
    min_samples: int = 40,
) -> dict[str, float]:
    """Calibración empírica con decay temporal + shrinkage Bayesiano + IC.

    - Vecinos de señal similares
    - Más peso a historia reciente
    - Shrinkage de E[r] hacia 0 (James-Stein lite) para no sobreconfiar
    - IC Spearman rolling como calidad de predictibilidad
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
            "ic_spearman": np.nan,
            "meta_label_prob": np.nan,
            "er_shrunk": np.nan,
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
            "ic_spearman": np.nan,
            "meta_label_prob": np.nan,
            "er_shrunk": np.nan,
        }

    latest_signal = float(signal.iloc[-1])
    dist = (panel["signal"] - latest_signal).abs()
    k = max(min_samples, int(len(panel) * 0.18))
    nbr_idx = dist.nsmallest(k).index
    neighbors = panel.loc[nbr_idx, "fwd"]

    # Decay temporal: más peso a observaciones recientes
    age = np.arange(len(panel.loc[nbr_idx]))[::-1]  # rough
    # Mejor: usar posición temporal real
    pos = panel.index.get_indexer(nbr_idx)
    recency = (pos - pos.min()) / max(pos.max() - pos.min(), 1)
    weights = 0.35 + 0.65 * recency  # 0.35..1.0
    weights = weights / weights.sum()

    empiric_er = float(np.sum(neighbors.values * weights))
    empiric_hit = float(np.sum((neighbors.values > 0).astype(float) * weights))

    # IC Spearman en ventana reciente (predictibilidad del signal)
    recent = panel.tail(min(126, len(panel)))
    if len(recent) >= 40:
        ic = float(recent["signal"].corr(recent["fwd"], method="spearman"))
    else:
        ic = np.nan

    # Shrinkage Bayesiano lite hacia 0 (priors conservadores)
    # Intensidad ↑ si poca muestra / IC débil / alta dispersión
    dispersion = float(np.sqrt(np.average((neighbors.values - empiric_er) ** 2, weights=weights)))
    shrink = float(np.clip(1.0 - (len(neighbors) / 120) * max(ic if np.isfinite(ic) else 0.0, 0.0), 0.25, 0.85))
    er_shrunk = float((1 - shrink) * empiric_er)  # pull to 0

    # Meta-label: P(ganar) aproximada por hit ponderado * (0.5+0.5*relu(IC))
    ic_boost = 0.5 + 0.5 * max(ic if np.isfinite(ic) else 0.0, 0.0)
    meta_label_prob = float(np.clip(empiric_hit * ic_boost, 0.05, 0.95))

    quality = float(
        np.clip(
            (len(neighbors) / 90)
            * (0.04 / max(dispersion, 0.008))
            * (0.55 + 0.45 * max(ic if np.isfinite(ic) else 0.0, 0.0)),
            0.05,
            1.0,
        )
    )

    return {
        "empirical_expected_return": empiric_er,
        "empirical_hit_rate": empiric_hit,
        "sample_size": float(len(neighbors)),
        "calibration_quality": quality,
        "ic_spearman": ic,
        "meta_label_prob": meta_label_prob,
        "er_shrunk": er_shrunk,
    }
