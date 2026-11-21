from __future__ import annotations

import numpy as np

from advisor.models import Prediction


def apply_cross_sectional_ranks(predictions: list[Prediction]) -> list[Prediction]:
    """Rank cross-sectional por IR proxy + score + E[r] shrunk.

    Prioriza ideas con mejor retorno ajustado a riesgo y mejor ranking relativo.
    """
    if len(predictions) < 3:
        return predictions

    scores = np.array([p.score for p in predictions], dtype=float)
    ers = np.array([p.expected_return for p in predictions], dtype=float)
    irs = np.array([float(p.factors.get("ir_proxy", 0.0)) for p in predictions], dtype=float)
    metas = np.array([float(p.factors.get("meta_label_prob", 0.0)) for p in predictions], dtype=float)

    def _z(x: np.ndarray) -> np.ndarray:
        mu = np.nanmean(x)
        sd = np.nanstd(x)
        if not np.isfinite(sd) or sd < 1e-9:
            return np.zeros_like(x)
        return (x - mu) / sd

    composite = (
        0.30 * _z(scores)
        + 0.25 * _z(ers)
        + 0.30 * _z(irs)
        + 0.15 * _z(metas)
    )

    # Penalización suave por concentración sectorial del top
    sector_counts: dict[str, int] = {}
    for p in predictions:
        sector_counts[p.sector] = sector_counts.get(p.sector, 0) + 1

    ranked = []
    for pred, cs in zip(predictions, composite):
        factors = dict(pred.factors)
        factors["cross_sectional_z"] = float(cs)
        # Si el sector está saturado en el universo, leve restado
        sat = sector_counts.get(pred.sector, 1)
        sector_pen = 0.03 * max(sat - 3, 0)
        new_score = float(pred.score + 0.18 * cs - sector_pen)
        ranked.append(
            pred.model_copy(
                update={
                    "score": new_score,
                    "factors": factors,
                    "confidence": float(
                        np.clip(pred.confidence + 0.04 * max(cs, 0) - sector_pen, 0.1, 0.95)
                    ),
                }
            )
        )

    return sorted(ranked, key=lambda p: p.score, reverse=True)
