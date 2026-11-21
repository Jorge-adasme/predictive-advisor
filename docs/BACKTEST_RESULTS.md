# Walk-forward — última corrida de referencia

Comando:

```bash
advisor backtest --lookback 756 --train 252 --step 10 --horizon 10 --max-positions 3
```

## Resultado (OOS)

| Métrica | Valor | Lectura |
|---------|-------|---------|
| Rebalances | 24 | ventana ~1 año OOS |
| Trades | 10 | muy selectivo |
| Cash folds | 19/24 | capital protection activa |
| Hit rate | 50% | mixto |
| Expectancy neta/trade | **+0.30%** | edge por trade positivo tras costos |
| Profit factor | 1.17 | barely > 1 |
| Total return | −2.7% | equity curve flojo |
| Max drawdown | −4.4% | daño controlado |
| Sharpe ann | −0.47 | no sirve aún como alpha de portafolio |
| Excess vs SPY | −16.4% | buy&hold gana en bull |

Exits: 4 horizon / 4 stop / 2 target.

## Conclusión experta

1. **Por trade** hay expectancy neta ligeramente positiva → los filtros no están rotos.
2. **Por portafolio** todavía no hay alpha: demasiada cash + stops frecuentes en tendencia alcista.
3. **No subir tamaño live** hasta mejorar Sharpe OOS (>0.5) y excess ≥ 0 en la misma ventana.
4. Próximos ajustes de mayor ROI:
   - Trailing stop / break-even tras +1R (menos stops prematuros)
   - Permitir sleeve trend más agresivo en `risk_on` prolongado
   - Walk-forward en bear/sideways separado (regime-conditioned metrics)
   - LightGBM meta-label con purged CV
