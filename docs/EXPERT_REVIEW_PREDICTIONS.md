# Revisión experta del motor predictivo

## Estado actual: Alpha Engine v2

El motor ya no es solo un score heurístico. Incorpora ensemble, calibración Bayesiana,
meta-labeling y ranking por Information Ratio. Detalle: [`QUANT_ALPHA_V2.md`](QUANT_ALPHA_V2.md).

### Debilidades del MVP original (cerradas en v2)
1. ~~`probability_up` no calibrada~~ → hit-rate empírico + shrinkage.
2. ~~`expected_return` lineal del score~~ → blend heurístico + E[r] shrunk + vol targeting.
3. ~~Sin alpha vs benchmark~~ → residual / relative strength.
4. ~~Sin ranking cross-sectional~~ → rank por score/E[r]/IR/meta + sector.
5. ~~Stops por vol benchmark~~ → ATR del activo + RR mínimo.
6. ~~Sin filtro liquidez~~ → Amihud-lite + volume z.
7. Walk-forward formal → **pendiente v3**.
8. Fundamentals / alt-data → **pendiente v3**.

### Qué quedó implementado (v2)
1. Features cuant: mom 12-1, vol-scaled mom, 52w, skew, Amihud, MACD, BB %b.
2. Ensemble de 3 sleeves (trend / residual alpha / defensive) con pesos por régimen.
3. Calibración: recency weights, IC Spearman, shrinkage Bayesiano, meta-label.
4. Ranking IR + meta-label + diversificación sectorial suave.
5. Risk gates: meta, IC, IR, edge neto, ATR stops.

### Próxima frontera (v3)
1. Walk-forward backtest con costos reales (Alpaca/BTG).
2. LightGBM + purged cross-validation.
3. Neutralización sectorial explícita.
4. Optimización transaction-cost-aware.
5. Event risk (earnings) USA.
6. Control de correlación de portafolio.
