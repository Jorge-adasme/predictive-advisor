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
    console.print_json(json.dumps(status.__dict__, default=str))


@app.command("autopilot")
def autopilot(
    once: bool = typer.Option(True, help="Ejecutar un ciclo y salir"),
    top: int = typer.Option(8, help="Ideas a evaluar"),
) -> None:
    """Ejecuta inversiones automáticamente en modo PAPER con risk gates."""
    from advisor.execution.autopilot import Autopilot

    result = Autopilot(mode="paper").run_once(top_n=top)
    console.print(f"[bold]{result.message}[/bold]")
    console.print_json(
        json.dumps(
            {
                "ts": result.ts,
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
def portfolio() -> None:
    """Estado del portafolio paper."""
    from advisor.execution.paper_broker import PaperBroker

    console.print_json(json.dumps(PaperBroker(get_settings()).status(), default=str))


@app.command("halt")
def halt(reason: str = typer.Option("manual_stop")) -> None:
    from advisor.execution.paper_broker import PaperBroker

    console.print_json(json.dumps(PaperBroker(get_settings()).halt(reason), default=str))


@app.command("resume")
def resume() -> None:
    from advisor.execution.paper_broker import PaperBroker

    console.print_json(json.dumps(PaperBroker(get_settings()).resume(), default=str))


if __name__ == "__main__":
    app()
