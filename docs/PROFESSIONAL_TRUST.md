# Capa de confianza profesional (v0.4)

Una app de inversión seria no solo “predice”: **muestra controles, límites y rastro**.

## Qué agrega v0.4

| Pieza | Para qué |
|-------|----------|
| **System status** | Checklist: keys, IA, news, earnings, riesgo, kill-switch |
| **Performance** | Win rate, expectancy, profit factor, exposición, presupuesto diario |
| **Audit log** | Bitácora append-only de `analyze`, `autopilot`, `halt`, `resume` |
| **Trust bar (UI)** | PAPER/LIVE, sistema listo, exposición, sync |
| **Disclaimer** | Visible en API y dashboard |

## Flujo de confianza

```
Cuant → IA → Autopilot
              ↓
         Audit log
              ↓
   Dashboard (riesgo + sistema + auditoría)
```

## CLI / API

```bash
advisor system-status
advisor performance --mode paper
advisor audit --limit 30
```

```
GET /health
GET /system/status
GET /performance
GET /audit
GET /dashboard   # incluye performance + system + audit
```

## Controles que ya existen (no negociables)

- Edge neto tras costos
- Stop ATR + trailing / break-even / partial TP / time-stop
- Cap de posiciones y por sector
- Kill-switch de pérdida diaria
- Gate de IA (`approve_trade`) antes de comprar
- Paper-first (Alpaca paper / paper local)

## Qué todavía no es “banco / broker regulado”

- Auth de usuarios / multi-cuenta
- Reportes fiscales
- Notificaciones push
- Cumplimiento CMF formal si se ofrece a terceros en Chile
- Live BTG sin API/partner oficial

## Principio

> Transparencia > magia. Si el sistema no puede explicar *por qué* compra o se detiene, no es confiable.
