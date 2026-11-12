from __future__ import annotations

from pathlib import Path

import typer

import fm27lab
from fm27lab.config import Settings
from fm27lab.sidecar import run

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def version() -> None:
    """Print the sidecar version and API name."""
    typer.echo(f"{fm27lab.__version__} {fm27lab.API_VERSION}")


@app.command()
def serve(
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Data directory"),
    engine_root: Path | None = typer.Option(None, "--engine-root", help="Engine workspace"),
    host: str | None = typer.Option(None, "--host", help="Loopback host"),
    port: int | None = typer.Option(None, "--port", help="Port; 0 selects a free port"),
    token: str | None = typer.Option(None, "--token", help="Bearer token; generated when omitted"),
    dev: bool | None = typer.Option(None, "--dev/--no-dev", help="Allow the Vite development origin"),
) -> None:
    """Run the local HTTP sidecar until shutdown."""
    base = Settings.from_env()
    settings = Settings.create(
        data_dir=data_dir or base.data_dir,
        engine_root=engine_root or base.engine_root,
        token=token or base.token,
        host=base.host if host is None else host,
        port=base.port if port is None else port,
        dev=base.dev if dev is None else dev,
    )
    raise typer.Exit(run(settings))


def main() -> None:
    app()
