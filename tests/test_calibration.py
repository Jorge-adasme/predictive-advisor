from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from advisor.prediction.calibration import calibrate_from_history
from advisor.prediction.ranking import apply_cross_sectional_ranks
from advisor.models import Prediction


def _hist(n=300, drift=0.001):
    rng = np.random.default_rng(7)
    rets = rng.normal(drift, 0.012, n)
    close = 100 * np.cumprod(1 + rets)
    idx = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": close * 0.99,
            "High": close * 1.01,
            "Low": close * 0.98,
            "Close": close,
            "Volume": rng.integers(1e5, 5e5, n),
        },
        index=idx,
    )


def test_calibration_returns_fields():
    out = calibrate_from_history(_hist(n=400), horizon_days=10)
    assert "empirical_expected_return" in out
    assert "empirical_hit_rate" in out
    assert "meta_label_prob" in out
    assert "er_shrunk" in out
    assert out["sample_size"] >= 0


def test_cross_sectional_rank_adds_z():
    preds = []
    for i, score in enumerate([0.1, 0.5, 1.0, -0.2]):
        preds.append(
            Prediction(
                ticker=f"T{i}",
                name=f"T{i}",
                sector="X",
                as_of=datetime.now(timezone.utc),
                horizon_days=10,
                last_price=10,
                expected_return=score * 0.01,
                probability_up=0.5,
                confidence=0.4,
                score=score,
            )
        )
    ranked = apply_cross_sectional_ranks(preds)
    assert "cross_sectional_z" in ranked[0].factors
    assert ranked[0].score >= ranked[-1].score
