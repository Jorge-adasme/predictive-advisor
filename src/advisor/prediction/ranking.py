from __future__ import annotations

import numpy as np

from advisor.models import Prediction


def apply_cross_sectional_ranks(predictions: list[Prediction]) -> list[Prediction]:
    """Re-rankea por z-score cross-sectional del score + E[r] empírico.

    Esto imita praxis cuant: no basta ser 'bueno', hay que ser top del universo.
    """
    if len(predictions) < 3:
        return predictions

    scores = np.array([p.score for p in predictions], dtype=float)
    ers = np.array([p.expected_return for p in predictions], dtype=float)

    def _z(x: np.ndarray) -> np.ndarray:
        mu = np.nanmean(x)
        sd = np.nanstd(x)
        if not np.isfinite(sd) or sd < 1e-9:
            return np.zeros_like(x)
        return (x - mu) / sd

    z_score = _z(scores)
    z_er = _z(ers)
    composite = 0.55 * z_score + 0.45 * z_er

    ranked = []
    for pred, cs in zip(predictions, composite):
        factors = dict(pred.factors)
        factors["cross_sectional_z"] = float(cs)
        # Ajuste suave del score final
        new_score = float(pred.score + 0.15 * cs)
        ranked.append(
            pred.model_copy(
                update={
                    "score": new_score,
                    "factors": factors,
                    "confidence": float(np.clip(pred.confidence + 0.03 * max(cs, 0), 0.1, 0.95)),
                }
            )
        )

    return sorted(ranked, key=lambda p: p.score, reverse=True)
