from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from advisor.analysis.features import latest_feature_row
from advisor.models import Prediction, Regime, SymbolInfo


def _sigmoid(x: float) -> float:
    return float(1 / (1 + np.exp(-x)))


def score_symbol(
    symbol: SymbolInfo,
    history: pd.DataFrame,
    regime: Regime,
    horizon_days: int,
) -> Prediction | None:
    row = latest_feature_row(history)
    if row is None:
        return None

    # Factores normalizados a [-1, 1] aprox.
    momentum = float(np.clip(row["momentum"] / 0.2, -1.5, 1.5))
    trend = float(np.clip(row["trend_strength"] / 0.04, -1.5, 1.5))
    rsi = float(row["rsi_14"])
    rsi_factor = float(np.clip((rsi - 50) / 25, -1.5, 1.5))
    vol = float(row["volatility_20d"])
    low_vol = float(np.clip((0.22 - vol) / 0.15, -1.0, 1.0))
    quality = float(np.clip(row["quality"] / 0.4, -1.5, 1.5))
    volume_confirm = float(np.clip(row["volume_z"] / 2.0, -1.0, 1.0))
    zscore = float(row["zscore_20"])

    # En risk-off favorecemos calidad/low-vol y penalizamos momentum extremo.
    if regime == Regime.RISK_ON:
        weights = {
            "momentum": 0.30,
            "trend": 0.25,
            "rsi": 0.10,
            "low_vol": 0.10,
            "quality": 0.15,
            "volume": 0.10,
        }
    elif regime == Regime.RISK_OFF:
        weights = {
            "momentum": 0.10,
            "trend": 0.10,
            "rsi": 0.15,
            "low_vol": 0.30,
            "quality": 0.25,
            "volume": 0.10,
        }
        # mean-reversion suave en pánico
        rsi_factor = float(np.clip((40 - rsi) / 20, -1.0, 1.0))
    else:
        weights = {
            "momentum": 0.22,
            "trend": 0.22,
            "rsi": 0.12,
            "low_vol": 0.16,
            "quality": 0.18,
            "volume": 0.10,
        }

    factors = {
        "momentum": momentum,
        "trend": trend,
        "rsi": rsi_factor,
        "low_vol": low_vol,
        "quality": quality,
        "volume": volume_confirm,
    }

    score = sum(factors[k] * weights[k] for k in weights)
    # Ajuste por sobreextensión
    if abs(zscore) > 2.2:
        score -= np.sign(zscore) * 0.15

    # Escala el retorno esperado al horizonte (más días => más movimiento potencial)
    horizon_scale = max(horizon_days / 5.0, 0.6)
    expected_return = float(np.clip(score * 0.018 * horizon_scale, -0.12, 0.12))
    probability_up = _sigmoid(score * 1.4)
    confidence = float(np.clip(abs(score) / 1.2, 0.15, 0.92))

    reasons: list[str] = []
    risks: list[str] = []

    if momentum > 0.4:
        reasons.append("Momentum a 60 días positivo.")
    elif momentum < -0.4:
        risks.append("Momentum a 60 días negativo.")

    if trend > 0.3:
        reasons.append("Tendencia de corto plazo alcista (SMA20>SMA50).")
    elif trend < -0.3:
        risks.append("Tendencia de corto plazo bajista.")

    if low_vol > 0.3:
        reasons.append("Volatilidad relativa controlada.")
    elif low_vol < -0.3:
        risks.append("Volatilidad alta: tamaño de posición más conservador.")

    if quality > 0.3:
        reasons.append("Calidad/estabilidad de retornos por encima del promedio.")

    if rsi > 70:
        risks.append("RSI elevado: posible sobrecompra.")
    elif rsi < 30:
        reasons.append("RSI bajo: posible sobreventa táctica.")

    if not reasons:
        reasons.append("Señal mixta; score compuesto marginalmente favorable.")

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
