# Walk-forward — última corrida de referencia

Comando:

```bash
advisor backtest --lookback 756 --train 252 --step 10 --horizon 10 --max-positions 3
```

## Resultado (OOS) con trailing BE/+1R

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
| by_regime | 10 trades en `risk_on` | sin trades risk_off (correcto) |

Nota: en esta ventana el trailing casi no cambia el resultado porque varios trades
pegan stop **antes** de +1R. El BE ayuda cuando hay recorrido a favor.

## Márgenes de pérdida (app)

Ver [`RISK_STOPS.md`](RISK_STOPS.md): stop trade ≥1.5% (ATR×2), kill-switch −2% diario.

## Conclusión

1. Expectancy por trade > 0 → filtros OK.
2. Portafolio aún sin alpha vs SPY en bull.
3. No subir tamaño live hasta Sharpe OOS > 0.5.
