from __future__ import annotations

import re

# Lexicón financiero bilingüe (peso −2..+2). Suficiente sin dependencias NLP pesadas.
_POSITIVE = {
    "rally": 1.5,
    "surge": 1.5,
    "soar": 1.4,
    "beat": 1.2,
    "beats": 1.2,
    "growth": 1.0,
    "strong": 0.9,
    "record": 1.0,
    "optimistic": 1.1,
    "upgrade": 1.3,
    "upgraded": 1.3,
    "recovery": 1.0,
    "expansion": 0.9,
    "ease": 0.8,
    "easing": 1.0,
    "cut rates": 1.4,
    "rate cut": 1.4,
    "dovish": 1.3,
    "ceasefire": 1.5,
    "peace": 1.0,
    "stimulus": 1.2,
    "boom": 1.2,
    "outperform": 1.2,
    "bullish": 1.3,
    "all-time high": 1.2,
    "mejor": 0.8,
    "crecimiento": 1.0,
    "alza": 1.0,
    "sube": 0.9,
    "récord": 1.0,
    "optimista": 1.1,
    "rebote": 1.0,
    "expansión": 0.9,
}

_NEGATIVE = {
    "crash": -2.0,
    "crashed": -1.6,
    "plunges": -1.5,
    "wipeout": -1.6,
    "washout": -1.4,
    "collapse": -1.8,
    "recession": -1.7,
    "default": -1.8,
    "bankruptcy": -1.8,
    "war": -1.6,
    "invasion": -1.7,
    "sanctions": -1.3,
    "tariff": -1.1,
    "tariffs": -1.1,
    "inflation": -0.9,
    "stagflation": -1.5,
    "hawkish": -1.2,
    "hike": -1.0,
    "rate hike": -1.4,
    "layoff": -1.1,
    "layoffs": -1.2,
    "miss": -1.1,
    "misses": -1.1,
    "downgrade": -1.3,
    "downgraded": -1.3,
    "fear": -1.0,
    "panic": -1.5,
    "selloff": -1.4,
    "sell-off": -1.4,
    "plunge": -1.5,
    "slump": -1.3,
    "weak": -0.8,
    "slowdown": -1.1,
    "crisis": -1.5,
    "geopolitical": -1.0,
    "conflict": -1.2,
    "embargo": -1.4,
    "bearish": -1.3,
    "scandal": -1.7,
    "affair": -1.4,
    "cheating": -1.3,
    "lawsuit": -1.4,
    "sued": -1.3,
    "fraud": -1.8,
    "indictment": -1.7,
    "resign": -1.3,
    "resignation": -1.3,
    "bribery": -1.6,
    "harassment": -1.5,
    "controversy": -1.1,
    "probe": -1.1,
    "investigation": -1.2,
    "allegations": -1.3,
    "misconduct": -1.5,
    "caída": -1.1,
    "cae": -0.9,
    "guerra": -1.6,
    "recesión": -1.7,
    "inflación": -0.9,
    "sanciones": -1.3,
    "miedo": -1.0,
    "crisis": -1.5,
    "desempleo": -1.1,
    "default": -1.8,
    "escándalo": -1.7,
    "demanda": -1.3,
    "fraude": -1.8,
    "renuncia": -1.3,
}

# Temas macro → sector / sesgo de régimen
SECTOR_KEYWORDS: dict[str, list[str]] = {
    "Energy": ["oil", "crude", "opec", "brent", "wti", "gas", "petroleum", "petróleo"],
    "Tech": [
        "chip",
        "semiconductor",
        "ai",
        "apple",
        "nvidia",
        "microsoft",
        "google",
        "meta",
        "cloud",
        "cyber",
    ],
    "Financials": [
        "bank",
        "fed",
        "rates",
        "treasury",
        "credit",
        "yield",
        "powell",
        "ecb",
        "banco central",
    ],
    "Health": ["fda", "drug", "pharma", "biotech", "vaccine", "medicare"],
    "Consumer": ["retail", "consumer", "amazon", "walmart", "spending", "consumo"],
}

TICKER_ALIASES: dict[str, list[str]] = {
    "AAPL": ["apple"],
    "MSFT": ["microsoft"],
    "NVDA": ["nvidia"],
    "AMZN": ["amazon"],
    "GOOGL": ["alphabet", "google"],
    "META": ["meta", "facebook"],
    "TSLA": ["tesla"],
    "JPM": ["jpmorgan", "jp morgan"],
    "XOM": ["exxon"],
    "CVX": ["chevron"],
    "JNJ": ["johnson & johnson", "j&j"],
    "LLY": ["eli lilly", "lilly"],
    "ABBV": ["abbvie"],
    "MRK": ["merck"],
    "AVGO": ["broadcom"],
    "AMD": ["advanced micro devices"],
    "CRM": ["salesforce"],
    "ORCL": ["oracle"],
    "NFLX": ["netflix"],
    "INTC": ["intel"],
    "V": ["visa"],
    "MA": ["mastercard"],
    "BAC": ["bank of america"],
    "GS": ["goldman"],
    "COST": ["costco"],
    "WMT": ["walmart"],
    "HD": ["home depot"],
    "PG": ["procter"],
    "KO": ["coca-cola", "coca cola"],
    "PEP": ["pepsi"],
    "NKE": ["nike"],
    "DIS": ["disney"],
    "UNH": ["unitedhealth"],
    "BA": ["boeing"],
    "CAT": ["caterpillar"],
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _phrase_hit(haystack: str, phrase: str) -> bool:
    """Evita falsos positivos tipo war⊂forward o miss⊂dismissed."""
    if " " in phrase:
        return phrase in haystack
    return re.search(rf"\b{re.escape(phrase)}\b", haystack) is not None


def score_text(text: str) -> float:
    """Retorna sentimiento ∈ [-1, 1]."""
    t = _normalize(text)
    if not t:
        return 0.0
    score = 0.0
    hits = 0
    for phrase, w in {**_POSITIVE, **_NEGATIVE}.items():
        if _phrase_hit(t, phrase):
            score += w
            hits += 1
    if hits == 0:
        return 0.0
    # Normaliza por densidad de hits
    return float(max(-1.0, min(1.0, score / max(hits * 1.2, 1.0))))


def detect_sectors(text: str) -> list[str]:
    t = _normalize(text)
    found = []
    for sector, keys in SECTOR_KEYWORDS.items():
        if any(k in t for k in keys):
            found.append(sector)
    return found


def detect_tickers(text: str, universe: list[str] | None = None) -> list[str]:
    t = _normalize(text)
    out: list[str] = []
    uni = set(universe or TICKER_ALIASES.keys())
    for ticker, aliases in TICKER_ALIASES.items():
        if ticker not in uni and ticker not in (universe or []):
            # still allow if in default map and mentioned
            pass
        if ticker.lower() in t.split() or any(a in t for a in aliases):
            if universe is None or ticker in universe:
                out.append(ticker)
    # bare ticker tokens
    if universe:
        for tk in universe:
            if re.search(rf"\b{re.escape(tk.lower())}\b", t) and tk not in out:
                out.append(tk)
    return out


def urgency_score(text: str) -> float:
    t = _normalize(text)
    keys = [
        "breaking",
        "urgent",
        "emergency",
        "crash",
        "war",
        "attack",
        "default",
        "scandal",
        "fraud",
        "indictment",
        "última hora",
        "urgente",
        "escándalo",
    ]
    hits = sum(1 for k in keys if _phrase_hit(t, k))
    return float(min(1.0, hits / 2.0))


def is_governance_risk(text: str) -> bool:
    t = _normalize(text)
    keys = [
        "scandal", "affair", "cheating", "lawsuit", "fraud", "indictment",
        "resign", "bribery", "harassment", "misconduct", "escándalo", "fraude",
    ]
    return any(_phrase_hit(t, k) for k in keys)
