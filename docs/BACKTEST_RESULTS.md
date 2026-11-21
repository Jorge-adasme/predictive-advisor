# Walk-forward — referencia OOS

```bash
advisor backtest --lookback 756 --train 252 --step 10 --horizon 10 --max-positions 3
```

## v2.1 (partial TP + time-stop + sector cap + risk-on bias)

| Métrica | v2 (antes) | **v2.1** |
|---------|------------|----------|
| Trades | 10 | 12 |
| Expectancy neta/trade | +0.30% | **+0.34%** |
| Profit factor | 1.17 | **1.21** |
| Hit rate | 50% | 42% |
| Total return | −2.7% | **+3.6%** |
| Max drawdown | −4.4% | **−2.8%** |
| **Sharpe ann** | −0.47 | **+0.61** |
| Excess vs SPY | −16.4% | −10.2% |

Lectura: Sharpe ya supera el umbral 0.5. Sigue perdiendo vs buy&hold SPY en bull
(normal con mucha cash), pero el motor de riesgo/gestión mejoró claro.

## Márgenes de pérdida

Ver [`RISK_STOPS.md`](RISK_STOPS.md).
