# Predictive Investment Advisor (Chile / BTG-ready)

Asistente predictivo de inversiones orientado a **ganar expectancy neta**, no solo "predecir dirección".

Flujo actual (MVP):

1. Analiza régimen de mercado (IPSA)
2. Scorea universo de acciones Chile (BCS / `.SN`)
3. Estima probabilidad / retorno esperado
4. Filtra por **edge neto después de costos BTG estimados**
5. Entrega plan: entrada, stop, target, tamaño
6. Guarda decisiones en journal (aceptar/rechazar)
7. Prepara draft de orden BTG (sin ejecución automática todavía)

> No garantiza rentabilidad. Es una herramienta de decisión con gestión de riesgo.

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

Endpoints:

- `GET /health`
- `GET /analyze?top_n=8`
- `GET /btg/status`
- `POST /decisions` `{ "ticker": "CHILE.SN", "decision": "accepted" }`
- `GET /journal`

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

- [ ] Conector oficial BTG / Finanzas Abiertas
- [ ] Semi-auto / live con aprobación
- [ ] Modelos ML entrenados (además del scoring factorial)

## Nota regulatoria (Chile)

Si este sistema se ofrece a terceros como recomendaciones de inversión, puede requerir marco CMF / Ley Fintec. El MVP actual está pensado primero para uso interno + paper.
