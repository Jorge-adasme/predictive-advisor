# Walk-forward backtest

Valida expectancy **out-of-sample** del Alpha Engine v2 con costos round-trip.

## Cómo corre

1. Descarga historia (Yahoo, ~2–3 años).
2. En cada fecha de decisión `t` (cada `step` días):
   - Score/plan **solo** con datos ≤ `t` (sin look-ahead).
   - Toma hasta `max_positions` BUYs.
   - Simula hold `t+1 … t+H` con stop/target ATR.
   - Si stop y target el mismo día → **stop** (conservador).
   - Resta `round_trip_cost_pct` (slippage Alpaca ~10 bps ida-vuelta).
3. Si no hay BUY → cash (retorno 0). Eso también es edge.

## CLI

```bash
advisor backtest --lookback 756 --train 252 --step 10 --horizon 10 --max-positions 3
```

Guarda detalle en `data/backtest_walk_forward.json`.

## API

```
GET /backtest/walk-forward?lookback=756&train=252&step=10&horizon=10&max_positions=3
```

## Métricas clave

| Métrica | Qué mira |
|---------|----------|
| `expectancy_net` | E[r] neto por trade |
| `hit_rate` | % trades con net > 0 |
| `profit_factor` | suma wins / |suma losses| |
| `sharpe_ann` | Sharpe anualizado de retornos por fold |
| `max_drawdown` | Peor caída del equity curve |
| `excess_return` | Total strategy − buy&hold benchmark |

## Lectura honesta

- Expectancy > 0 y Sharpe > 0.5 con MaxDD tolerable → candidato a subir tamaño paper.
- Expectancy ≤ 0 → **no** subir capital; ajustar gates / no operar.
- Pocos trades → resultado inestable; ampliar lookback o relajar filtros solo con evidencia.
