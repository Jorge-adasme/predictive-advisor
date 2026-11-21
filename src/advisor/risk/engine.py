from __future__ import annotations

from advisor.config import Settings
from advisor.models import Action, MarketSnapshot, Prediction, Regime, TradePlan
from advisor.risk.trailing import stop_loss_pct


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
    meta = float(prediction.factors.get("meta_label_prob", 0.0))
    ic = float(prediction.factors.get("ic_spearman", 0.0))
    ir_proxy = float(prediction.factors.get("ir_proxy", 0.0))

    # Filtros duros de certeza (capa cuantitativa)
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
    if meta > 0 and meta < 0.50:
        return _avoid_plan(prediction, edge_net, "Meta-label rechaza la operación.")
    if ic < -0.02 and calib_q >= 0.2:
        return _avoid_plan(prediction, edge_net, "IC histórico negativo para este signal.")
    if ir_proxy < 0.15 and gross > 0:
        return _avoid_plan(prediction, edge_net, "IR proxy insuficiente (retorno/riesgo).")
    if cs < -0.6:
        return _avoid_plan(
            prediction,
            edge_net,
            "Debilitado en ranking cross-sectional del universo.",
        )

    entry = prediction.last_price

    # Stops por ATR del activo (floor = min_stop_pct, tipicamente 1.5%)
    atr_stop = max(atr_pct * settings.atr_stop_mult, settings.min_stop_pct)
    bench_daily = max(market.benchmark_volatility_20d / (252 ** 0.5), 0.008)
    stop_distance = max(
        entry * atr_stop,
        entry * bench_daily * 2.0,
        entry * settings.min_stop_pct,
    )
    stop = entry - stop_distance
    initial_stop_pct = stop_loss_pct(entry, stop)

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

    # Confianza + meta-label + ranking + IR
    raw_pct *= 0.55 + 0.20 * prediction.confidence + 0.15 * max(meta, 0) + 0.10 * max(cs, 0)
    if atr_pct > 0.045:
        raw_pct *= 0.75
    if ir_proxy > 0.8:
        raw_pct *= 1.08
    position_pct = float(min(settings.max_position_pct, max(0.01, raw_pct)))

    news_f = float(prediction.factors.get("news_factor", 0.0))
    news_u = float(prediction.factors.get("news_urgency", 0.0) or market.news_urgency)

    # Shock de noticias negativo: no abrir riesgo nuevo
    if news_f <= -0.55 and news_u >= 0.45:
        return _avoid_plan(
            prediction,
            edge_net,
            "Noticias adversas de alto impacto: se evita abrir riesgo.",
        )
    if market.news_sentiment <= -0.55 and market.news_urgency >= 0.55:
        return _avoid_plan(
            prediction,
            edge_net,
            "Clima de noticias global hostil: capital en defensiva.",
        )

    # Umbral BUY: un poco más permisivo en risk_on prolongado (menos cash drag)
    min_score = 0.28 if market.regime == Regime.RISK_ON else 0.32
    min_prob = 0.54 if market.regime == Regime.RISK_ON else 0.55
    min_meta = 0.52 if market.regime == Regime.RISK_ON else 0.55
    if news_f >= 0.4:
        min_score -= 0.03
    if news_f <= -0.35:
        min_score += 0.05
        min_prob += 0.02
    buy = (
        prediction.score >= min_score
        and prediction.probability_up >= min_prob
        and edge_net >= settings.min_edge_net_pct
        and (meta <= 0 or meta >= min_meta)
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
            f"Stop inicial {stop:.2f} (−{initial_stop_pct:.1%}). "
            f"Break-even a +{settings.breakeven_at_r:.0f}R; "
            f"trail lock +1R a +{settings.trail_at_r:.0f}R. "
            f"Kill-switch diario −{settings.max_daily_loss_pct:.0%}."
        ),
        horizon_days=prediction.horizon_days,
        stop_pct=round(initial_stop_pct, 5),
        risk_r=round(stop_distance, 4),
    )


def _avoid_plan(prediction: Prediction, edge_net: float, reason: str) -> TradePlan:
    entry = prediction.last_price
    stop = entry * 0.98
    return TradePlan(
        ticker=prediction.ticker,
        action=Action.AVOID,
        entry_price=round(entry, 2),
        stop_price=round(stop, 2),
        target_price=round(entry * 1.02, 2),
        position_pct=0.0,
        risk_reward=0.0,
        edge_net_pct=round(edge_net, 5),
        invalidation=reason,
        horizon_days=prediction.horizon_days,
        stop_pct=round(stop_loss_pct(entry, stop), 5),
        risk_r=round(entry - stop, 4),
    )
