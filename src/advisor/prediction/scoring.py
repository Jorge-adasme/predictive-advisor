from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from advisor.analysis.features import latest_feature_row
from advisor.models import Prediction, Regime, SymbolInfo
from advisor.prediction.calibration import calibrate_from_history


def _sigmoid(x: float) -> float:
    return float(1 / (1 + np.exp(-x)))


def score_symbol(
    symbol: SymbolInfo,
    history: pd.DataFrame,
    regime: Regime,
    horizon_days: int,
    benchmark_history: pd.DataFrame | None = None,
) -> Prediction | None:
    row = latest_feature_row(history, benchmark_df=benchmark_history)
    if row is None:
        return None

    momentum = float(np.clip(row["momentum"] / 0.2, -1.5, 1.5))
    momentum_20 = float(np.clip(row["momentum_20"] / 0.08, -1.5, 1.5))
    trend = float(np.clip(row["trend_strength"] / 0.04, -1.5, 1.5))
    rsi = float(row["rsi_14"])
    rsi_factor = float(np.clip((rsi - 50) / 25, -1.5, 1.5))
    vol = float(row["volatility_20d"])
    low_vol = float(np.clip((0.22 - vol) / 0.15, -1.0, 1.0))
    quality = float(np.clip(row["quality"] / 0.4, -1.5, 1.5))
    volume_confirm = float(np.clip(row["volume_z"] / 2.0, -1.0, 1.0))
    zscore = float(row["zscore_20"])
    adx = float(row.get("adx_14", 20.0))
    trend_quality = float(np.clip((adx - 18) / 25, -1.0, 1.5))
    reversal = float(np.clip(row.get("reversal_5d", 0.0) / 0.06, -1.5, 1.5))
    atr_pct = float(row.get("atr_pct", 0.02))
    rs_20 = float(row["rs_20"]) if "rs_20" in row and pd.notna(row["rs_20"]) else 0.0
    rs_factor = float(np.clip(rs_20 / 0.08, -1.5, 1.5))
    residual = float(row["residual_mom_20"]) if "residual_mom_20" in row and pd.notna(row["residual_mom_20"]) else 0.0
    residual_factor = float(np.clip(residual / 0.06, -1.5, 1.5))

    if regime == Regime.RISK_ON:
        weights = {
            "momentum": 0.16,
            "momentum_20": 0.10,
            "trend": 0.12,
            "rs": 0.18,
            "residual": 0.12,
            "rsi": 0.05,
            "low_vol": 0.05,
            "quality": 0.08,
            "volume": 0.06,
            "trend_quality": 0.08,
        }
    elif regime == Regime.RISK_OFF:
        weights = {
            "momentum": 0.05,
            "momentum_20": 0.05,
            "trend": 0.08,
            "rs": 0.10,
            "residual": 0.08,
            "rsi": 0.10,
            "low_vol": 0.20,
            "quality": 0.18,
            "volume": 0.06,
            "trend_quality": 0.10,
        }
        rsi_factor = float(np.clip((40 - rsi) / 20, -1.0, 1.0))
        # En stress, un poco de mean-reversion ayuda a no perseguir caídas
        weights["momentum"] *= 0.5
    else:
        weights = {
            "momentum": 0.12,
            "momentum_20": 0.08,
            "trend": 0.12,
            "rs": 0.16,
            "residual": 0.12,
            "rsi": 0.07,
            "low_vol": 0.10,
            "quality": 0.10,
            "volume": 0.06,
            "trend_quality": 0.07,
        }

    factors = {
        "momentum": momentum,
        "momentum_20": momentum_20,
        "trend": trend,
        "rs": rs_factor,
        "residual": residual_factor,
        "rsi": rsi_factor,
        "low_vol": low_vol,
        "quality": quality,
        "volume": volume_confirm,
        "trend_quality": trend_quality,
        "reversal_5d": reversal,
        "atr_pct": atr_pct,
    }

    score = sum(factors[k] * w for k, w in weights.items())

    # Penalizaciones de experto
    if abs(zscore) > 2.0:
        score -= np.sign(zscore) * 0.18
    if adx < 16:
        score *= 0.85  # mercado choppy: menos confianza direccional
    if atr_pct > 0.05:
        score -= 0.08  # ruido excesivo
    if float(row.get("above_200", 0.0)) < 1 and regime != Regime.RISK_OFF:
        score -= 0.05

    # Calibración empírica (más certera que score lineal)
    calib = calibrate_from_history(
        history=history,
        horizon_days=horizon_days,
        benchmark_df=benchmark_history,
    )
    empiric_er = calib["empirical_expected_return"]
    empiric_hit = calib["empirical_hit_rate"]
    calib_q = calib["calibration_quality"]

    horizon_scale = max(horizon_days / 10.0, 0.7)
    heuristic_er = float(np.clip(score * 0.015 * horizon_scale, -0.12, 0.12))

    if np.isfinite(empiric_er):
        # Blend: más peso a evidencia histórica cuando hay calidad
        expected_return = float(
            np.clip((1 - calib_q) * heuristic_er + calib_q * empiric_er, -0.15, 0.15)
        )
    else:
        expected_return = heuristic_er

    if np.isfinite(empiric_hit):
        probability_up = float(
            np.clip((1 - calib_q) * _sigmoid(score * 1.25) + calib_q * empiric_hit, 0.05, 0.95)
        )
    else:
        probability_up = _sigmoid(score * 1.25)

    confidence = float(
        np.clip(0.35 * abs(score) / 1.1 + 0.45 * calib_q + 0.20 * max(trend_quality, 0), 0.12, 0.93)
    )

    factors.update(
        {
            "empirical_expected_return": float(empiric_er) if np.isfinite(empiric_er) else 0.0,
            "empirical_hit_rate": float(empiric_hit) if np.isfinite(empiric_hit) else 0.0,
            "calibration_quality": float(calib_q),
            "sample_size": float(calib["sample_size"]),
        }
    )

    reasons: list[str] = []
    risks: list[str] = []

    if rs_factor > 0.4:
        reasons.append("Relative strength positivo vs benchmark (alpha táctico).")
    elif rs_factor < -0.4:
        risks.append("Relative strength negativo vs benchmark.")

    if residual_factor > 0.35:
        reasons.append("Momentum residual (idiosincrático) favorable.")

    if trend_quality > 0.3:
        reasons.append("Tendencia usable (ADX) — menos ruido lateral.")
    elif trend_quality < 0:
        risks.append("Mercado lateral/choppy: señales menos confiables.")

    if np.isfinite(empiric_hit) and empiric_hit >= 0.55:
        reasons.append(
            f"Calibración histórica: hit-rate ~{empiric_hit:.0%} en señales similares."
        )
    elif np.isfinite(empiric_hit) and empiric_hit < 0.48:
        risks.append("Calibración histórica débil para este tipo de señal.")

    if momentum > 0.4:
        reasons.append("Momentum a 60 días positivo.")
    elif momentum < -0.4:
        risks.append("Momentum a 60 días negativo.")

    if low_vol < -0.3:
        risks.append("Volatilidad alta: sizing más defensivo.")

    if rsi > 70:
        risks.append("RSI elevado: posible sobrecompra.")
    elif rsi < 30:
        reasons.append("RSI bajo: posible sobreventa táctica.")

    if not reasons:
        reasons.append("Señal mixta; edge depende de calibración/régimen.")

    as_of = history.index[-1].to_pydatetime()
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    return Prediction(
        ticker=symbol.ticker,
        name=symbol.name,
        sector=symbol.sector,
        as_of=as_of,
        horizon_days=horizon_days,
        last_price=float(row["Close"]),
        expected_return=expected_return,
        probability_up=probability_up,
        confidence=confidence,
        score=float(score),
        factors=factors,
        reasons=reasons,
        risks=risks,
    )
