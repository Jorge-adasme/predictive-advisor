# Predictive Investment Advisor (Chile / BTG-ready)

Asistente predictivo de inversiones orientado a **expectancy neta**, riesgo y **confianza operativa** — no solo "predecir dirección".

Flujo actual (v0.4):

1. Analiza régimen + noticias (14d) + earnings blackout
2. Scorea universo (Alpaca US / Chile)
3. Estima probabilidad / retorno / edge neto tras costos
4. Autopilot con stops, trailing, diversificación y kill-switch
5. **Auditoría + performance + checklist** de sistema (paper-first)
6. *(Opcional, OFF por ahora)* capa IA de decisión — se reactiva más adelante

> No garantiza rentabilidad. No es asesoría financiera regulada. Opera primero en paper.

Confianza profesional: [`docs/PROFESSIONAL_TRUST.md`](docs/PROFESSIONAL_TRUST.md)

## Stack

- Python 3.11+
- pandas / numpy / scikit-learn
- yfinance (datos iniciales BCS)
- FastAPI + Typer/Rich CLI
- Adapter stub BTG Chile (listo para partner/SFA)

## Setup

```bash
cd predictive-advisor
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
cp .env.example .env
```

## Uso CLI

```bash
# Analizar mercado y ver recomendaciones
advisor analyze --top 8

# Walk-forward OOS (expectancy real con costos)
advisor backtest --lookback 756 --train 252 --step 10

# Pulso de noticias mundiales (afecta régimen + scores)
advisor news

# Confianza operativa
advisor system-status
advisor performance --mode paper
advisor audit --limit 30

# Calendario earnings + blackout
advisor earnings

# Salida JSON
advisor json --top 5

# Aceptar una idea y generar draft BTG
advisor accept CHILE.SN --note "paper trade"

# Ver journal
advisor journal

# Estado de integración BTG
advisor btg-status
```

## API

```bash
uvicorn advisor.api.app:app --reload --port 8000
```

Dashboard web (`/`): responsive para **iPhone** (dock inferior + safe-area) y **escritorio** (2 columnas + acciones en el header).

**Tiempo real:** el panel usa SSE (`/live/stream`) o polling (`/live`) cada ~8s para equity/posiciones, y re-analiza el cuant cada ~2 min.

Endpoints:

- `GET /health`
- `GET /live` · `GET /live/stream` (SSE tiempo casi real)
- `GET /system/status`
- `GET /performance`
- `GET /audit`
- `GET /analyze?top_n=30`
- `GET /btg/status`
- `POST /decisions` `{ "ticker": "CHILE.SN", "decision": "accepted" }`
- `GET /journal`

## Capa de IA (desactivada por ahora)

El código de decisión IA está en el repo (`docs/AI_DECISION_LAYER.md`) pero **OFF** por defecto:

```bash
ADVISOR_AI_ENABLED=false
ADVISOR_AI_GATE_AUTOPILOT=false
```

Hoy decide solo el **motor cuantitativo** (edge, stops, rotación, kill-switch). Se puede reactivar más adelante.

## Qué decide el sistema

Una recomendación `buy` solo aparece si:

- el score/probabilidad es suficiente,
- el retorno esperado supera costos round-trip estimados,
- el régimen de mercado no invalida la idea,
- el tamaño respeta riesgo por trade y tope de posición.

## Alpaca (recomendado para auto-ejecución)

Guía completa: [`docs/ALPACA_SETUP.md`](docs/ALPACA_SETUP.md)

```bash
# 1) Configura keys paper en .env
# 2) Analiza universo USA
advisor analyze --top 8

# 3) Autopilot en Alpaca Paper
advisor alpaca-status
advisor autopilot --mode alpaca --top 8
advisor portfolio --mode alpaca
```

API:

- `POST /autopilot/run?mode=alpaca`
- `GET /alpaca/status`
- `GET /portfolio?mode=alpaca`
- `POST /portfolio/halt?mode=alpaca`
- `POST /portfolio/resume?mode=alpaca`

Reglas de protección:

- no opera sin edge neto tras costos
- stop inicial ≥ **1.5%** (ATR×2; típico 1.5–5%)
- break-even a **+1R** y trail lock a **+2R**
- kill-switch diario **−2%** equity
- máximo de posiciones abiertas

Detalle: [`docs/RISK_STOPS.md`](docs/RISK_STOPS.md)

> No garantiza ganancias. Live en BTG requiere API/partner oficial.

## Motor predictivo

Alpha Engine **v2**: ensemble (trend/alpha/defensive), calibración Bayesiana,
meta-labeling e IR ranking. Ver [`docs/QUANT_ALPHA_V2.md`](docs/QUANT_ALPHA_V2.md).

## Roadmap

- [x] MVP análisis + predicción + risk filter
- [x] CLI + API + journal
- [x] Stub BTG Chile
- [x] Autopilot paper + portfolio + kill-switch
- [x] Alpha Engine v2 (ensemble + meta-label + IR)
- [x] Backtest walk-forward con costos reales (`advisor backtest`)
- [x] v2.1: partial TP, time-stop, diversificación sectorial
- [x] Factor de noticias mundiales (RSS + Yahoo) en predicción/régimen
- [x] v3: sentimiento semántico TF-IDF + NewsAPI opcional + earnings blackout
- [x] UI responsive iPhone + escritorio
- [x] Capa de confianza: system status, performance, audit log, trust bar
- [x] Stop duro por activo + kill-switch en modo rotación
- [x] Universo Alpaca ampliado (~230 tickers líquidos USA + ETFs)
- [x] Capa IA implementada pero **desactivada** (reactivar con `ADVISOR_AI_ENABLED=true`)

- [ ] Auth de usuario / sesiones
- [ ] Notificaciones (email/push) de fills y kill-switch
- [ ] Reactivar / afinar capa IA de decisión
- [ ] Conector oficial BTG / Finanzas Abiertas
- [ ] Semi-auto / live con aprobación humana
- [ ] Modelos ML entrenados (además del scoring factorial)
- [ ] Reportes exportables (CSV/PDF) para compliance personal

## Nota regulatoria (Chile)

Si este sistema se ofrece a terceros como recomendaciones de inversión, puede requerir marco CMF / Ley Fintec. El MVP actual está pensado primero para uso interno + paper.
