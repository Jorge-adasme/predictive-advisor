from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TrailUpdate:
    stop: float
    event: str | None  # None | breakeven | trail_1R | trail_atr


def risk_unit(entry: float, initial_stop: float) -> float:
    return max(float(entry) - float(initial_stop), 1e-9)


def ratchet_stop(
    *,
    entry: float,
    current_stop: float,
    mark_price: float,
    initial_stop: float,
    breakeven_at_r: float = 1.0,
    trail_at_r: float = 2.0,
    cost_buffer_pct: float = 0.001,
    atr: float | None = None,
    atr_mult: float = 2.0,
) -> TrailUpdate:
    """Sube el stop (nunca lo baja): break-even a +1R, lock +1R a +2R.

    R = entry - initial_stop (riesgo inicial por acción).
    """
    r = risk_unit(entry, initial_stop)
    progress_r = (float(mark_price) - float(entry)) / r
    new_stop = float(current_stop)
    event: str | None = None

    if progress_r >= trail_at_r:
        candidate = float(entry) + r * 1.0  # asegura al menos +1R
        if candidate > new_stop + 1e-9:
            new_stop = candidate
            event = "trail_1R"
    elif progress_r >= breakeven_at_r:
        candidate = float(entry) * (1.0 + float(cost_buffer_pct))
        if candidate > new_stop + 1e-9:
            new_stop = candidate
            event = "breakeven"

    # Trailing ATR opcional (solo si ya hay BE o mejor)
    if atr is not None and atr > 0 and new_stop >= entry * (1.0 + cost_buffer_pct) - 1e-9:
        atr_stop = float(mark_price) - float(atr_mult) * float(atr)
        if atr_stop > new_stop + 1e-9:
            new_stop = atr_stop
            event = "trail_atr"

    # Nunca bajar el stop; nunca poner stop por encima del mark (evitar fill inmediato)
    new_stop = max(new_stop, float(current_stop))
    if new_stop >= float(mark_price):
        new_stop = min(new_stop, float(mark_price) * 0.999)
        new_stop = max(new_stop, float(current_stop))

    if abs(new_stop - float(current_stop)) < 1e-9:
        event = None
    return TrailUpdate(stop=float(new_stop), event=event)


def stop_loss_pct(entry: float, stop: float) -> float:
    """Margen de pérdida aceptado desde la entrada hasta el stop."""
    if entry <= 0:
        return 0.0
    return max((float(entry) - float(stop)) / float(entry), 0.0)


def progress_in_r(entry: float, mark_price: float, initial_stop: float) -> float:
    r = risk_unit(entry, initial_stop)
    return (float(mark_price) - float(entry)) / r


def should_partial_take(
    *,
    entry: float,
    mark_price: float,
    initial_stop: float,
    already_taken: bool,
    partial_at_r: float = 1.5,
) -> bool:
    if already_taken:
        return False
    return progress_in_r(entry, mark_price, initial_stop) >= partial_at_r


def should_time_stop(
    *,
    entry: float,
    mark_price: float,
    initial_stop: float,
    days_held: int,
    horizon_days: int,
    time_stop_frac: float = 0.7,
    min_r: float = 0.3,
) -> bool:
    if horizon_days <= 0:
        return False
    threshold = max(int(round(horizon_days * time_stop_frac)), 1)
    if days_held < threshold:
        return False
    return progress_in_r(entry, mark_price, initial_stop) < min_r
