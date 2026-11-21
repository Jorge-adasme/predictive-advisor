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

## Autopilot (paper)

Ejecuta automáticamente compras/ventas **simuladas** solo cuando hay edge neto estimado:

```bash
advisor autopilot --top 8
advisor portfolio
advisor halt
advisor resume
```

API:

- `POST /autopilot/run`
- `GET /portfolio`
- `POST /portfolio/halt`
- `POST /portfolio/resume`

Reglas de protección:

- no opera sin edge neto tras costos
- stop / take-profit automáticos
- máximo de posiciones abiertas
- kill-switch por pérdida diaria

> No garantiza ganancias. Live en BTG requiere API/partner oficial.

## Roadmap

- [x] MVP análisis + predicción + risk filter
- [x] CLI + API + journal
- [x] Stub BTG Chile
- [x] Autopilot paper + portfolio + kill-switch
- [ ] Backtest walk-forward con costos reales
- [ ] Conector oficial BTG / Finanzas Abiertas
- [ ] Semi-auto / live con aprobación
- [ ] Modelos ML entrenados (además del scoring factorial)

## Nota regulatoria (Chile)

Si este sistema se ofrece a terceros como recomendaciones de inversión, puede requerir marco CMF / Ley Fintec. El MVP actual está pensado primero para uso interno + paper.
