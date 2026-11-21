# Márgenes de pérdida — cuándo vende la app

## Respuesta corta

| Capa | Margen | Qué hace |
|------|--------|----------|
| **Stop por trade** | **≥ 1.5%** bajo la entrada (piso). Típico **1.5%–5%+** según ATR×2 | Vende esa posición |
| **Break-even** | Al llegar a **+1R** de ganancia | Sube el stop a entrada (+buffer de costo) |
| **Trail lock** | Al llegar a **+2R** | Fija stop en **+1R** (protege ganancia) |
| **Kill-switch diario** | **−2%** del equity del día | Pausa TODO el autopilot |
| **Riesgo por trade** | **0.75%** del equity (sizing) | Define el tamaño, no el stop |

R = `entry − stop_inicial` (dinero de riesgo por acción).

## Stop inicial (fórmula)

```text
stop_distance = max(
  precio × max(ATR% × 2, 1.5%),
  precio × vol_diaria_benchmark × 2,
  precio × 1.5%
)
stop = entry − stop_distance
```

Ejemplos:
- Acción tranquila (ATR% ~0.8%) → stop ≈ **−1.5%** (piso).
- Acción volátil (ATR% ~2.5%) → stop ≈ **−5%**.

Cada plan expone `stop_pct` (margen exacto de esa idea).

## Kill-switch de portafolio

`ADVISOR_MAX_DAILY_LOSS_PCT=0.02` (default).
Si el PnL diario ≤ −2% del equity → `halt` y no abre más trades ese día.

## Trailing (nuevo)

1. Precio ≥ entrada + 1R → stop sube a **break-even** (entrada + medio costo RT).
2. Precio ≥ entrada + 2R → stop sube a **entrada + 1R**.
3. El stop **nunca baja**.

Aplica en paper, backtest y autopilot (Alpaca vía `trail_stops.json` + cierre manual si toca el trail).

## Config (.env)

```bash
ADVISOR_MIN_STOP_PCT=0.015
ADVISOR_ATR_STOP_MULT=2.0
ADVISOR_MAX_DAILY_LOSS_PCT=0.02
ADVISOR_BREAKEVEN_AT_R=1.0
ADVISOR_TRAIL_AT_R=2.0
ADVISOR_RISK_PER_TRADE=0.0075
```
