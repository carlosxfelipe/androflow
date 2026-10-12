from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .android import AndroidDriver, AndroidError
from .runner import FlowError, FlowRunner

app = typer.Typer(
    name="androflow",
    help="Executa fluxos YAML de teste de UI em um emulador Android via ADB.",
    no_args_is_help=True,
)


@app.callback()
def main(
    ctx: typer.Context,
    serial: Annotated[
        str | None,
        typer.Option("--serial", "-s", help="Serial ADB do emulador/dispositivo."),
    ] = None,
) -> None:
    ctx.obj = {"driver": AndroidDriver(serial=serial)}


@app.command()
def devices(ctx: typer.Context) -> None:
    """Lista os dispositivos disponíveis no ADB."""
    driver: AndroidDriver = ctx.obj["driver"]
    try:
        rows = driver.devices()
    except AndroidError as exc:
        typer.echo(f"Erro: {exc}", err=True)
        raise typer.Exit(2) from exc
    if not rows:
        typer.echo(
            "Nenhum dispositivo encontrado. Inicie o emulador no Android Studio."
        )
        return
    typer.echo("SERIAL\t\tSTATE")
    for serial, state in rows:
        typer.echo(f"{serial}\t{state}")


@app.command("test")
def test_flow(
    ctx: typer.Context,
    flow: Annotated[Path, typer.Argument(help="Caminho do arquivo YAML.")],
) -> None:
    """Executa um fluxo YAML."""
    driver: AndroidDriver = ctx.obj["driver"]
    runner = FlowRunner(driver, echo=typer.echo)
    try:
        result = runner.run(flow)
    except (AndroidError, FlowError) as exc:
        typer.echo(f"Erro: {exc}", err=True)
        raise typer.Exit(1) from exc
    raise typer.Exit(0 if result.ok else 1)


if __name__ == "__main__":
    app()
