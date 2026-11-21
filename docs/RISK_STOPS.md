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

## Stop por activo (lo primero)

Cada compra tiene:

1. **Stop ATR** (típico −1.5% a −5%)
2. **Tope duro** `ADVISOR_MAX_POSITION_LOSS_PCT=0.025` → si esa acción cae **−2.5%** desde la entrada, **se vende sola** (`max_position_loss`)

No esperas al −2% de toda la cuenta: la posición mala se corta antes.

## Kill-switch diario (modo rotación)

`ADVISOR_MAX_DAILY_LOSS_PCT=0.02` + `ADVISOR_KILL_SWITCH_MODE=rotate` (default).

Si el PnL diario ≤ −2% del equity:

1. Gestiona stops/trailing.
2. Vende posiciones en rojo.
3. **No bloquea todo**: entra en defensa (tamaño ×0.45) y **busca otras ideas** con edge.
4. `pause` (opcional) sí bloquea compras nuevas.

Micro-edges: si el edge neto > 0 (aunque sea chico), puede comprar con tamaño reducido (`ADVISOR_ALLOW_MICRO_EDGE=true`).

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
ADVISOR_HALT_CLOSE_LOSERS=true
ADVISOR_HALT_FLATTEN_ALL=false
ADVISOR_BREAKEVEN_AT_R=1.0
ADVISOR_TRAIL_AT_R=2.0
ADVISOR_RISK_PER_TRADE=0.0075
```
