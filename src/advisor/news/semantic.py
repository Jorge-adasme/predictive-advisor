from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from advisor.news.sentiment import score_text, urgency_score

# Prototipos semánticos ("embeddings lite" sin descargar modelos pesados)
_BULL_PROTOS = [
    "stocks rally to record highs as markets surge on strong growth and optimism",
    "federal reserve rate cut fuels bullish risk-on rally across equities",
    "company beats earnings estimates with robust revenue expansion and upgrades",
    "ceasefire and peace talks boost global markets and investor confidence",
    "stimulus and easing financial conditions support recovery and outperformance",
    "acciones suben con fuerza por crecimiento optimista y recorte de tasas",
]

_BEAR_PROTOS = [
    "stock market crash and panic selloff as recession fears grip investors",
    "war invasion sanctions and geopolitical conflict hammer global equities",
    "hawkish rate hike inflation shock triggers sharp market plunge and layoffs",
    "bank default credit crisis and bankruptcy spark financial contagion",
    "missed earnings downgrade weak guidance drive technology sell-off wipeout",
    "caída de la bolsa por guerra inflación crisis y miedo a recesión",
]

_vectorizer: TfidfVectorizer | None = None
_bull_vec = None
_bear_vec = None


def _ensure_model() -> None:
    global _vectorizer, _bull_vec, _bear_vec
    if _vectorizer is not None:
        return
    corpus = _BULL_PROTOS + _BEAR_PROTOS
    _vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        min_df=1,
        stop_words="english",
        sublinear_tf=True,
    )
    mat = _vectorizer.fit_transform(corpus)
    n_bull = len(_BULL_PROTOS)
    _bull_vec = np.asarray(mat[:n_bull].mean(axis=0))
    _bear_vec = np.asarray(mat[n_bull:].mean(axis=0))


def semantic_score(text: str) -> float:
    """Similaridad TF-IDF a prototipos bull vs bear → [-1, 1]."""
    t = (text or "").strip()
    if len(t) < 8:
        return 0.0
    _ensure_model()
    assert _vectorizer is not None and _bull_vec is not None and _bear_vec is not None
    doc = _vectorizer.transform([t])
    bull = cosine_similarity(doc, _bull_vec)
    bear = cosine_similarity(doc, _bear_vec)
    raw = float(bull[0, 0] - bear[0, 0])
    return float(max(-1.0, min(1.0, raw * 2.2)))


def blend_sentiment(text: str, semantic_weight: float = 0.55) -> tuple[float, float, float]:
    """Combina lexicón + semántica. Retorna (blend, lexicon, semantic)."""
    lex = score_text(text)
    sem = semantic_score(text)
    w = float(max(0.0, min(1.0, semantic_weight)))
    blended = float(max(-1.0, min(1.0, (1 - w) * lex + w * sem)))
    return blended, lex, sem


def headline_urgency(text: str) -> float:
    return urgency_score(text)
