# Capa de IA para decisiones

> **Estado actual: DESACTIVADA** (`ADVISOR_AI_ENABLED=false`).  
> El código permanece listo; se reactivará más adelante. Hoy decide solo el cuant.

## Idea
La automatización ejecuta. La **IA decide**.

```
Datos → Cuant (score/news/earnings/risk)
      → IA Decision Agent (buy/hold/avoid + approve_trade)
      → Autopilot (solo si IA aprueba, si gate ON)
```

## Modos

| Provider | Qué necesita | Cuándo usarlo |
|----------|--------------|---------------|
| `local` (default) | Nada | Comité explicable siempre ON |
| `openai` | `ADVISOR_AI_API_KEY` | GPT decide con el contexto cuant |
| `anthropic` | `ADVISOR_AI_API_KEY` | Claude decide |

## Config

```bash
ADVISOR_AI_ENABLED=true
ADVISOR_AI_PROVIDER=local          # local | openai | anthropic
ADVISOR_AI_API_KEY=
ADVISOR_AI_MODEL=                  # vacío = default
ADVISOR_AI_GATE_AUTOPILOT=true     # autopilot exige approve_trade
```

## CLI / API

```bash
advisor analyze          # incluye bloque Decisión IA
advisor ai-decide
```

```
GET /ai/decisions
GET /analyze             # campos ai + ai_decisions + item.ai
```

## Qué mira la IA
- Régimen, edge neto, score, probabilidad
- Noticias 14d y riesgo de gobernanza por ticker
- Earnings blackout
- Meta-label / IC

## Importante
La IA **no reemplaza** stops ni kill-switch. Solo autoriza o veta la entrada.
