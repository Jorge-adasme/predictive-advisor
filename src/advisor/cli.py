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


def _print_rec_table(title: str, rows: list[dict]) -> None:
    table = Table(title=title)
    table.add_column("#", justify="right")
    table.add_column("Ticker")
    table.add_column("Acción")
    table.add_column("Prob↑", justify="right")
    table.add_column("E[r]", justify="right")
    table.add_column("News", justify="right")
    table.add_column("Edge", justify="right")
    table.add_column("Motivo")
    for rec in rows:
        pred = rec["prediction"]
        plan = rec["plan"]
        nf = float((pred.get("factors") or {}).get("news_factor") or 0)
        why = plan.get("invalidation") or ""
        if pred.get("risks"):
            why = pred["risks"][0]
        table.add_row(
            str(rec["rank"]),
            pred["ticker"],
            plan["action"],
            f"{pred['probability_up']:.0%}",
            f"{pred['expected_return']:.2%}",
            f"{nf:+.2f}",
            f"{plan['edge_net_pct']:.2%}",
            why[:48],
        )
    console.print(table)


@app.command("analyze")
def analyze(top: int = typer.Option(8, help="Cantidad por lista (comprar / evitar)")) -> None:
    """Analiza mercado: qué comprar Y qué NO invertir."""
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

    news = result.get("news") or {}
    headlines = market.get("news_headlines") or news.get("headlines") or []
    stories = news.get("ticker_stories") or []
    lookback = news.get("lookback_days", 14)
    console.print(
        f"\n[bold]Noticias (últimos {lookback}d)[/bold] sent={market.get('news_sentiment', news.get('market_sentiment', 0)):+.2f} | "
        f"urgencia={market.get('news_urgency', news.get('market_urgency', 0)):.2f} | "
        f"titulares={len(headlines)} / total={news.get('n_headlines', len(headlines))}"
    )
    if stories:
        console.print("[bold]Impacto por acción[/bold]")
        for s in stories[:8]:
            gov = " ⚠️gov" if s.get("governance") else ""
            console.print(
                f"  {s.get('ticker')}: factor={s.get('factor', 0):+.2f}{gov} · "
                f"{str(s.get('headline', ''))[:90]}"
            )
    if not headlines:
        console.print("[yellow]Sin titulares — prueba: advisor news --refresh[/yellow]")
    for h in headlines[:10]:
        age = h.get("age_label") or ""
        console.print(f"  • [{h.get('sentiment', 0):+.2f}] {age} {h.get('title', '')[:110]}")

    if result.get("message"):
        style = "green" if result.get("actionable") else "yellow"
        console.print(f"\n[{style}]{result['message']}[/{style}]")

    buys = result.get("actionable") or []
    opps = result.get("opportunities") or result.get("recommendations") or []
    avoids = result.get("do_not_invest") or []
    if opps:
        _print_rec_table("Oportunidades (buy + watch)", opps)
    if buys and buys != opps:
        _print_rec_table("Listas para ejecutar (BUY)", buys)
    if not opps:
        console.print("\n[yellow]Sin oportunidades hoy.[/yellow]")

    if avoids:
        _print_rec_table("Para NO invertir (evitar)", avoids)
        console.print("\n[bold]Por qué evitar (top)[/bold]")
        for rec in avoids[:5]:
            pred = rec["prediction"]
            plan = rec["plan"]
            console.print(f"[red]{pred['ticker']}[/red] — {plan.get('invalidation', '')}")
            for risk in (pred.get("risks") or [])[:2]:
                console.print(f"  ! {risk}")
    else:
        console.print("\n[dim]Lista de evitar vacía.[/dim]")

    ai_meta = result.get("ai") or {}
    ai_rows = result.get("ai_decisions") or []
    if ai_meta.get("enabled") and ai_rows:
        console.print(
            f"\n[bold]Decisión IA[/bold] provider={ai_meta.get('provider')} "
            f"gate_autopilot={ai_meta.get('gate_autopilot')}"
        )
        for d in ai_rows[:10]:
            mark = {
                "buy": "[green]BUY[/green]",
                "hold": "[yellow]HOLD[/yellow]",
                "avoid": "[red]AVOID[/red]",
            }.get(d.get("action"), d.get("action"))
            appr = "✓ ejecuta" if d.get("approve_trade") else "✗ no ejecuta"
            console.print(
                f"  {d.get('ticker')}: {mark} conv={float(d.get('conviction') or 0):.0%} "
                f"{appr} — {d.get('summary', '')[:90]}"
            )

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
    pool = result.get("recommendations") or []
    pool = pool + (result.get("do_not_invest") or []) + (result.get("actionable") or [])
    match = next(
        (
            Recommendation.model_validate(item)
            for item in pool
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


@app.command("system-status")
def system_status_cmd(mode: str = typer.Option("alpaca", help="alpaca|paper")) -> None:
    """Checklist de confianza: broker, IA, riesgo, kill-switch, auditoría."""
    from advisor.execution.autopilot import build_broker
    from advisor.execution.paper_broker import PaperBroker
    from advisor.portfolio.audit import SystemStatus

    settings = get_settings()
    try:
        portfolio = build_broker(settings, mode).status()
    except Exception:
        portfolio = PaperBroker(settings).status()
    status = SystemStatus(settings).build(portfolio)
    ready = "[green]LISTO[/green]" if status["ready"] else "[red]DEGRADADO[/red]"
    console.print(f"[bold]Sistema[/bold] v{status['version']} · {ready} · {status['mode']}")
    console.print(status["disclaimer"])
    for c in status["checks"]:
        mark = "[green]OK[/green]" if c["ok"] else "[red]FAIL[/red]"
        console.print(f"  {mark} {c['name']}: {c['detail']}")


@app.command("audit")
def audit_cmd(
    limit: int = typer.Option(30, help="Eventos a mostrar"),
    event: Optional[str] = typer.Option(None, help="Filtrar por tipo"),
) -> None:
    """Bitácora de auditoría (analyze / autopilot / halt)."""
    from advisor.portfolio.audit import AuditLog

    rows = list(reversed(AuditLog().list_events(limit=limit, event=event)))
    if not rows:
        console.print("[yellow]Sin eventos de auditoría todavía.[/yellow]")
        return
    for r in rows:
        console.print(
            f"[cyan]{r.get('event')}[/cyan] {r.get('ts', '')[:19]} · "
            f"{r.get('summary', '')[:100]}"
        )


@app.command("performance")
def performance_cmd(mode: str = typer.Option("alpaca", help="alpaca|paper")) -> None:
    """Win rate, expectancy, exposición y presupuesto de pérdida diaria."""
    from advisor.execution.autopilot import build_broker
    from advisor.execution.paper_broker import PaperBroker
    from advisor.portfolio.audit import PerformanceStats

    settings = get_settings()
    try:
        portfolio = build_broker(settings, mode).status()
    except Exception:
        portfolio = PaperBroker(settings).status()
    stats = PerformanceStats(settings).from_portfolio(portfolio)
    console.print_json(json.dumps(stats, default=str))


@app.command("ai-decide")
def ai_decide(top: int = typer.Option(10, help="Ideas a evaluar con IA")) -> None:
    """Capa de IA (OFF por defecto). Reactivar con ADVISOR_AI_ENABLED=true."""
    if not get_settings().ai_enabled:
        console.print(
            "[yellow]IA desactivada[/yellow] (ADVISOR_AI_ENABLED=false). "
            "Hoy solo corre el motor cuantitativo."
        )
        raise typer.Exit(code=0)
    result = AdvisoryPipeline().analyze(top_n=top)
    if result.get("error"):
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)
    console.print_json(
        json.dumps(
            {
                "ai": result.get("ai"),
                "decisions": result.get("ai_decisions"),
                "message": result.get("message"),
            },
            default=str,
        )
    )


@app.command("news")
def news_cmd(refresh: bool = typer.Option(False, help="Ignorar cache")) -> None:
    """Pulso de noticias mundiales que afectan acciones/bolsa."""
    from advisor.news.engine import NewsEngine

    settings = get_settings()
    symbols = AdvisoryPipeline(settings).market_data.load_universe()
    pulse = NewsEngine(settings).pulse(symbols, use_cache=not refresh)
    console.print(
        f"[bold]News pulse[/bold] ventana={pulse.lookback_days}d "
        f"sent={pulse.market_sentiment:+.2f} "
        f"urg={pulse.market_urgency:.2f} bias={pulse.regime_bias:+.2f} "
        f"({pulse.n_headlines} headlines / {pulse.sources_ok} sources)"
    )
    for n in pulse.notes:
        console.print(f"- {n}")
    if pulse.ticker_stories:
        console.print("[bold]Impacto por acción[/bold]")
        for s in pulse.ticker_stories[:10]:
            gov = " ⚠️gov" if s.get("governance") else ""
            console.print(
                f"  {s['ticker']}: {s['factor']:+.2f}{gov} · {str(s.get('headline',''))[:90]}"
            )
    for h in pulse.headlines[:10]:
        age = h.get("age_label") or ""
        console.print(f"  • [{h['sentiment']:+.2f}] {age} {h['title'][:110]}")
    if pulse.by_sector:
        console.print_json(
            json.dumps({"by_sector": pulse.by_sector, "by_ticker": pulse.by_ticker}, default=str)
        )


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
