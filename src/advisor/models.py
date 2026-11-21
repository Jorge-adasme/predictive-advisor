from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Action(str, Enum):
    BUY = "buy"
    HOLD = "hold"
    REDUCE = "reduce"
    AVOID = "avoid"


class Regime(str, Enum):
    RISK_ON = "risk_on"
    NEUTRAL = "neutral"
    RISK_OFF = "risk_off"


class SymbolInfo(BaseModel):
    ticker: str
    name: str
    sector: str = "Unknown"


class MarketSnapshot(BaseModel):
    as_of: datetime
    benchmark: str
    regime: Regime
    regime_score: float
    benchmark_return_20d: float
    benchmark_volatility_20d: float
    notes: list[str] = Field(default_factory=list)


class Prediction(BaseModel):
    ticker: str
    name: str
    sector: str
    as_of: datetime
    horizon_days: int
    last_price: float
    expected_return: float
    probability_up: float
    confidence: float
    score: float
    factors: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class TradePlan(BaseModel):
    ticker: str
    action: Action
    entry_price: float
    stop_price: float
    target_price: float
    position_pct: float
    risk_reward: float
    edge_net_pct: float
    invalidation: str
    horizon_days: int
    stop_pct: float = 0.0  # margen de pérdida inicial (entry→stop)
    risk_r: float = 0.0  # $ de riesgo por acción (entry-stop)


class Recommendation(BaseModel):
    prediction: Prediction
    plan: TradePlan
    market: MarketSnapshot
    rank: int
    disclaimer: str = (
        "Herramienta de apoyo a la decisión. No garantiza rentabilidad. "
        "Evalúa costos, liquidez y tu perfil de riesgo antes de operar."
    )


class PaperFill(BaseModel):
    ticker: str
    side: str
    qty: float
    price: float
    ts: datetime
    note: str = ""


class JournalEntry(BaseModel):
    ts: datetime
    ticker: str
    decision: str
    recommendation: dict[str, Any]
    outcome_note: str = ""
