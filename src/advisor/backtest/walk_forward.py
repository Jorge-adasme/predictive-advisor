from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from advisor.adapters.yahoo import YahooMarketDataAdapter
from advisor.analysis.regime import detect_regime
from advisor.config import Settings, get_settings
from advisor.models import Action, SymbolInfo
from advisor.prediction.ranking import apply_cross_sectional_ranks
from advisor.prediction.scoring import score_symbol
from advisor.risk.engine import build_trade_plan


@dataclass
class SimulatedTrade:
    ticker: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    position_pct: float
    gross_return: float
    net_return: float
    exit_reason: str
    score: float
    edge_net_pct: float
    probability_up: float
    regime: str


@dataclass
class BacktestResult:
    as_of: str
    lookback_days: int
    train_bars: int
    step_days: int
    horizon_days: int
    max_positions: int
    round_trip_cost_pct: float
    n_rebalances: int
    n_trades: int
    hit_rate: float
    avg_gross: float
    avg_net: float
    expectancy_net: float
    profit_factor: float
    sharpe_ann: float
    max_drawdown: float
    total_return: float
    cash_rebalances: int
    benchmark_return: float
    excess_return: float
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    folds: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _align_histories(
    histories: dict[str, pd.DataFrame],
    tickers: list[str],
) -> dict[str, pd.DataFrame]:
    """Normaliza índices a fechas naive UTC date para slices consistentes."""
    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        df = histories.get(t)
        if df is None or df.empty:
            continue
        frame = df.copy()
        idx = pd.to_datetime(frame.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        frame.index = idx.normalize()
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        out[t] = frame
    return out


def _common_calendar(histories: dict[str, pd.DataFrame], benchmark: str) -> pd.DatetimeIndex:
    bench = histories[benchmark]
    # Solo fechas donde al menos 40% del universo tiene dato
    counts = None
    for df in histories.values():
        s = pd.Series(1, index=df.index)
        counts = s if counts is None else counts.add(s, fill_value=0)
    min_count = max(3, int(0.4 * len(histories)))
    valid = counts[counts >= min_count].index.intersection(bench.index)
    return pd.DatetimeIndex(sorted(valid))


def _simulate_hold(
    path: pd.DataFrame,
    entry_price: float,
    stop: float,
    target: float,
    horizon_days: int,
) -> tuple[float, str, pd.Timestamp]:
    """Simula stop/target/horizon sin look-ahead intradía sesgado: stop primero si ambos."""
    if path.empty:
        return entry_price, "no_path", pd.Timestamp.utcnow()

    window = path.iloc[:horizon_days]
    for ts, row in window.iterrows():
        low = float(row["Low"])
        high = float(row["High"])
        close = float(row["Close"])
        # Conservador: si toca stop y target el mismo día, gana el stop
        if low <= stop:
            return stop, "stop", pd.Timestamp(ts)
        if high >= target:
            return target, "target", pd.Timestamp(ts)
        last_close, last_ts = close, pd.Timestamp(ts)
    return last_close, "horizon", last_ts


def _metrics_from_returns(period_rets: list[float], periods_per_year: float) -> tuple[float, float, float]:
    if not period_rets:
        return 0.0, 0.0, 0.0
    arr = np.asarray(period_rets, dtype=float)
    equity = np.cumprod(1.0 + arr)
    peak = np.maximum.accumulate(equity)
    dd = (equity / peak) - 1.0
    max_dd = float(dd.min()) if len(dd) else 0.0
    total = float(equity[-1] - 1.0)
    vol = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    mean = float(arr.mean())
    sharpe = float((mean / vol) * np.sqrt(periods_per_year)) if vol > 1e-12 else 0.0
    return total, max_dd, sharpe


class WalkForwardBacktester:
    """Walk-forward out-of-sample con costos round-trip y stops ATR."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def run(
        self,
        lookback_days: int = 756,
        train_bars: int = 252,
        step_days: int | None = None,
        horizon_days: int | None = None,
        max_positions: int = 3,
        top_n: int = 8,
    ) -> BacktestResult:
        settings = self.settings
        horizon = horizon_days or settings.horizon_days
        step = step_days or horizon
        adapter = YahooMarketDataAdapter(settings)
        symbols = adapter.load_universe()
        # Excluir ETFs de trading activo si son benchmark
        trade_symbols = [s for s in symbols if s.ticker != adapter.benchmark]
        tickers = [s.ticker for s in trade_symbols] + [adapter.benchmark]

        raw = adapter.get_history(tickers, lookback_days)
        histories = _align_histories(raw, tickers)
        if adapter.benchmark not in histories:
            raise RuntimeError("Sin datos de benchmark para backtest.")

        calendar = _common_calendar(histories, adapter.benchmark)
        if len(calendar) < train_bars + horizon + 5:
            raise RuntimeError(
                f"Historia insuficiente: {len(calendar)} barras "
                f"(se necesitan ~{train_bars + horizon + 5})."
            )

        symbol_map = {s.ticker: s for s in trade_symbols}
        trades: list[SimulatedTrade] = []
        folds: list[dict[str, Any]] = []
        equity_curve: list[dict[str, Any]] = []
        period_rets: list[float] = []
        cash_rebalances = 0
        equity = 1.0

        decision_indices = list(range(train_bars - 1, len(calendar) - horizon - 1, step))
        notes = [
            "Walk-forward: score/plan solo con datos hasta t; outcome en t+1..t+H.",
            "Costo round-trip aplicado a cada trade abierto.",
            "Si stop y target el mismo día → se asume stop (conservador).",
            "Sin BUY en un fold → cash (retorno 0).",
        ]

        for di in decision_indices:
            decision_date = calendar[di]
            # Historia visible hasta decisión (inclusive)
            hist_slice: dict[str, pd.DataFrame] = {}
            for t, df in histories.items():
                sliced = df.loc[:decision_date]
                if len(sliced) >= 60:
                    hist_slice[t] = sliced

            bench = hist_slice.get(adapter.benchmark)
            if bench is None or len(bench) < 60:
                continue

            market = detect_regime(bench, adapter.benchmark)
            predictions = []
            for ticker, sym in symbol_map.items():
                h = hist_slice.get(ticker)
                if h is None or len(h) < 60:
                    continue
                # Evitar entrada si no hay path futuro
                full = histories.get(ticker)
                if full is None:
                    continue
                future_idx = full.index.searchsorted(decision_date, side="right")
                if future_idx >= len(full):
                    continue
                pred = score_symbol(
                    symbol=sym,
                    history=h,
                    regime=market.regime,
                    horizon_days=horizon,
                    benchmark_history=bench,
                )
                if pred is not None:
                    predictions.append(pred)

            if not predictions:
                cash_rebalances += 1
                period_rets.append(0.0)
                equity_curve.append(
                    {
                        "date": decision_date.strftime("%Y-%m-%d"),
                        "equity": equity,
                        "period_return": 0.0,
                        "n_trades": 0,
                        "regime": market.regime.value,
                    }
                )
                folds.append(
                    {
                        "date": decision_date.strftime("%Y-%m-%d"),
                        "regime": market.regime.value,
                        "candidates": 0,
                        "buys": 0,
                        "period_return": 0.0,
                    }
                )
                continue

            predictions = apply_cross_sectional_ranks(predictions)
            buys = []
            for pred in predictions:
                plan = build_trade_plan(pred, market, settings)
                if plan is None:
                    continue
                if plan.action == Action.BUY and plan.position_pct > 0:
                    buys.append((pred, plan))
                if len(buys) >= max_positions:
                    break
            # Ordenar por edge neto / score ya viene del ranking
            buys = buys[:max_positions]

            if not buys:
                cash_rebalances += 1
                period_ret = 0.0
            else:
                weights = np.array([p.position_pct for _, p in buys], dtype=float)
                weights = weights / weights.sum()
                fold_rets = []
                for w, (pred, plan) in zip(weights, buys):
                    full = histories[pred.ticker]
                    future = full.iloc[full.index.searchsorted(decision_date, side="right") :]
                    exit_px, reason, exit_ts = _simulate_hold(
                        path=future,
                        entry_price=plan.entry_price,
                        stop=plan.stop_price,
                        target=plan.target_price,
                        horizon_days=horizon,
                    )
                    # Entrada al close de decisión (ya en plan.entry_price ≈ last close)
                    gross = (exit_px / plan.entry_price) - 1.0
                    net = gross - settings.round_trip_cost_pct
                    fold_rets.append(w * net)
                    trades.append(
                        SimulatedTrade(
                            ticker=pred.ticker,
                            entry_date=decision_date.strftime("%Y-%m-%d"),
                            exit_date=exit_ts.strftime("%Y-%m-%d"),
                            entry_price=float(plan.entry_price),
                            exit_price=float(round(exit_px, 4)),
                            stop_price=float(plan.stop_price),
                            target_price=float(plan.target_price),
                            position_pct=float(plan.position_pct),
                            gross_return=float(gross),
                            net_return=float(net),
                            exit_reason=reason,
                            score=float(pred.score),
                            edge_net_pct=float(plan.edge_net_pct),
                            probability_up=float(pred.probability_up),
                            regime=market.regime.value,
                        )
                    )
                period_ret = float(np.sum(fold_rets))

            equity *= 1.0 + period_ret
            period_rets.append(period_ret)
            equity_curve.append(
                {
                    "date": decision_date.strftime("%Y-%m-%d"),
                    "equity": float(equity),
                    "period_return": period_ret,
                    "n_trades": len(buys),
                    "regime": market.regime.value,
                }
            )
            folds.append(
                {
                    "date": decision_date.strftime("%Y-%m-%d"),
                    "regime": market.regime.value,
                    "candidates": len(predictions),
                    "buys": len(buys),
                    "period_return": period_ret,
                    "tickers": [p.ticker for p, _ in buys],
                }
            )

        # Benchmark buy&hold en la misma ventana OOS
        bench_full = histories[adapter.benchmark]
        if decision_indices:
            start_d = calendar[decision_indices[0]]
            end_d = calendar[min(decision_indices[-1] + horizon, len(calendar) - 1)]
            b0 = float(bench_full.loc[:start_d]["Close"].iloc[-1])
            b1 = float(bench_full.loc[:end_d]["Close"].iloc[-1])
            bench_ret = (b1 / b0) - 1.0
        else:
            bench_ret = 0.0

        nets = [t.net_return for t in trades]
        grosses = [t.gross_return for t in trades]
        wins = [r for r in nets if r > 0]
        losses = [r for r in nets if r <= 0]
        hit = (len(wins) / len(nets)) if nets else 0.0
        avg_net = float(np.mean(nets)) if nets else 0.0
        avg_gross = float(np.mean(grosses)) if grosses else 0.0
        # Expectancy clásica: E[r] por trade
        expectancy = avg_net
        gross_wins = float(np.sum(wins)) if wins else 0.0
        gross_losses = float(abs(np.sum(losses))) if losses else 0.0
        profit_factor = (gross_wins / gross_losses) if gross_losses > 1e-12 else (999.0 if gross_wins > 0 else 0.0)

        periods_per_year = 252.0 / max(step, 1)
        total_ret, max_dd, sharpe = _metrics_from_returns(period_rets, periods_per_year)

        return BacktestResult(
            as_of=datetime.now(timezone.utc).isoformat(),
            lookback_days=lookback_days,
            train_bars=train_bars,
            step_days=step,
            horizon_days=horizon,
            max_positions=max_positions,
            round_trip_cost_pct=float(settings.round_trip_cost_pct),
            n_rebalances=len(period_rets),
            n_trades=len(trades),
            hit_rate=float(hit),
            avg_gross=avg_gross,
            avg_net=avg_net,
            expectancy_net=float(expectancy),
            profit_factor=float(min(profit_factor, 999.0)),
            sharpe_ann=float(sharpe),
            max_drawdown=float(max_dd),
            total_return=float(total_ret),
            cash_rebalances=cash_rebalances,
            benchmark_return=float(bench_ret),
            excess_return=float(total_ret - bench_ret),
            trades=[asdict(t) for t in trades],
            equity_curve=equity_curve,
            folds=folds,
            notes=notes,
        )
