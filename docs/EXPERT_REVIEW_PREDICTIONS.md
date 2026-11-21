# Revisión experta del motor predictivo (pre-Alpaca)

## Diagnóstico del MVP actual

El sistema actual es un **score heurístico técnico**. Útil como base, pero todavía no es un predictor calibrado.

### Debilidades principales
1. `probability_up` no está calibrada con frecuencia real histórica.
2. `expected_return` es una transformación lineal del score (no estimada).
3. No mide **alpha** vs benchmark (solo momentum absoluto).
4. No hay ranking **cross-sectional** (comparar vs el universo del día).
5. Stops basados en vol del benchmark, no en ATR del activo.
6. Falta filtro de liquidez/microestructura.
7. No hay validación walk-forward / out-of-sample formal.
8. Sin fundamentals (earnings surprise, valuation) ni alternative data.

## Qué implementamos ahora (mayor ROI)
1. Features avanzadas: ATR, trend quality, gap, liquidez, multi-horizon momentum.
2. Relative strength / residual vs benchmark.
3. Calibración empírica rolling (hit-rate y E[r] histórico por señal).
4. Ranking cross-sectional del universo.
5. Stops/targets por ATR + mínimo reward/risk.
6. Penalización por sobreextensión y baja liquidez.

## Qué falta después (fase Alpaca)
1. Walk-forward backtest con costos Alpaca reales.
2. Modelo ML (LightGBM) entrenado out-of-sample.
3. Meta-labeling (operar solo cuando el modelo de confianza confirma).
4. Control de correlación de portafolio.
5. Event risk (earnings calendar) para USA.
6. Ejecución Alpaca paper → live.
