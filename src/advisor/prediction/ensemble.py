from __future__ import annotations

import numpy as np

from advisor.models import Regime


def ensemble_sleeves(
    *,
    regime: Regime,
    mom_12_1: float,
    mom_vol_scaled: float,
    trend: float,
    rs: float,
    residual: float,
    reversal: float,
    quality: float,
    low_vol: float,
    trend_quality: float,
    macd: float,
    dist_52w: float,
    skew: float,
) -> tuple[float, dict[str, float], dict[str, float]]:
    """Ensemble de 3 sleeves cuantitativos.

    1) Trend/momentum
    2) Residual alpha (idiosincrático)
    3) Defensive / mean-reversion táctica
    """
    sleeve_trend = (
        0.35 * mom_12_1
        + 0.20 * mom_vol_scaled
        + 0.20 * trend
        + 0.15 * macd
        + 0.10 * trend_quality
    )
    # Penaliza chase de máximos exhaustos
    if dist_52w > -0.02 and mom_vol_scaled > 0.8:
        sleeve_trend -= 0.12

    sleeve_alpha = (
        0.40 * rs
        + 0.35 * residual
        + 0.15 * quality
        + 0.10 * macd
    )

    sleeve_defensive = (
        0.30 * low_vol
        + 0.25 * quality
        + 0.20 * reversal
        + 0.15 * trend_quality
        + 0.10 * (-min(skew, 0))  # premia menos cola izquierda
    )

    if regime == Regime.RISK_ON:
        w = {"trend": 0.45, "alpha": 0.40, "defensive": 0.15}
    elif regime == Regime.RISK_OFF:
        w = {"trend": 0.15, "alpha": 0.30, "defensive": 0.55}
    else:
        w = {"trend": 0.35, "alpha": 0.40, "defensive": 0.25}

    score = (
        w["trend"] * sleeve_trend
        + w["alpha"] * sleeve_alpha
        + w["defensive"] * sleeve_defensive
    )

    sleeves = {
        "sleeve_trend": float(sleeve_trend),
        "sleeve_alpha": float(sleeve_alpha),
        "sleeve_defensive": float(sleeve_defensive),
    }
    return float(score), w, sleeves
