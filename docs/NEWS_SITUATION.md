# Noticias = situación actual (no solo hoy)

## Ventana
Por defecto **14 días** (`ADVISOR_NEWS_LOOKBACK_DAYS`).
Un evento de hace una semana (p.ej. escándalo de un CEO) sigue entrando al score
con peso menor que una noticia de hoy, pero **sí afecta** la predicción del ticker.

## Fuentes
- RSS macro: BBC, CNBC, MarketWatch, Fed, Google Markets
- **Google News por ticker** (NVDA, AAPL, …) con `when:14d`
- Yahoo Finance news por ticker
- NewsAPI opcional

## Cómo impacta una acción
1. Detecta si el titular habla del ticker (alias: NVIDIA→NVDA).
2. Sentimiento lexicón + semántico; **gobernanza** (scandal/fraud/lawsuit/CEO) amplifica.
3. `news_factor` del activo = mezcla ticker (65%) + sector + mercado.
4. Eso mueve score, sizing y puede mandar a **avoid**.

## UI
- Bloque **Impacto por acción**
- Titulares con etiqueta `hoy` / `hace 3d`
