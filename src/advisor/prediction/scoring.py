from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from advisor.analysis.features import latest_feature_row
from advisor.models import Prediction, Regime, SymbolInfo
from advisor.prediction.calibration import calibrate_from_history
from advisor.prediction.ensemble import ensemble_sleeves


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

    mom_12_1 = float(np.clip(row.get("mom_12_1", row["momentum"]) / 0.25, -1.5, 1.5))
    mom_vol_scaled = float(np.clip(row.get("mom_vol_scaled", 0.0) / 1.2, -1.5, 1.5))
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
    def _f(key: str, default: float) -> float:
        val = row.get(key, default)
        return float(val) if pd.notna(val) else float(default)

    atr_pct = _f("atr_pct", 0.02)
    macd = float(np.clip(_f("macd_hist", 0.0) / 0.01, -1.5, 1.5))
    dist_52w = _f("dist_52w_high", -0.1)
    skew = _f("ret_skew_60", 0.0)
    amihud = _f("amihud", 0.0)
    bb = _f("bb_pctb", 0.5)

    rs_20 = float(row["rs_20"]) if "rs_20" in row and pd.notna(row["rs_20"]) else 0.0
    rs_factor = float(np.clip(rs_20 / 0.08, -1.5, 1.5))
    residual = (
        float(row["residual_mom_20"])
        if "residual_mom_20" in row and pd.notna(row["residual_mom_20"])
        else 0.0
    )
    residual_factor = float(np.clip(residual / 0.06, -1.5, 1.5))

    if regime == Regime.RISK_OFF:
        rsi_factor = float(np.clip((40 - rsi) / 20, -1.0, 1.0))

    score, sleeve_w, sleeves = ensemble_sleeves(
        regime=regime,
        mom_12_1=mom_12_1,
        mom_vol_scaled=mom_vol_scaled,
        trend=trend,
        rs=rs_factor,
        residual=residual_factor,
        reversal=reversal,
        quality=quality,
        low_vol=low_vol,
        trend_quality=trend_quality,
        macd=macd,
        dist_52w=dist_52w,
        skew=skew,
    )

    # Penalizaciones estructurales (anti-overfit / anti-chase)
    if abs(zscore) > 2.0:
        score -= np.sign(zscore) * 0.16
    if adx < 16:
        score *= 0.82
    if atr_pct > 0.05:
        score -= 0.10
    if amihud > 0:  # relative later in cross-section; local soft penalty if extreme jumps
        score -= float(np.clip(np.log1p(amihud * 1e6) / 20, 0, 0.12))
    if bb > 0.95 and score > 0:
        score -= 0.08  # sobrecompra bandas
    if float(row.get("above_200", 0.0)) < 1 and regime == Regime.RISK_ON:
        score -= 0.06

    calib = calibrate_from_history(
        history=history,
        horizon_days=horizon_days,
        benchmark_df=benchmark_history,
    )
    empiric_er = calib["empirical_expected_return"]
    empiric_hit = calib["empirical_hit_rate"]
    calib_q = calib["calibration_quality"]
    ic = calib.get("ic_spearman", np.nan)
    meta = calib.get("meta_label_prob", np.nan)
    er_shrunk = calib.get("er_shrunk", np.nan)

    horizon_scale = max(horizon_days / 10.0, 0.7)
    # Vol-target del alpha heurístico: score / vol
    vol_target = float(np.clip(0.16 / max(vol, 0.08), 0.5, 1.8))
    heuristic_er = float(np.clip(score * 0.014 * horizon_scale * vol_target, -0.12, 0.12))

    if np.isfinite(er_shrunk):
        expected_return = float(
            np.clip((1 - calib_q) * heuristic_er + calib_q * er_shrunk, -0.12, 0.12)
        )
    elif np.isfinite(empiric_er):
        expected_return = float(
            np.clip((1 - calib_q) * heuristic_er + calib_q * empiric_er, -0.12, 0.12)
        )
    else:
        expected_return = heuristic_er

    base_prob = _sigmoid(score * 1.2)
    if np.isfinite(meta):
        probability_up = float(np.clip(0.45 * base_prob + 0.55 * meta, 0.05, 0.95))
    elif np.isfinite(empiric_hit):
        probability_up = float(
            np.clip((1 - calib_q) * base_prob + calib_q * empiric_hit, 0.05, 0.95)
        )
    else:
        probability_up = base_prob

    ic_term = max(ic, 0.0) if np.isfinite(ic) else 0.0
    confidence = float(
        np.clip(
            0.25 * abs(score) / 1.1
            + 0.35 * calib_q
            + 0.20 * max(trend_quality, 0)
            + 0.20 * ic_term,
            0.10,
            0.94,
        )
    )

    # Information ratio proxy (E[r] / vol)
    ir_proxy = float(expected_return / max(vol / np.sqrt(252 / max(horizon_days, 1)), 1e-6))

    factors = {
        "momentum": momentum,
        "momentum_20": momentum_20,
        "mom_12_1": mom_12_1,
        "mom_vol_scaled": mom_vol_scaled,
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
        "macd": macd,
        "dist_52w_high": dist_52w,
        "ret_skew_60": skew,
        "ir_proxy": ir_proxy,
        "vol_target": vol_target,
        "empirical_expected_return": float(empiric_er) if np.isfinite(empiric_er) else 0.0,
        "empirical_hit_rate": float(empiric_hit) if np.isfinite(empiric_hit) else 0.0,
        "calibration_quality": float(calib_q),
        "sample_size": float(calib["sample_size"]),
        "ic_spearman": float(ic) if np.isfinite(ic) else 0.0,
        "meta_label_prob": float(meta) if np.isfinite(meta) else 0.0,
        "er_shrunk": float(er_shrunk) if np.isfinite(er_shrunk) else 0.0,
        **{f"w_{k}": float(v) for k, v in sleeve_w.items()},
        **sleeves,
    }

    reasons: list[str] = []
    risks: list[str] = []

    if sleeves["sleeve_alpha"] > 0.35:
        reasons.append("Sleeve alpha idiosincrático dominante.")
    if sleeves["sleeve_trend"] > 0.35:
        reasons.append("Sleeve trend/momentum alineado.")
    if sleeves["sleeve_defensive"] > 0.35 and regime == Regime.RISK_OFF:
        reasons.append("Sleeve defensivo activo en risk-off.")

    if np.isfinite(ic) and ic >= 0.05:
        reasons.append(f"IC histórico del signal positivo ({ic:.2f}).")
    elif np.isfinite(ic) and ic < 0:
        risks.append("IC histórico débil/negativo: menos predictibilidad.")

    if np.isfinite(meta) and meta >= 0.58:
        reasons.append(f"Meta-label favorable (P≈{meta:.0%}).")
    elif np.isfinite(meta) and meta < 0.48:
        risks.append("Meta-label bajo: mejor no forzar la operación.")

    if rs_factor > 0.4:
        reasons.append("Relative strength positivo vs benchmark.")
    elif rs_factor < -0.4:
        risks.append("Relative strength negativo vs benchmark.")

    if trend_quality < 0:
        risks.append("Mercado choppy (ADX bajo).")
    if low_vol < -0.3:
        risks.append("Volatilidad alta: sizing defensivo.")
    if dist_52w > -0.03 and score > 0:
        risks.append("Cerca de máximos 52w: riesgo de exhaustión.")
    if skew < -0.8:
        risks.append("Skew negativo: cola de crash elevada.")

    if not reasons:
        reasons.append("Señal mixta; edge depende de calibración/ensemble.")

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
