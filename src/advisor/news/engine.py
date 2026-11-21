from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from advisor.config import Settings, get_settings
from advisor.models import SymbolInfo
from advisor.news.feeds import (
    RawHeadline,
    fetch_google_ticker_news,
    fetch_rss_headlines,
    fetch_yahoo_ticker_news,
)
from advisor.news.newsapi_client import fetch_newsapi_headlines
from advisor.news.semantic import blend_sentiment, headline_urgency
from advisor.news.sentiment import detect_sectors, detect_tickers, is_governance_risk


@dataclass
class NewsPulse:
    as_of: str
    market_sentiment: float
    market_urgency: float
    regime_bias: float
    by_sector: dict[str, float] = field(default_factory=dict)
    by_ticker: dict[str, float] = field(default_factory=dict)
    headlines: list[dict[str, Any]] = field(default_factory=list)
    ticker_stories: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sources_ok: int = 0
    n_headlines: int = 0
    lookback_days: int = 14
    semantic_enabled: bool = True
    newsapi_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def factor_for(self, ticker: str, sector: str) -> float:
        t = float(self.by_ticker.get(ticker, 0.0))
        s = float(self.by_sector.get(sector, 0.0))
        m = float(self.market_sentiment)
        # Si hay señal específica del ticker (escándalo/CEO/etc), pesa más
        if abs(t) >= 0.15:
            return float(max(-1.0, min(1.0, 0.65 * t + 0.20 * s + 0.15 * m)))
        return float(max(-1.0, min(1.0, 0.45 * t + 0.30 * s + 0.25 * m)))


class NewsEngine:
    """Pulso de noticias recientes (no solo hoy) → régimen + factor por activo."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.cache_path = self.settings.data_dir / "news_cache.json"
        self.ttl_sec = int(getattr(self.settings, "news_cache_ttl_sec", 900))
        self.lookback_days = int(getattr(self.settings, "news_lookback_days", 14))

    def _read_cache(self) -> dict[str, Any] | None:
        if not self.cache_path.exists():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            ts = datetime.fromisoformat(payload["as_of"])
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if (
                age <= self.ttl_sec
                and payload.get("headlines")
                and int(payload.get("lookback_days") or 0) == self.lookback_days
            ):
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

    def _age_hours(self, published: datetime | None, now: datetime) -> float:
        if published is None:
            # Sin fecha: asumir mitad de la ventana (no descartar)
            return self.lookback_days * 12.0
        return max((now - published).total_seconds() / 3600.0, 0.0)

    def _recency_weight(self, age_h: float) -> float:
        """Decaimiento en lookback_days: 1.0 hoy → ~0.15 al final de la ventana."""
        horizon_h = max(self.lookback_days * 24.0, 24.0)
        if age_h > horizon_h:
            return 0.0
        return float(max(0.15, 1.0 - age_h / horizon_h))

    def pulse(
        self,
        symbols: list[SymbolInfo] | None = None,
        use_cache: bool = True,
        include_yahoo: bool = True,
    ) -> NewsPulse:
        if use_cache:
            cached = self._read_cache()
            if cached:
                cached.setdefault("semantic_enabled", True)
                cached.setdefault("newsapi_enabled", False)
                cached.setdefault("ticker_stories", [])
                cached.setdefault("lookback_days", self.lookback_days)
                fields = {k: cached[k] for k in NewsPulse.__dataclass_fields__ if k in cached}
                try:
                    return NewsPulse(**fields)
                except TypeError:
                    pass

        symbols = symbols or []
        universe = [s.ticker for s in symbols]
        sector_of = {s.ticker: s.sector for s in symbols}
        name_of = {s.ticker: s.name for s in symbols}
        semantic_w = float(getattr(self.settings, "news_semantic_weight", 0.55))
        newsapi_key = str(getattr(self.settings, "newsapi_key", "") or "")

        headlines = fetch_rss_headlines()
        sources = {h.source.split(":")[0] for h in headlines}

        # Google News por ticker (ventana lookback) — clave para eventos de hace días
        g_syms = [(s.ticker, s.name) for s in symbols if s.ticker not in {"SPY", "QQQ", "IWM", "XLF"}]
        try:
            g_items = fetch_google_ticker_news(
                g_syms,
                lookback_days=self.lookback_days,
                max_symbols=min(20, len(g_syms)),
            )
            headlines.extend(g_items)
            if g_items:
                sources.add("Google")
        except Exception:
            pass

        newsapi_on = False
        if newsapi_key:
            api_items = fetch_newsapi_headlines(newsapi_key)
            if api_items:
                headlines.extend(api_items)
                sources.add("NewsAPI")
                newsapi_on = True

        if include_yahoo and universe:
            y_items = fetch_yahoo_ticker_news(universe, limit_per=8, max_tickers=35)
            headlines.extend(y_items)
            if y_items:
                sources.add("Yahoo")

        now = datetime.now(timezone.utc)
        if not headlines:
            return NewsPulse(
                as_of=now.isoformat(),
                market_sentiment=0.0,
                market_urgency=0.0,
                regime_bias=0.0,
                notes=[
                    "Sin noticias disponibles (feeds caídos o sin red).",
                    f"Ventana buscada: últimos {self.lookback_days} días.",
                ],
                lookback_days=self.lookback_days,
                semantic_enabled=True,
                newsapi_enabled=bool(newsapi_key),
            )

        scored: list[tuple[float, float, RawHeadline, float, float, float, float]] = []
        sector_acc: dict[str, list[float]] = {}
        ticker_acc: dict[str, list[float]] = {}
        ticker_hits: dict[str, list[dict[str, Any]]] = {}

        for h in headlines:
            age_h = self._age_hours(h.published, now)
            recency = self._recency_weight(age_h)
            if recency <= 0:
                continue

            text = f"{h.title}. {h.summary}"
            sent, lex, sem = blend_sentiment(text, semantic_weight=semantic_w)
            urg = headline_urgency(text)
            gov = is_governance_risk(text)
            if gov:
                # Escándalos/CEO/fraude: refuerza negatividad y urgencia
                sent = float(max(-1.0, sent - 0.25))
                urg = float(min(1.0, urg + 0.35))

            weight = recency * (1.0 + 0.55 * urg)
            scored.append((sent, weight, h, urg, lex, sem, age_h))

            tickers = list(h.tickers) if h.tickers else detect_tickers(text, universe=universe or None)
            for sec in detect_sectors(text):
                sector_acc.setdefault(sec, []).append(sent * weight)
            for tk in tickers:
                if universe and tk not in universe:
                    continue
                # Gobernanza sobre el ticker: amplifica impacto idiosincrático
                tw = weight * (1.35 if gov else 1.0)
                ticker_acc.setdefault(tk, []).append(sent * tw)
                sec = sector_of.get(tk)
                if sec:
                    sector_acc.setdefault(sec, []).append(sent * tw * 0.45)
                ticker_hits.setdefault(tk, []).append(
                    {
                        "title": h.title,
                        "sentiment": round(sent, 3),
                        "age_hours": round(age_h, 1),
                        "governance": gov,
                        "source": h.source,
                        "url": h.url,
                    }
                )

        def _wavg(xs: list[float]) -> float:
            return float(sum(xs) / len(xs)) if xs else 0.0

        wsum = sum(w for _, w, *_ in scored) or 1.0
        market_sentiment = float(
            max(-1.0, min(1.0, sum(s * w for s, w, *_ in scored) / wsum))
        )
        market_urgency = float(
            max(0.0, min(1.0, sum(u * w for _, w, _, u, *_ in scored) / wsum))
        )
        regime_bias = float(
            max(-1.2, min(1.2, market_sentiment * 0.85 - market_urgency * 0.55))
        )

        by_sector = {k: float(max(-1, min(1, _wavg(v)))) for k, v in sector_acc.items()}
        by_ticker = {k: float(max(-1, min(1, _wavg(v)))) for k, v in ticker_acc.items()}

        ranked = sorted(scored, key=lambda x: abs(x[0]) * x[1], reverse=True)
        top: list[dict[str, Any]] = []
        for sent, weight, h, urg, lex, sem, age_h in ranked[:20]:
            days = age_h / 24.0
            top.append(
                {
                    "title": h.title,
                    "source": h.source,
                    "url": h.url,
                    "sentiment": round(sent, 3),
                    "lexicon": round(lex, 3),
                    "semantic": round(sem, 3),
                    "urgency": round(urg, 3),
                    "age_hours": round(age_h, 1),
                    "age_label": (
                        "hoy" if days < 1 else f"hace {days:.0f}d" if days < 14 else f"hace {days:.0f}d"
                    ),
                    "published": h.published.isoformat() if h.published else None,
                    "tickers": list(h.tickers),
                }
            )

        # Historias por ticker más impactantes (para UI y explicación)
        ticker_stories: list[dict[str, Any]] = []
        for tk, hits in ticker_hits.items():
            best = sorted(hits, key=lambda x: abs(x["sentiment"]), reverse=True)[0]
            ticker_stories.append(
                {
                    "ticker": tk,
                    "name": name_of.get(tk, tk),
                    "factor": round(by_ticker.get(tk, 0.0), 3),
                    "headline": best["title"],
                    "sentiment": best["sentiment"],
                    "age_hours": best["age_hours"],
                    "governance": best["governance"],
                    "source": best["source"],
                }
            )
        ticker_stories = sorted(
            ticker_stories, key=lambda x: abs(x["factor"]), reverse=True
        )[:12]

        notes: list[str] = [
            f"Ventana de noticias: últimos {self.lookback_days} días (no solo hoy).",
            "Scoring: lexicón + semántica TF-IDF"
            + (" + NewsAPI" if newsapi_on else "")
            + " + Google/Yahoo por ticker.",
        ]
        if market_sentiment <= -0.35:
            notes.append(f"Clima mediático negativo (sent={market_sentiment:.2f}).")
        elif market_sentiment >= 0.35:
            notes.append(f"Clima mediático positivo (sent={market_sentiment:.2f}).")
        else:
            notes.append(f"Clima mediático mixto (sent={market_sentiment:.2f}).")
        if ticker_stories:
            worst = min(ticker_stories, key=lambda x: x["factor"])
            notes.append(
                f"Mayor presión idiosincrática: {worst['ticker']} ({worst['factor']:+.2f}) — "
                f"{worst['headline'][:80]}"
            )

        pulse = NewsPulse(
            as_of=now.isoformat(),
            market_sentiment=market_sentiment,
            market_urgency=market_urgency,
            regime_bias=regime_bias,
            by_sector=by_sector,
            by_ticker=by_ticker,
            headlines=top,
            ticker_stories=ticker_stories,
            notes=notes,
            sources_ok=len(sources),
            n_headlines=len(scored),
            lookback_days=self.lookback_days,
            semantic_enabled=True,
            newsapi_enabled=newsapi_on,
        )
        self._write_cache(pulse)
        return pulse
