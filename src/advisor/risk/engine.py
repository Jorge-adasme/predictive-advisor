from __future__ import annotations

from advisor.config import Settings
from advisor.models import Action, MarketSnapshot, Prediction, Regime, TradePlan


def build_trade_plan(
    prediction: Prediction,
    market: MarketSnapshot,
    settings: Settings,
) -> TradePlan | None:
    """Convierte predicción en plan operable solo si hay edge neto."""
    gross = prediction.expected_return
    edge_net = gross - settings.round_trip_cost_pct

    empiric_hit = float(prediction.factors.get("empirical_hit_rate", 0.0))
    calib_q = float(prediction.factors.get("calibration_quality", 0.0))
    atr_pct = float(prediction.factors.get("atr_pct", 0.02) or 0.02)
    cs = float(prediction.factors.get("cross_sectional_z", 0.0))

    # Filtros duros de certeza
    if prediction.probability_up < 0.54 and gross > 0:
        return None
    if edge_net < settings.min_edge_net_pct:
        return _avoid_plan(prediction, edge_net, "Edge neto insuficiente tras costos.")
    if market.regime == Regime.RISK_OFF and prediction.score < 0.55:
        return _avoid_plan(
            prediction,
            edge_net,
            "Régimen risk-off: se exigen señales más fuertes.",
        )
    if prediction.score <= 0.18:
        return _avoid_plan(prediction, edge_net, "Score demasiado débil para abrir riesgo.")
    if calib_q >= 0.25 and empiric_hit > 0 and empiric_hit < 0.48:
        return _avoid_plan(
            prediction,
            edge_net,
            "Hit-rate empírico bajo en señales similares.",
        )
    if cs < -0.6:
        return _avoid_plan(
            prediction,
            edge_net,
            "Debilitado en ranking cross-sectional del universo.",
        )

    entry = prediction.last_price

    # Stops por ATR del activo (mejor que vol genérica del benchmark)
    atr_stop = max(atr_pct * 2.0, 0.015)
    bench_daily = max(market.benchmark_volatility_20d / (252 ** 0.5), 0.008)
    stop_distance = max(entry * atr_stop, entry * bench_daily * 2.0, entry * 0.015)
    stop = entry - stop_distance

    # Target: al menos 1.8R o el E[r] neto proyectado
    target_by_edge = entry * max(gross, settings.min_edge_net_pct * 2.5)
    target_by_rr = stop_distance * 1.8
    target_distance = max(target_by_edge, target_by_rr)
    target = entry + target_distance
    rr = target_distance / stop_distance if stop_distance else 0.0

    if rr < 1.4:
        return _avoid_plan(prediction, edge_net, "Reward/risk insuficiente (<1.4).")

    risk_budget = settings.risk_per_trade
    raw_pct = risk_budget / (stop_distance / entry)
    if market.regime == Regime.RISK_OFF:
        raw_pct *= 0.55
    elif market.regime == Regime.RISK_ON:
        raw_pct *= 1.0

    # Confianza + calidad de calibración + ranking
    raw_pct *= 0.65 + 0.25 * prediction.confidence + 0.10 * max(cs, 0)
    if atr_pct > 0.045:
        raw_pct *= 0.75
    position_pct = float(min(settings.max_position_pct, max(0.01, raw_pct)))

    # Umbral BUY más estricto: score + probabilidad + edge
    buy = (
        prediction.score >= 0.32
        and prediction.probability_up >= 0.55
        and edge_net >= settings.min_edge_net_pct
    )
    action = Action.BUY if buy else Action.HOLD

    return TradePlan(
        ticker=prediction.ticker,
        action=action,
        entry_price=round(entry, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        position_pct=round(position_pct, 4),
        risk_reward=round(rr, 2),
        edge_net_pct=round(edge_net, 5),
        invalidation=(
            f"Cierre bajo {stop:.2f}, pérdida de RS vs benchmark, "
            f"o régimen risk_off."
        ),
        horizon_days=prediction.horizon_days,
    )


def _avoid_plan(prediction: Prediction, edge_net: float, reason: str) -> TradePlan:
    entry = prediction.last_price
    return TradePlan(
        ticker=prediction.ticker,
        action=Action.AVOID,
        entry_price=round(entry, 2),
        stop_price=round(entry * 0.98, 2),
        target_price=round(entry * 1.02, 2),
        position_pct=0.0,
        risk_reward=0.0,
        edge_net_pct=round(edge_net, 5),
        invalidation=reason,
        horizon_days=prediction.horizon_days,
    )
