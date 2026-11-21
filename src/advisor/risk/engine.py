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

    # Filtros duros
    if prediction.probability_up < 0.53 and gross > 0:
        return None
    if edge_net < settings.min_edge_net_pct:
        return _avoid_plan(prediction, edge_net, "Edge neto insuficiente tras costos.")

    if market.regime == Regime.RISK_OFF and prediction.score < 0.6:
        return _avoid_plan(
            prediction,
            edge_net,
            "Régimen risk-off: se exigen señales más fuertes.",
        )

    if prediction.score <= 0.15:
        return _avoid_plan(prediction, edge_net, "Score demasiado débil para abrir riesgo.")

    entry = prediction.last_price
    # Stop ~ 1.2x vol diaria implícita o floor
    daily_vol = max(market.benchmark_volatility_20d / (252 ** 0.5), 0.008)
    stop_distance = max(entry * daily_vol * 2.2, entry * 0.02)
    stop = entry - stop_distance
    target_distance = max(entry * max(gross, settings.min_edge_net_pct * 2), stop_distance * 1.6)
    target = entry + target_distance
    rr = target_distance / stop_distance if stop_distance else 0.0

    # Position sizing por riesgo
    risk_budget = settings.risk_per_trade
    raw_pct = risk_budget / (stop_distance / entry)
    if market.regime == Regime.RISK_OFF:
        raw_pct *= 0.6
    elif market.regime == Regime.RISK_ON:
        raw_pct *= 1.0

    # Ajuste por confianza
    raw_pct *= 0.7 + 0.3 * prediction.confidence
    position_pct = float(min(settings.max_position_pct, max(0.01, raw_pct)))

    action = Action.BUY if prediction.score >= 0.35 else Action.HOLD

    return TradePlan(
        ticker=prediction.ticker,
        action=action,
        entry_price=round(entry, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        position_pct=round(position_pct, 4),
        risk_reward=round(rr, 2),
        edge_net_pct=round(edge_net, 5),
        invalidation=f"Cierre diario bajo {stop:.2f} o deterioro de régimen a risk_off.",
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
