from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from .android import AndroidDriver, AndroidError
from .reports import generate_html_report, generate_junit_xml
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
    disable_animations: Annotated[
        bool,
        typer.Option(
            "--disable-animations",
            help="Desativa animações do Android via ADB antes da execução.",
        ),
    ] = False,
    record: Annotated[
        bool,
        typer.Option(
            "--record",
            "-r",
            help="Grava o vídeo da execução do fluxo e salva em artifacts/.",
        ),
    ] = False,
    report_junit: Annotated[
        Path | None,
        typer.Option(
            "--report-junit",
            help="Caminho para gerar o relatório JUnit XML para CI/CD.",
        ),
    ] = None,
    report_html: Annotated[
        Path | None,
        typer.Option(
            "--report-html",
            help="Caminho para gerar o relatório HTML visual e interativo.",
        ),
    ] = None,
    report: Annotated[
        bool,
        typer.Option(
            "--report",
            help="Ativa a geração de relatórios HTML e JUnit XML em artifacts/.",
        ),
    ] = False,
    env: Annotated[
        list[str] | None,
        typer.Option(
            "--env",
            "-e",
            help="Variável de ambiente no formato CHAVE=VALOR (pode repetir).",
        ),
    ] = None,
) -> None:
    """Executa um fluxo YAML."""
    driver: AndroidDriver = ctx.obj["driver"]
    if disable_animations and hasattr(driver, "disable_animations"):
        typer.echo("Desativando animações do Android via ADB...")
        driver.disable_animations()

    if report:
        report_html = report_html or Path("artifacts/report.html")
        report_junit = report_junit or Path("artifacts/report.xml")

    cli_env: dict[str, str] = {}
    if env:
        for item in env:
            if "=" in item:
                k, v = item.split("=", 1)
                cli_env[k.strip()] = v.strip()
            else:
                cli_env[item.strip()] = os.environ.get(item.strip(), "")

    runner = FlowRunner(driver, env=cli_env, echo=typer.echo)
    try:
        result = runner.run(flow, record=record)
    except (AndroidError, FlowError) as exc:
        typer.echo(f"Erro: {exc}", err=True)
        raise typer.Exit(1) from exc

    if report_junit:
        generate_junit_xml(result, report_junit)
        typer.echo(f"Relatório JUnit XML gerado em: {report_junit}")
    if report_html:
        generate_html_report(result, report_html)
        typer.echo(f"Relatório HTML interativo gerado em: {report_html}")

    raise typer.Exit(0 if result.ok else 1)


if __name__ == "__main__":
    app()
