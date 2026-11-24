from pathlib import Path

import typer

from .config import load_config
from .pipeline import run_pipeline

app = typer.Typer(no_args_is_help=True, help="Local arXiv analysis and archiving")


@app.callback()
def main():
    """Process papers locally."""


@app.command()
def run(
    arxiv_url_or_id: str,
    no_zotero: bool = typer.Option(False, "--no-zotero"),
    no_obsidian: bool = typer.Option(False, "--no-obsidian"),
    config: Path = Path("config.yaml"),
):
    """Analyze one paper and export its results."""
    try:
        run_pipeline(
            arxiv_url_or_id,
            load_config(config),
            obsidian=not no_obsidian,
            zotero=not no_zotero,
            log=typer.echo,
        )
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command()
def poll(limit: int = typer.Option(3, min=1), config: Path = Path("config.yaml")):
    """Process a bounded batch of pending Supabase tasks."""
    from .supabase_queue import poll_queue

    try:
        result = poll_queue(load_config(config), limit, log=typer.echo)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    if result.failed:
        raise typer.Exit(1)


@app.command()
def gui(config: Path = Path("config.yaml")):
    """Open the desktop runner and settings."""
    from .gui import launch_gui

    try:
        launch_gui(config)
    except Exception as exc:
        typer.echo(f"GUI error: {exc}", err=True)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()
