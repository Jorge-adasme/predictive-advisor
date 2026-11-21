from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from advisor.config import Settings, get_settings
from advisor.portfolio.audit import PerformanceStats


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_broker(settings: Settings, mode: str):
    from advisor.execution.autopilot import build_broker
    from advisor.execution.paper_broker import PaperBroker

    try:
        return build_broker(settings, mode), mode, None
    except Exception as exc:
        return PaperBroker(settings), "paper", f"Alpaca no disponible ({exc}). Paper local."


def _mark_open_prices(broker: Any, portfolio: dict[str, Any]) -> dict[str, float]:
    """Actualiza last_price de posiciones abiertas (paper) con Yahoo rápido."""
    positions = portfolio.get("positions") or {}
    tickers = list(positions.keys())
    if not tickers:
        return {}
    if not hasattr(broker, "mark_price"):
        return {t: float(positions[t].get("last_price") or 0) for t in tickers}

    prices: dict[str, float] = {}
    try:
        import yfinance as yf

        for ticker in tickers:
            try:
                info = yf.Ticker(ticker).fast_info
                px = getattr(info, "last_price", None) or getattr(info, "lastPrice", None)
                if px is None and isinstance(info, dict):
                    px = info.get("last_price") or info.get("lastPrice")
                if px is not None and float(px) > 0:
                    prices[ticker] = float(px)
                    broker.mark_price(ticker, float(px))
            except Exception:
                continue
    except Exception:
        return {}
    return prices


def live_snapshot(mode: str = "alpaca", refresh_marks: bool = True) -> dict[str, Any]:
    """Snapshot liviano para UI en tiempo casi real (sin analyze/news pesado)."""
    settings = get_settings()
    broker, used_mode, warning = _build_broker(settings, mode)
    portfolio = broker.status()
    marks = _mark_open_prices(broker, portfolio) if refresh_marks else {}
    if marks:
        portfolio = broker.status()

    positions = []
    for ticker, pos in (portfolio.get("positions") or {}).items():
        entry = float(pos.get("entry_price") or 0)
        last = float(pos.get("last_price") or entry)
        qty = float(pos.get("qty") or 0)
        pnl = float(pos.get("unrealized_pl") or ((last - entry) * qty))
        pnl_pct = ((last / entry) - 1.0) if entry else 0.0
        positions.append(
            {
                "ticker": ticker,
                "qty": qty,
                "entry_price": entry,
                "last_price": last,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "stop": pos.get("stop"),
                "target": pos.get("target"),
                "sector": pos.get("sector") or "Unknown",
            }
        )
    positions = sorted(positions, key=lambda p: p["pnl"], reverse=True)

    movements: list[dict] = []
    for o in portfolio.get("orders", [])[-12:]:
        movements.append(
            {
                "type": "order",
                "ts": o.get("ts"),
                "side": o.get("side"),
                "ticker": o.get("ticker") or o.get("symbol"),
                "qty": o.get("qty"),
                "price": o.get("price"),
                "pnl": o.get("pnl"),
                "status": o.get("status"),
                "reason": o.get("reason"),
            }
        )
    for c in portfolio.get("closed", [])[-12:]:
        movements.append(
            {
                "type": "closed",
                "ts": c.get("ts"),
                "side": "sell",
                "ticker": c.get("ticker"),
                "qty": c.get("qty"),
                "price": c.get("exit_price"),
                "pnl": c.get("pnl"),
                "status": "closed",
                "reason": c.get("reason"),
            }
        )
    movements = sorted(movements, key=lambda m: str(m.get("ts") or ""), reverse=True)[:20]

    stats = PerformanceStats(settings).from_portfolio(portfolio)
    daily = float(portfolio.get("daily_pnl") or 0)
    total = float(portfolio.get("total_pnl") or 0)

    return {
        "mode": used_mode,
        "warning": warning,
        "live": True,
        "server_ts": _now(),
        "poll_sec": int(getattr(settings, "live_poll_sec", 8) or 8),
        "analyze_sec": int(getattr(settings, "live_analyze_sec", 120) or 120),
        "headline": {
            "equity": float(portfolio.get("equity") or 0),
            "cash": float(portfolio.get("cash") or 0),
            "daily_pnl": daily,
            "total_pnl": total,
            "daily_positive": daily >= 0,
            "total_positive": total >= 0,
            "open_positions": int(portfolio.get("open_positions") or len(positions)),
            "halted": bool(portfolio.get("halted")),
            "halt_reason": portfolio.get("halt_reason") or "",
            "updated_at": portfolio.get("updated_at") or _now(),
            "exposure_pct": stats.get("exposure_pct"),
            "daily_loss_budget_left": stats.get("daily_loss_budget_left"),
        },
        "positions": positions,
        "movements": movements,
        "performance": stats,
        "marks": marks,
        "currency": settings.base_currency,
    }
