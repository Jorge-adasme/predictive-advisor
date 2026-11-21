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
