from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from advisor.advisory.pipeline import AdvisoryPipeline
from advisor.config import get_settings
from advisor.models import Recommendation
from advisor.portfolio.journal import JournalStore

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Predictive Investment Advisor",
    description="Analizador predictivo de inversiones (Chile / BTG-ready)",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


class DecisionRequest(BaseModel):
    ticker: str
    decision: str = Field(pattern="^(accepted|rejected|deferred)$")
    note: str = ""


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "predictive-advisor"}


@app.get("/dashboard")
def dashboard(mode: str = Query(default="alpaca")) -> dict:
    """Resumen amigable para la UI: portafolio + movimientos."""
    from advisor.execution.autopilot import build_broker
    from advisor.execution.paper_broker import PaperBroker

    settings = get_settings()
    used_mode = mode
    warning = None
    try:
        broker = build_broker(settings, mode)
        portfolio = broker.status()
    except Exception as exc:
        used_mode = "paper"
        warning = f"Alpaca no disponible ({exc}). Mostrando paper local."
        portfolio = PaperBroker(settings).status()

    movements: list[dict] = []
    for o in portfolio.get("orders", [])[-20:]:
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
    for c in portfolio.get("closed", [])[-20:]:
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
    movements = sorted(movements, key=lambda m: str(m.get("ts") or ""), reverse=True)[:30]

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
            }
        )
    positions = sorted(positions, key=lambda p: p["pnl"], reverse=True)

    daily = float(portfolio.get("daily_pnl") or 0)
    total = float(portfolio.get("total_pnl") or 0)
    return {
        "mode": used_mode,
        "warning": warning,
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
            "updated_at": portfolio.get("updated_at"),
        },
        "positions": positions,
        "movements": movements,
        "currency": settings.base_currency,
    }


@app.get("/analyze")
def analyze(top_n: int = Query(default=8, ge=1, le=30)) -> dict:
    result = AdvisoryPipeline().analyze(top_n=top_n)
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@app.get("/btg/status")
def btg_status() -> dict:
    return AdvisoryPipeline().btg.status().__dict__


@app.post("/decisions")
def decisions(payload: DecisionRequest) -> dict:
    settings = get_settings()
    pipeline = AdvisoryPipeline(settings)
    result = pipeline.analyze(top_n=max(settings.top_n, 15))
    match = next(
        (
            Recommendation.model_validate(item)
            for item in result.get("recommendations", [])
            if item["prediction"]["ticker"].upper() == payload.ticker.upper()
        ),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail=f"Sin recomendación para {payload.ticker}")

    store = JournalStore(settings.data_dir / "journal.json")
    entry = store.record_decision(match, decision=payload.decision, outcome_note=payload.note)
    draft = pipeline.draft_order(match) if payload.decision == "accepted" else None
    return {"journal": entry.model_dump(mode="json"), "btg_draft": draft}


@app.get("/journal")
def journal(limit: int = Query(default=50, ge=1, le=500)) -> dict:
    settings = get_settings()
    store = JournalStore(settings.data_dir / "journal.json")
    return {"entries": store.list_entries(limit=limit)}


@app.post("/autopilot/run")
def autopilot_run(
    top_n: int = Query(default=8, ge=1, le=30),
    mode: str = Query(default="alpaca"),
) -> dict:
    """Ejecuta un ciclo de inversión automática (alpaca|paper)."""
    from advisor.execution.autopilot import Autopilot

    result = Autopilot(mode=mode).run_once(top_n=top_n)
    return {
        "ts": result.ts,
        "mode": result.mode,
        "message": result.message,
        "actions": result.actions,
        "portfolio": result.portfolio,
        "market": result.market,
        "disclaimer": (
            "Autopilot busca expectancy neta positiva con stops/kill-switch. "
            "No garantiza ganancias. Usa paper antes de live."
        ),
    }


@app.get("/portfolio")
def portfolio(mode: str = Query(default="alpaca")) -> dict:
    from advisor.execution.autopilot import build_broker

    return build_broker(get_settings(), mode).status()


@app.post("/portfolio/halt")
def portfolio_halt(
    reason: str = Query(default="manual_stop"),
    mode: str = Query(default="alpaca"),
) -> dict:
    from advisor.execution.autopilot import build_broker

    return build_broker(get_settings(), mode).halt(reason)


@app.post("/portfolio/resume")
def portfolio_resume(mode: str = Query(default="alpaca")) -> dict:
    from advisor.execution.autopilot import build_broker

    return build_broker(get_settings(), mode).resume()


@app.get("/alpaca/status")
def alpaca_status() -> dict:
    settings = get_settings()
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        raise HTTPException(
            status_code=400,
            detail="Faltan ADVISOR_ALPACA_API_KEY / ADVISOR_ALPACA_SECRET_KEY",
        )
    from advisor.execution.alpaca_broker import AlpacaBroker

    return AlpacaBroker(settings).status()


@app.get("/earnings")
def earnings_calendar(refresh: bool = Query(default=False)) -> dict:
    from advisor.events.earnings import EarningsCalendar

    settings = get_settings()
    symbols = AdvisoryPipeline(settings).market_data.load_universe()
    try:
        snap = EarningsCalendar(settings).snapshot(
            [s.ticker for s in symbols], use_cache=not refresh
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "blackout_before": settings.earnings_blackout_before,
        "blackout_after": settings.earnings_blackout_after,
        "tickers": {k: v.to_dict() for k, v in snap.items()},
    }


@app.get("/news")
def news_pulse(refresh: bool = Query(default=False)) -> dict:
    """Noticias mundiales + sentimiento para régimen y scoring."""
    from advisor.news.engine import NewsEngine

    settings = get_settings()
    symbols = AdvisoryPipeline(settings).market_data.load_universe()
    try:
        pulse = NewsEngine(settings).pulse(symbols, use_cache=not refresh)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return pulse.to_dict()


@app.get("/backtest/walk-forward")
def backtest_walk_forward(
    lookback: int = Query(default=756, ge=250, le=2000),
    train: int = Query(default=252, ge=120, le=800),
    step: int = Query(default=10, ge=5, le=40),
    horizon: int = Query(default=10, ge=5, le=40),
    max_positions: int = Query(default=3, ge=1, le=8),
) -> dict:
    """Walk-forward out-of-sample (puede tardar ~1–3 min)."""
    from advisor.backtest.walk_forward import WalkForwardBacktester

    try:
        result = WalkForwardBacktester(get_settings()).run(
            lookback_days=lookback,
            train_bars=train,
            step_days=step,
            horizon_days=horizon,
            max_positions=max_positions,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    payload = result.to_dict()
    # Respuesta API: trades truncados para no saturar
    payload["trades"] = payload.get("trades", [])[-50:]
    return payload


@app.get("/live/btg/status")
def live_btg_status() -> dict:
    from advisor.execution.live_btg import BTGLiveExecutor

    gate = BTGLiveExecutor(get_settings()).gate()
    return {
        "enabled": gate.enabled,
        "reason": gate.reason,
        "next_steps": gate.next_steps,
    }


@app.post("/live/btg/place")
def live_btg_place(ticker: str = Query(...)) -> dict:
    """Intenta orden live; si no hay API oficial, devuelve bloqueo + draft."""
    from advisor.execution.live_btg import BTGLiveExecutor

    settings = get_settings()
    pipeline = AdvisoryPipeline(settings)
    result = pipeline.analyze(top_n=max(settings.top_n, 15))
    match = next(
        (
            item
            for item in result.get("recommendations", [])
            if item["prediction"]["ticker"].upper() == ticker.upper()
        ),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail=f"Sin plan para {ticker}")

    return BTGLiveExecutor(settings).place_order(match["plan"])
