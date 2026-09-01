"""``na`` command-line interface: generate, analytics, report, serve, verify."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from networkanalysis.config.presets import load_config, save_preset
from networkanalysis.paths import WAREHOUSE_DB

app = typer.Typer(add_completion=False, help="RAN & Transport Isolation module CLI")
console = Console()


@app.command()
def generate(
    preset: str = typer.Option("mixed_realistic", help="preset name or path to a config YAML"),
    sites: int = typer.Option(0, help="override market.n_sites"),
    days: int = typer.Option(0, help="override duration_days"),
    seed: int = typer.Option(0, help="override seed"),
    load_bin_facts: bool = typer.Option(False, help="also load 5-min facts into SQLite (large)"),
):
    """Generate a synthetic dataset and load it into the SQLite warehouse."""
    from networkanalysis.generate import run_generation

    cfg = load_config(preset)
    if sites:
        cfg.market.n_sites = sites
    if days:
        cfg.duration_days = days
    if seed:
        cfg.seed = seed
    console.print(f"[bold]generating[/] preset=[cyan]{cfg.name}[/] "
                  f"sites={cfg.market.n_sites} days={cfg.duration_days} seed={cfg.seed}")
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as p:
        t = p.add_task("starting", total=None)
        res = run_generation(
            cfg, load_bin_facts=load_bin_facts,
            on_progress=lambda s, pct, m: p.update(t, description=f"[{pct:4.0%}] {s}: {m}"),
        )
    console.print("[green]done[/]\n" + res.summary())


@app.command()
def analytics():
    """Run the analytics engine (scoring, attribution, correlation, anomaly, variability, RCA)."""
    from networkanalysis.analytics import run_analytics

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as p:
        t = p.add_task("starting", total=None)
        res = run_analytics(on_progress=lambda s, pct, m: p.update(t, description=f"[{pct:4.0%}] {s}: {m}"))
    console.print("[green]done[/]\n" + res.summary())


@app.command()
def report(fmt: str = typer.Option("html", help="html | pdf | both")):
    """Build the analytics report and the Phase-2 audit list."""
    from networkanalysis.report import build_report

    out = build_report(fmt=fmt)
    for k, v in out.items():
        console.print(f"  {k}: [cyan]{v}[/]")


@app.command()
def presets():
    """List available generation presets."""
    from networkanalysis.config.presets import list_presets

    for n in list_presets():
        console.print(f"  - {n}")


@app.command("save-preset")
def save_preset_cmd(source: str, name: str):
    """Copy/normalise a config YAML into config/presets/<name>.yaml."""
    cfg = load_config(source)
    cfg.name = name
    path = save_preset(cfg, name)
    console.print(f"saved [cyan]{path}[/]")


@app.command()
def counts():
    """Show warehouse table row counts."""
    from networkanalysis.db.database import table_counts

    tbl = Table("table", "rows")
    for k, v in sorted(table_counts().items()):
        if v:
            tbl.add_row(k, f"{v:,}")
    console.print(tbl)


@app.command()
def verify():
    """Verification: generator determinism + ground-truth recovery targets."""
    from networkanalysis.verify import run_verification

    ok = run_verification(console)
    raise typer.Exit(0 if ok else 1)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
    """Start the FastAPI backend (also serves the built dashboard if web/dist exists)."""
    import uvicorn

    uvicorn.run("networkanalysis.api.main:app", host=host, port=port, reload=reload)


@app.command("db-path")
def db_path():
    """Print the warehouse DB path."""
    console.print(str(WAREHOUSE_DB))


if __name__ == "__main__":
    app()
