# Alpha Engine v2 — mejoras cuantitativas

## Tesis
Más certeza ≠ más trades.  
Más certeza = **mejor ranking, mejor calibración, menos falsos positivos**.

## Qué había (v1)
Score heurístico + calibración simple por vecinos.

## Qué agrega v2 (nivel institucional retail)

### 1) Features de literature cuant
- Momentum **12-1** (clásico, evita mean-reversion de 1 mes)
- Momentum **vol-scaled**
- Distancia a máximo 52 semanas
- Skew de retornos (crash risk)
- Amihud-lite (iliquidez)
- MACD hist + Bollinger %b

### 2) Ensemble de 3 sleeves
- Trend/momentum
- Residual alpha (idiosincrático)
- Defensive / mean-reversion
Pesos dinámicos por régimen (risk-on / off / neutral).

### 3) Calibración avanzada
- Pesos temporales (historia reciente importa más)
- **Shrinkage Bayesiano** de E[r] hacia 0 (anti-sobreconfianza)
- **IC Spearman** del signal
- **Meta-label probability** (¿conviene operar esta señal?)

### 4) Ranking cross-sectional v2
Composite de:
- score
- expected return
- IR proxy (retorno/riesgo)
- meta-label
+ penalización suave por saturación sectorial

### 5) Risk gates más estrictos
Rechaza si:
- meta-label flojo
- IC negativo
- IR insuficiente
- edge neto insuficiente

## Próxima frontera (v3)
1. Walk-forward backtest formal out-of-sample
2. LightGBM + purged CV
3. Neutralización sectorial explícita
4. Transaction-cost-aware optimization (net alpha)
5. Event risk (earnings) para USA/Alpaca
