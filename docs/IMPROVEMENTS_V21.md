# Mejoras v2.1 — post walk-forward

Diagnóstico v2: expectancy/trade > 0 pero Sharpe de portafolio flojo
(demasiada cash + stops en bull + concentración Tech).

## Qué se agregó

1. **Diversificación sectorial dura** — máx 1 posición por sector (proxy correlación).
2. **Partial take-profit** — vende 50% a **+1.5R**, resto con stop en break-even.
3. **Time-stop** — si a ~70% del horizonte no hay ≥0.3R de progreso → sale.
4. **Risk-on más agresivo** — sleeve trend 55%, umbral BUY un poco más bajo,
   +1 slot de posición en bull.
5. **Risk-off más defensivo** — menos slots abiertos.

## Cómo usar / tunear (.env)

```bash
ADVISOR_MAX_PER_SECTOR=1
ADVISOR_MAX_POSITIONS=4
ADVISOR_PARTIAL_TP_AT_R=1.5
ADVISOR_PARTIAL_TP_FRACTION=0.5
ADVISOR_TIME_STOP_FRAC=0.7
ADVISOR_TIME_STOP_MIN_R=0.3
```

## Siguiente frontera (v3)

- LightGBM + purged CV
- Correlación real (matriz 60d) en vez de solo sector
- Earnings blackout USA
- Walk-forward multi-año / bear markets
