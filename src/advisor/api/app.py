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
