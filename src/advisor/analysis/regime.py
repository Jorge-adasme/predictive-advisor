from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from advisor.analysis.features import compute_features
from advisor.models import MarketSnapshot, Regime


def detect_regime(
    benchmark_df: pd.DataFrame,
    benchmark: str,
    news: dict[str, Any] | None = None,
) -> MarketSnapshot:
    featured = compute_features(benchmark_df)
    featured = featured.dropna(
        subset=["Close", "ret_20d", "volatility_20d", "trend_strength", "sma_200"]
    )
    if featured.empty:
        now = datetime.now(timezone.utc)
        return MarketSnapshot(
            as_of=now,
            benchmark=benchmark,
            regime=Regime.NEUTRAL,
            regime_score=0.0,
            benchmark_return_20d=0.0,
            benchmark_volatility_20d=0.0,
            notes=["Datos de benchmark insuficientes; régimen neutral por defecto."],
        )

    last = featured.iloc[-1]
    score = 0.0
    notes: list[str] = []

    ret_20 = float(last["ret_20d"])
    vol_20 = float(last["volatility_20d"])
    trend = float(last["trend_strength"])
    above_200 = float(last["Close"] > last["sma_200"]) if not np.isnan(last["sma_200"]) else 0.5

    score += np.clip(ret_20 / 0.05, -1.5, 1.5)
    score += np.clip(trend / 0.03, -1.0, 1.0)
    score += (above_200 - 0.5) * 1.2
    score -= np.clip((vol_20 - 0.18) / 0.12, -0.5, 1.5)

    news_sentiment = 0.0
    news_urgency = 0.0
    news_bias = 0.0
    headlines: list[dict[str, Any]] = []
    if news:
        news_sentiment = float(news.get("market_sentiment") or 0.0)
        news_urgency = float(news.get("market_urgency") or 0.0)
        news_bias = float(news.get("regime_bias") or 0.0)
        headlines = list(news.get("headlines") or [])[:8]
        score += news_bias
        for n in news.get("notes") or []:
            notes.append(str(n))

    if ret_20 > 0.02:
        notes.append("Benchmark con momentum positivo a 20 días.")
    elif ret_20 < -0.02:
        notes.append("Benchmark con momentum negativo a 20 días.")

    if vol_20 > 0.25:
        notes.append("Volatilidad elevada: reducir agresividad.")
    if above_200 >= 1:
        notes.append("Precio sobre SMA200: sesgo constructivo.")
    else:
        notes.append("Precio bajo SMA200: sesgo defensivo.")

    if benchmark == "CHILE_PROXY":
        notes.append("Benchmark sintético equal-weight de acciones líquidas BCS.")

    if abs(news_bias) >= 0.25:
        notes.append(f"Ajuste de régimen por noticias: {news_bias:+.2f}.")

    if score >= 0.75:
        regime = Regime.RISK_ON
    elif score <= -0.75:
        regime = Regime.RISK_OFF
    else:
        regime = Regime.NEUTRAL

    # Shock mediático extremo puede forzar risk_off aunque el precio aún no reaccione
    if news_sentiment <= -0.55 and news_urgency >= 0.5:
        regime = Regime.RISK_OFF
        notes.append("Shock de noticias negativo: régimen forzado a risk_off.")

    as_of = featured.index[-1].to_pydatetime()
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    return MarketSnapshot(
        as_of=as_of,
        benchmark=benchmark,
        regime=regime,
        regime_score=float(score),
        benchmark_return_20d=ret_20,
        benchmark_volatility_20d=vol_20,
        notes=notes,
        news_sentiment=news_sentiment,
        news_urgency=news_urgency,
        news_regime_bias=news_bias,
        news_headlines=headlines,
    )
