from __future__ import annotations

from advisor.config import Settings
from advisor.models import Action, MarketSnapshot, Prediction, Regime, TradePlan
from advisor.risk.trailing import stop_loss_pct


def build_trade_plan(
    prediction: Prediction,
    market: MarketSnapshot,
    settings: Settings,
) -> TradePlan | None:
    """Plan operable: captura más oportunidades; hard-avoid solo en riesgos extremos."""
    gross = prediction.expected_return
    edge_net = gross - settings.round_trip_cost_pct

    empiric_hit = float(prediction.factors.get("empirical_hit_rate", 0.0))
    calib_q = float(prediction.factors.get("calibration_quality", 0.0))
    atr_pct = float(prediction.factors.get("atr_pct", 0.02) or 0.02)
    cs = float(prediction.factors.get("cross_sectional_z", 0.0))
    meta = float(prediction.factors.get("meta_label_prob", 0.0))
    ic = float(prediction.factors.get("ic_spearman", 0.0))
    ir_proxy = float(prediction.factors.get("ir_proxy", 0.0))
    news_f = float(prediction.factors.get("news_factor", 0.0))
    news_u = float(prediction.factors.get("news_urgency", 0.0) or market.news_urgency)
    earnings_bo = float(prediction.factors.get("earnings_blackout", 0.0)) >= 1.0

    # --- Hard avoids (proteger capital) ---
    if earnings_bo and settings.earnings_enabled:
        return _avoid_plan(
            prediction,
            edge_net,
            "Blackout de earnings: no abrir riesgo en ventana de resultados.",
        )
    if news_f <= -0.65 and news_u >= 0.55:
        return _avoid_plan(
            prediction,
            edge_net,
            "Noticias adversas de alto impacto: se evita abrir riesgo.",
        )
    if market.news_sentiment <= -0.65 and market.news_urgency >= 0.6:
        return _avoid_plan(
            prediction,
            edge_net,
            "Clima de noticias global hostil: capital en defensiva.",
        )
    # Solo evitar si el edge es claramente negativo (no por umbral alto)
    if edge_net < -settings.min_edge_net_pct:
        return _avoid_plan(
            prediction,
            edge_net,
            "Expectativa neta negativa tras costos: no forzar.",
        )
    if prediction.score <= -0.35 and edge_net <= 0:
        return _avoid_plan(
            prediction,
            edge_net,
            "Score y edge débiles a la vez: mejor evitar.",
        )

    entry = prediction.last_price
    atr_stop = max(atr_pct * settings.atr_stop_mult, settings.min_stop_pct)
    bench_daily = max(market.benchmark_volatility_20d / (252 ** 0.5), 0.008)
    stop_distance = max(
        entry * atr_stop,
        entry * bench_daily * 2.0,
        entry * settings.min_stop_pct,
    )
    stop = entry - stop_distance
    initial_stop_pct = stop_loss_pct(entry, stop)

    target_by_edge = entry * max(abs(gross), settings.min_edge_net_pct * 2.0, 0.01)
    target_by_rr = stop_distance * 1.6
    target_distance = max(target_by_edge, target_by_rr)
    target = entry + target_distance
    rr = target_distance / stop_distance if stop_distance else 0.0

    # Soft penalties → sizing (no matan la idea)
    size_mult = 1.0
    soft_flags: list[str] = []
    if market.regime == Regime.RISK_OFF:
        size_mult *= 0.55
        soft_flags.append("risk_off")
    if prediction.probability_up < 0.52:
        size_mult *= 0.7
        soft_flags.append("prob_baja")
    if meta > 0 and meta < 0.48:
        size_mult *= 0.75
        soft_flags.append("meta_flojo")
    if ic < -0.05 and calib_q >= 0.2:
        size_mult *= 0.8
        soft_flags.append("ic_neg")
    if ir_proxy < 0.1 and gross > 0:
        size_mult *= 0.85
        soft_flags.append("ir_bajo")
    if cs < -0.8:
        size_mult *= 0.8
        soft_flags.append("cs_debil")
    if calib_q >= 0.25 and 0 < empiric_hit < 0.45:
        size_mult *= 0.8
        soft_flags.append("hit_bajo")
    if news_f <= -0.35:
        size_mult *= 0.75
        soft_flags.append("news_neg")
    if atr_pct > 0.045:
        size_mult *= 0.75
    if rr < 1.2:
        size_mult *= 0.85
        soft_flags.append("rr_bajo")

    risk_budget = settings.risk_per_trade
    raw_pct = risk_budget / (stop_distance / entry)
    raw_pct *= 0.50 + 0.20 * prediction.confidence + 0.15 * max(meta, 0) + 0.15 * max(cs, 0)
    raw_pct *= size_mult
    if ir_proxy > 0.8:
        raw_pct *= 1.08
    position_pct = float(min(settings.max_position_pct, max(0.01, raw_pct)))

    # Umbrales BUY más abiertos: capturar más oportunidades con tamaño adaptativo
    min_score = 0.12 if market.regime == Regime.RISK_ON else 0.18
    if market.regime == Regime.RISK_OFF:
        min_score = 0.22
    min_prob = 0.51
    min_edge = settings.min_edge_net_pct * 0.5  # permite edges pequeños

    if news_f >= 0.35:
        min_score -= 0.04
    if soft_flags:
        min_score += 0.02 * min(len(soft_flags), 3)

    strong_buy = (
        prediction.score >= min_score + 0.12
        and prediction.probability_up >= 0.55
        and edge_net >= settings.min_edge_net_pct
        and (meta <= 0 or meta >= 0.52)
    )
    buy = (
        prediction.score >= min_score
        and prediction.probability_up >= min_prob
        and edge_net >= min_edge
        and position_pct > 0
    )

    if strong_buy or buy:
        action = Action.BUY
        if not strong_buy:
            position_pct = float(max(0.01, position_pct * 0.7))  # size menor si es marginal
    elif edge_net >= 0 and prediction.score >= 0.05:
        action = Action.HOLD  # oportunidad a vigilar / semi
        position_pct = float(max(0.01, position_pct * 0.45))
    else:
        return _avoid_plan(
            prediction,
            edge_net,
            "Sin edge/score mínimo: mejor no forzar.",
        )

    note_soft = f" Soft:{','.join(soft_flags)}." if soft_flags else ""
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
            f"trail lock +1R a +{settings.trail_at_r:.0f}R."
            f"{note_soft}"
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
