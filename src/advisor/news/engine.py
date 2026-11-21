from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from advisor.config import Settings, get_settings
from advisor.models import SymbolInfo
from advisor.news.feeds import RawHeadline, fetch_rss_headlines, fetch_yahoo_ticker_news
from advisor.news.sentiment import (
    detect_sectors,
    detect_tickers,
    score_text,
    urgency_score,
)


@dataclass
class NewsPulse:
    as_of: str
    market_sentiment: float
    market_urgency: float
    regime_bias: float
    by_sector: dict[str, float] = field(default_factory=dict)
    by_ticker: dict[str, float] = field(default_factory=dict)
    headlines: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sources_ok: int = 0
    n_headlines: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def factor_for(self, ticker: str, sector: str) -> float:
        t = float(self.by_ticker.get(ticker, 0.0))
        s = float(self.by_sector.get(sector, 0.0))
        m = float(self.market_sentiment)
        # Ticker > sector > market
        return float(max(-1.0, min(1.0, 0.50 * t + 0.30 * s + 0.20 * m)))


class NewsEngine:
    """Pulso de noticias mundiales → sesgo de régimen y factor por activo."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.cache_path = self.settings.data_dir / "news_cache.json"
        self.ttl_sec = int(getattr(self.settings, "news_cache_ttl_sec", 1200))

    def _read_cache(self) -> dict[str, Any] | None:
        if not self.cache_path.exists():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            ts = datetime.fromisoformat(payload["as_of"])
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age <= self.ttl_sec:
                return payload
        except Exception:
            return None
        return None

    def _write_cache(self, pulse: NewsPulse) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(pulse.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def pulse(
        self,
        symbols: list[SymbolInfo] | None = None,
        use_cache: bool = True,
        include_yahoo: bool = True,
    ) -> NewsPulse:
        if use_cache:
            cached = self._read_cache()
            if cached:
                return NewsPulse(**cached)

        symbols = symbols or []
        universe = [s.ticker for s in symbols]
        sector_of = {s.ticker: s.sector for s in symbols}

        headlines = fetch_rss_headlines()
        sources = {h.source for h in headlines}
        if include_yahoo and universe:
            headlines.extend(fetch_yahoo_ticker_news(universe))

        if not headlines:
            empty = NewsPulse(
                as_of=datetime.now(timezone.utc).isoformat(),
                market_sentiment=0.0,
                market_urgency=0.0,
                regime_bias=0.0,
                notes=["Sin noticias disponibles (feeds caídos o sin red)."],
            )
            return empty

        # Recencia: últimas ~36h pesan más
        now = datetime.now(timezone.utc)
        scored: list[tuple[float, float, RawHeadline, float]] = []
        sector_acc: dict[str, list[float]] = {}
        ticker_acc: dict[str, list[float]] = {}

        for h in headlines:
            text = f"{h.title}. {h.summary}"
            sent = score_text(text)
            urg = urgency_score(text)
            age_h = 24.0
            if h.published is not None:
                age_h = max((now - h.published).total_seconds() / 3600.0, 0.0)
            recency = float(max(0.25, 1.0 - age_h / 48.0))
            weight = recency * (1.0 + 0.5 * urg)
            scored.append((sent, weight, h, urg))

            for sec in detect_sectors(text):
                sector_acc.setdefault(sec, []).append(sent * weight)
            for tk in detect_tickers(text, universe=universe or None):
                ticker_acc.setdefault(tk, []).append(sent * weight)
                # propaga al sector del universo
                sec = sector_of.get(tk)
                if sec:
                    sector_acc.setdefault(sec, []).append(sent * weight * 0.5)

        def _avg(xs: list[float]) -> float:
            return float(sum(xs) / len(xs)) if xs else 0.0

        wsum = sum(w for _, w, _, _ in scored) or 1.0
        market_sentiment = float(
            max(-1.0, min(1.0, sum(s * w for s, w, _, _ in scored) / wsum))
        )
        market_urgency = float(
            max(0.0, min(1.0, sum(u * w for _, w, _, u in scored) / wsum))
        )

        # Sesgo de régimen: sentimiento negativo + urgencia alta ⇒ risk_off
        regime_bias = float(
            max(-1.2, min(1.2, market_sentiment * 0.85 - market_urgency * 0.55))
        )

        by_sector = {k: float(max(-1, min(1, _avg(v)))) for k, v in sector_acc.items()}
        by_ticker = {k: float(max(-1, min(1, _avg(v)))) for k, v in ticker_acc.items()}

        # Top headlines por |sentimiento| * weight
        ranked = sorted(scored, key=lambda x: abs(x[0]) * x[1], reverse=True)
        top = []
        for sent, weight, h, urg in ranked[:12]:
            top.append(
                {
                    "title": h.title,
                    "source": h.source,
                    "url": h.url,
                    "sentiment": round(sent, 3),
                    "urgency": round(urg, 3),
                    "published": h.published.isoformat() if h.published else None,
                }
            )

        notes: list[str] = []
        if market_sentiment <= -0.35:
            notes.append(f"Noticias netamente negativas (sent={market_sentiment:.2f}).")
        elif market_sentiment >= 0.35:
            notes.append(f"Noticias netamente positivas (sent={market_sentiment:.2f}).")
        else:
            notes.append(f"Noticias mixtas/neutrales (sent={market_sentiment:.2f}).")
        if market_urgency >= 0.45:
            notes.append("Alta urgencia mediática: sizing más defensivo.")
        if by_sector:
            worst = min(by_sector.items(), key=lambda kv: kv[1])
            best = max(by_sector.items(), key=lambda kv: kv[1])
            notes.append(f"Sector más favorecido por news: {best[0]} ({best[1]:+.2f}).")
            notes.append(f"Sector más presionado por news: {worst[0]} ({worst[1]:+.2f}).")

        pulse = NewsPulse(
            as_of=now.isoformat(),
            market_sentiment=market_sentiment,
            market_urgency=market_urgency,
            regime_bias=regime_bias,
            by_sector=by_sector,
            by_ticker=by_ticker,
            headlines=top,
            notes=notes,
            sources_ok=len(sources),
            n_headlines=len(headlines),
        )
        self._write_cache(pulse)
        return pulse
