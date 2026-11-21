# Factor de noticias mundiales

Las predicciones ya no miran solo precio: incorporan un **pulso de noticias** que puede mover la bolsa.

## Fuentes (gratis, sin API key)

- BBC Business RSS
- CNBC Top / World RSS
- MarketWatch Top Stories
- Federal Reserve press feed
- Yahoo Finance news por ticker del universo

Cache local `data/news_cache.json` (~20 min) para no golpear feeds.

## Cómo entra al modelo

1. **Sentimiento** lexicón EN/ES (−1…+1) + **urgencia** (breaking/war/crash…).
2. **Régimen**: `regime_score += news_regime_bias`. Shock muy negativo puede forzar `risk_off`.
3. **Score por activo**:
   `news_factor = 0.50·ticker + 0.30·sector + 0.20·market`
   `score += news_weight × news_factor` (default weight 0.18).
4. **Risk gates**: si noticias adversas de alto impacto → `avoid` (no abre riesgo).

## CLI / API

```bash
advisor news
advisor news --refresh
advisor analyze   # ya incluye bloque Noticias
```

```
GET /news
GET /analyze   # campo news + market.news_*
```

## Config

```bash
ADVISOR_NEWS_ENABLED=true
ADVISOR_NEWS_WEIGHT=0.18
ADVISOR_NEWS_CACHE_TTL_SEC=1200
```

## Límites honestos

- No es NLP transformer ni Bloomberg Terminal.
- Titulares pueden ser ruidosos; el peso es moderado a propósito.
- Próximo salto: embeddings / NewsAPI opcional / earnings calendar.
