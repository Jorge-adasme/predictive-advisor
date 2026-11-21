from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from advisor.advisory.pipeline import AdvisoryPipeline
from advisor.config import get_settings
from advisor.models import Recommendation
from advisor.portfolio.journal import JournalStore

app = typer.Typer(help="Predictive Investment Advisor (Chile / BTG-ready)")
console = Console()


@app.command("analyze")
def analyze(top: int = typer.Option(8, help="Cantidad de recomendaciones")) -> None:
    """Analiza mercado Chile y genera recomendaciones predictivas."""
    pipeline = AdvisoryPipeline()
    result = pipeline.analyze(top_n=top)

    if result.get("error"):
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    market = result["market"]
    console.print("\n[bold]Situación de mercado[/bold]")
    console.print(
        f"Régimen: [cyan]{market['regime']}[/cyan] | "
        f"Score: {market['regime_score']:.2f} | "
        f"Ret 20d: {market['benchmark_return_20d']:.2%} | "
        f"Vol 20d: {market['benchmark_volatility_20d']:.2%}"
    )
    for note in market.get("notes", []):
        console.print(f"- {note}")

    if market.get("news_sentiment") is not None:
        console.print(
            f"\n[bold]Noticias[/bold] sent={market.get('news_sentiment', 0):+.2f} | "
            f"urgencia={market.get('news_urgency', 0):.2f} | "
            f"bias régimen={market.get('news_regime_bias', 0):+.2f}"
        )
        for h in (market.get("news_headlines") or [])[:5]:
            console.print(
                f"  • [{h.get('sentiment', 0):+.2f}] {h.get('title', '')[:110]}"
            )

    if result.get("message"):
        style = "green" if result.get("actionable") else "yellow"
        console.print(f"\n[{style}]{result['message']}[/{style}]")

    table = Table(title="Ranking / Recomendaciones")
    table.add_column("#", justify="right")
    table.add_column("Ticker")
    table.add_column("Acción")
    table.add_column("Prob↑", justify="right")
    table.add_column("E[r]", justify="right")
    table.add_column("Edge neto", justify="right")
    table.add_column("Pos %", justify="right")
    table.add_column("Entrada", justify="right")
    table.add_column("Stop", justify="right")
    table.add_column("Stop%", justify="right")
    table.add_column("Target", justify="right")

    for rec in result["recommendations"]:
        pred = rec["prediction"]
        plan = rec["plan"]
        table.add_row(
            str(rec["rank"]),
            pred["ticker"],
            plan["action"],
            f"{pred['probability_up']:.0%}",
            f"{pred['expected_return']:.2%}",
            f"{plan['edge_net_pct']:.2%}",
            f"{plan['position_pct']:.1%}",
            f"{plan['entry_price']:.2f}",
            f"{plan['stop_price']:.2f}",
            f"{float(plan.get('stop_pct') or 0):.1%}",
            f"{plan['target_price']:.2f}",
        )

    console.print(table)

    if result["recommendations"]:
        top_rec = result["recommendations"][0]
        console.print("\n[bold]Detalle #1[/bold]")
        console.print(f"{top_rec['prediction']['name']} ({top_rec['prediction']['ticker']})")
        for reason in top_rec["prediction"]["reasons"]:
            console.print(f"[green]+[/green] {reason}")
        for risk in top_rec["prediction"]["risks"]:
            console.print(f"[yellow]![/yellow] {risk}")
        console.print(f"Invalidación: {top_rec['plan']['invalidation']}")
        console.print(f"[dim]{top_rec['disclaimer']}[/dim]")

    console.print(
        f"\nEscaneados: {result['scanned']} | "
        f"Costo round-trip estimado: {result['cost_model']['round_trip_cost_pct']:.2%}"
    )


@app.command("json")
def analyze_json(top: int = typer.Option(8, help="Cantidad de recomendaciones")) -> None:
    """Misma salida en JSON (útil para integraciones)."""
    result = AdvisoryPipeline().analyze(top_n=top)
    console.print_json(json.dumps(result, default=str))


@app.command("accept")
def accept(
    ticker: str = typer.Argument(..., help="Ticker exacto de la recomendación"),
    note: Optional[str] = typer.Option(None, help="Nota opcional"),
) -> None:
    """Registra en journal que aceptaste una recomendación."""
    settings = get_settings()
    pipeline = AdvisoryPipeline(settings)
    result = pipeline.analyze(top_n=settings.top_n)
    match = next(
        (
            Recommendation.model_validate(item)
            for item in result["recommendations"]
            if item["prediction"]["ticker"].upper() == ticker.upper()
        ),
        None,
    )
    if match is None:
        console.print(f"[red]No hay recomendación activa para {ticker}[/red]")
        raise typer.Exit(code=1)

    store = JournalStore(settings.data_dir / "journal.json")
    entry = store.record_decision(match, decision="accepted", outcome_note=note or "")
    draft = pipeline.draft_order(match)
    console.print("[green]Decisión registrada[/green]")
    console.print_json(json.dumps({"journal": entry.model_dump(mode="json"), "btg_draft": draft}, default=str))


@app.command("journal")
def journal(limit: int = typer.Option(20)) -> None:
    settings = get_settings()
    store = JournalStore(settings.data_dir / "journal.json")
    rows = store.list_entries(limit=limit)
    console.print_json(json.dumps(rows, default=str))


@app.command("btg-status")
def btg_status() -> None:
    status = AdvisoryPipeline().btg.status()
    from advisor.execution.live_btg import BTGLiveExecutor

    live = BTGLiveExecutor(get_settings()).gate()
    console.print_json(
        json.dumps(
            {
                "adapter": status.__dict__,
                "live_gate": {
                    "enabled": live.enabled,
                    "reason": live.reason,
                    "next_steps": live.next_steps,
                },
            },
            default=str,
        )
    )


@app.command("alpaca-status")
def alpaca_status() -> None:
    """Estado de cuenta Alpaca (paper/live según .env)."""
    settings = get_settings()
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        console.print("[red]Faltan ADVISOR_ALPACA_API_KEY / ADVISOR_ALPACA_SECRET_KEY[/red]")
        console.print("Guía: docs/ALPACA_SETUP.md")
        raise typer.Exit(code=1)
    from advisor.execution.alpaca_broker import AlpacaBroker

    console.print_json(json.dumps(AlpacaBroker(settings).status(), default=str))


@app.command("autopilot")
def autopilot(
    mode: str = typer.Option("alpaca", help="alpaca | paper"),
    once: bool = typer.Option(True, help="Ejecutar un ciclo y salir"),
    top: int = typer.Option(8, help="Ideas a evaluar"),
) -> None:
    """Ejecuta inversiones automáticamente con risk gates."""
    from advisor.execution.autopilot import Autopilot

    result = Autopilot(mode=mode).run_once(top_n=top)
    console.print(f"[bold]{result.message}[/bold]")
    console.print_json(
        json.dumps(
            {
                "ts": result.ts,
                "mode": result.mode,
                "actions": result.actions,
                "portfolio": result.portfolio,
                "market": result.market,
            },
            default=str,
        )
    )
    if not once:
        console.print("[yellow]Loop continuo: usa un scheduler/cron por ahora.[/yellow]")


@app.command("portfolio")
def portfolio(mode: str = typer.Option("alpaca", help="alpaca | paper")) -> None:
    """Estado del portafolio."""
    from advisor.execution.autopilot import build_broker

    console.print_json(json.dumps(build_broker(get_settings(), mode).status(), default=str))


@app.command("halt")
def halt(
    mode: str = typer.Option("alpaca", help="alpaca | paper"),
    reason: str = typer.Option("manual_stop"),
) -> None:
    from advisor.execution.autopilot import build_broker

    console.print_json(json.dumps(build_broker(get_settings(), mode).halt(reason), default=str))


@app.command("resume")
def resume(mode: str = typer.Option("alpaca", help="alpaca | paper")) -> None:
    from advisor.execution.autopilot import build_broker

    console.print_json(json.dumps(build_broker(get_settings(), mode).resume(), default=str))


@app.command("earnings")
def earnings_cmd(refresh: bool = typer.Option(False, help="Ignorar cache")) -> None:
    """Calendario de earnings + ventana de blackout."""
    from advisor.events.earnings import EarningsCalendar

    settings = get_settings()
    symbols = AdvisoryPipeline(settings).market_data.load_universe()
    snap = EarningsCalendar(settings).snapshot(
        [s.ticker for s in symbols], use_cache=not refresh
    )
    rows = [v.to_dict() for v in snap.values()]
    rows = sorted(
        rows,
        key=lambda r: (
            999 if r["days_to_earnings"] is None else r["days_to_earnings"]
        ),
    )
    console.print(
        f"[bold]Earnings[/bold] blackout −{settings.earnings_blackout_before}d / "
        f"+{settings.earnings_blackout_after}d"
    )
    for r in rows:
        flag = "[red]BLACKOUT[/red]" if r["in_blackout"] else "[green]ok[/green]"
        dte = r["days_to_earnings"]
        dte_s = "n/a" if dte is None else f"{dte:+.1f}d"
        console.print(f"  {r['ticker']:<6} {flag}  dte={dte_s}  {r.get('blackout_reason','')}")


@app.command("news")
def news_cmd(refresh: bool = typer.Option(False, help="Ignorar cache")) -> None:
    """Pulso de noticias mundiales que afectan acciones/bolsa."""
    from advisor.news.engine import NewsEngine

    settings = get_settings()
    symbols = AdvisoryPipeline(settings).market_data.load_universe()
    pulse = NewsEngine(settings).pulse(symbols, use_cache=not refresh)
    console.print(
        f"[bold]News pulse[/bold] sent={pulse.market_sentiment:+.2f} "
        f"urg={pulse.market_urgency:.2f} bias={pulse.regime_bias:+.2f} "
        f"({pulse.n_headlines} headlines / {pulse.sources_ok} sources)"
    )
    for n in pulse.notes:
        console.print(f"- {n}")
    for h in pulse.headlines[:10]:
        console.print(f"  • [{h['sentiment']:+.2f}] {h['title'][:120]}")
    if pulse.by_sector:
        console.print_json(json.dumps({"by_sector": pulse.by_sector, "by_ticker": pulse.by_ticker}, default=str))


@app.command("backtest")
def backtest(
    lookback: int = typer.Option(756, help="Días de historia a descargar"),
    train: int = typer.Option(252, help="Barras mínimas in-sample antes de OOS"),
    step: int = typer.Option(10, help="Días entre rebalances"),
    horizon: int = typer.Option(10, help="Horizonte de hold"),
    max_positions: int = typer.Option(3, help="Máx posiciones por fold"),
    save: bool = typer.Option(True, help="Guardar JSON en data/"),
) -> None:
    """Walk-forward out-of-sample con costos round-trip."""
    from advisor.backtest.walk_forward import WalkForwardBacktester

    console.print("[cyan]Corriendo walk-forward… esto puede tardar 1–3 min[/cyan]")
    settings = get_settings()
    result = WalkForwardBacktester(settings).run(
        lookback_days=lookback,
        train_bars=train,
        step_days=step,
        horizon_days=horizon,
        max_positions=max_positions,
    )
    summary = {
        "n_rebalances": result.n_rebalances,
        "n_trades": result.n_trades,
        "hit_rate": result.hit_rate,
        "avg_gross": result.avg_gross,
        "avg_net": result.avg_net,
        "expectancy_net": result.expectancy_net,
        "profit_factor": result.profit_factor,
        "sharpe_ann": result.sharpe_ann,
        "max_drawdown": result.max_drawdown,
        "total_return": result.total_return,
        "benchmark_return": result.benchmark_return,
        "excess_return": result.excess_return,
        "cash_rebalances": result.cash_rebalances,
        "round_trip_cost_pct": result.round_trip_cost_pct,
        "by_regime": result.by_regime,
    }
    console.print("\n[bold]Walk-forward OOS[/bold]")
    console.print_json(json.dumps(summary, default=str))
    edge_style = "green" if result.expectancy_net > 0 else "red"
    console.print(
        f"\nExpectancy neta/trade: [{edge_style}]{result.expectancy_net:.2%}[/{edge_style}] | "
        f"Sharpe: {result.sharpe_ann:.2f} | MaxDD: {result.max_drawdown:.2%} | "
        f"Excess vs SPY: {result.excess_return:.2%}"
    )
    if save:
        path = settings.data_dir / "backtest_walk_forward.json"
        path.write_text(json.dumps(result.to_dict(), indent=2, default=str))
        console.print(f"[dim]Guardado: {path}[/dim]")


if __name__ == "__main__":
    app()
