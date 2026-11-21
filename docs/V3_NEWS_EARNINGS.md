# Alpha Engine v3 — News semántico + Earnings blackout

## Qué agrega este salto

### 1) Sentimiento semántico (TF-IDF “embeddings lite”)
Cada titular se compara por cosine similarity contra prototipos **bull** y **bear**.
Se mezcla con el lexicón:

```text
score = (1 − w)·lexicón + w·semántico   (w default 0.55)
```

Sin descargar transformers: rápido, local, reproducible.

### 2) NewsAPI opcional
Si configuras `ADVISOR_NEWSAPI_KEY`, se suman headlines de [newsapi.org](https://newsapi.org)
a RSS + Yahoo.

### 3) Calendario de earnings + blackout
- Fuente: Yahoo Finance (`get_earnings_dates`)
- Default: no abrir trades desde **2 días antes** hasta **1 día después** del earnings
- El score también se penaliza cerca de la fecha

## CLI / API

```bash
advisor news --refresh
advisor earnings --refresh
advisor analyze
```

```
GET /news
GET /earnings
GET /analyze   # incluye news + earnings
```

## Config

```bash
ADVISOR_NEWS_WEIGHT=0.20
ADVISOR_NEWS_SEMANTIC_WEIGHT=0.55
ADVISOR_NEWSAPI_KEY=
ADVISOR_EARNINGS_ENABLED=true
ADVISOR_EARNINGS_BLACKOUT_BEFORE=2
ADVISOR_EARNINGS_BLACKOUT_AFTER=1
```

## Por qué importa para empezar a operar

- Evita comprar justo antes de un gap de earnings
- Reacciona mejor a shocks reales (guerra, Fed, sell-off) que un keyword suelto
- Sigue siendo defendible en paper sin costos de LLM
