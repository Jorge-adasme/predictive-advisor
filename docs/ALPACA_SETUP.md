# Setup Alpaca (Paper → Live)

## 1) Crear cuenta
1. Entra a https://alpaca.markets
2. Crea cuenta
3. Abre **Paper Trading**
4. En el dashboard: **API Keys** → Create Key

Copia:
- `API Key ID`
- `Secret Key`

## 2) Configurar la app

En `.env`:

```bash
ADVISOR_BROKER=alpaca
ADVISOR_BASE_CURRENCY=USD
ADVISOR_UNIVERSE_PATH=configs/universe_alpaca_us.json

# Costos Alpaca (acciones USA commission-free; modelamos slippage)
ADVISOR_COMMISSION_RATE=0.0
ADVISOR_VAT_RATE=0.0
ADVISOR_SLIPPAGE_BPS=5
ADVISOR_MIN_EDGE_NET_PCT=0.002

ADVISOR_ALPACA_API_KEY=PK...
ADVISOR_ALPACA_SECRET_KEY=...
ADVISOR_ALPACA_PAPER=true
```

## 3) Probar

```bash
source .venv/bin/activate
advisor alpaca-status
advisor analyze --top 8
advisor autopilot --mode alpaca --top 8
advisor portfolio --mode alpaca
```

## 4) Pasar a live (después de validar paper)

1. Genera keys de cuenta **Live**
2. Cambia:

```bash
ADVISOR_ALPACA_PAPER=false
ADVISOR_ALPACA_API_KEY=...
ADVISOR_ALPACA_SECRET_KEY=...
```

3. Empieza con capital pequeño y kill-switch activo.

## Universo ampliado (Alpaca)

`configs/universe_alpaca_us.json` incluye **~230 tickers líquidos** USA:

- Mega/large cap tech, financials, health, energy, industrials, consumer
- Utilities, materials, real estate, telecom
- ETFs sectoriales + SPY/QQQ/IWM/VOO + bonos/oro/intl

Diseñado para **Alpaca** (NYSE/NASDAQ). Se evitan OTC y penny stocks.

```bash
# Ver cuántos escanea
python -c "from advisor.adapters.universe import load_universe; from pathlib import Path; print(len(load_universe(Path('configs/universe_alpaca_us.json'))[1]))"
advisor analyze --top 30
```

Si el análisis tarda mucho, baja lookback o top_n; el universo puede seguir grande.

## Notas
- Paper y Live usan endpoints distintos; no mezcles keys.
- Horario mercado USA (no opera 24/7).
- No garantiza rentabilidad; el autopilot solo opera con edge neto estimado.
- Más tickers ≠ más trades: sigue filtrando por edge neto, stops e IA.
