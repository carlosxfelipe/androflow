from pathlib import Path
from unittest.mock import MagicMock

from typer.testing import CliRunner

from androflow.cli import app
from androflow.runner import FlowResult

runner = CliRunner()


def test_cli_test_with_env_and_disable_animations_flags(tmp_path: Path, monkeypatch):
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text("appId: com.demo\n---\n- sleep: 100\n")

    mock_driver = MagicMock()
    mock_run = MagicMock(return_value=FlowResult(path=flow_file, total=1))

    monkeypatch.setattr("androflow.cli.AndroidDriver", lambda serial=None: mock_driver)
    monkeypatch.setattr("androflow.cli.FlowRunner.run", mock_run)

    result = runner.invoke(
        app,
        [
            "test",
            str(flow_file),
            "--disable-animations",
            "--env",
            "USER_EMAIL=test@example.com",
            "-e",
            "FOO=bar",
        ],
    )
    assert result.exit_code == 0
    mock_driver.disable_animations.assert_called_once()
    mock_run.assert_called_once()


def test_cli_test_with_record_and_reports(tmp_path: Path, monkeypatch):
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text("appId: com.demo\n---\n- sleep: 100\n")

    mock_driver = MagicMock()
    mock_run = MagicMock(return_value=FlowResult(path=flow_file, total=1))
    mock_junit = MagicMock()
    mock_html = MagicMock()

    monkeypatch.setattr("androflow.cli.AndroidDriver", lambda serial=None: mock_driver)
    monkeypatch.setattr("androflow.cli.FlowRunner.run", mock_run)
    monkeypatch.setattr("androflow.cli.generate_junit_xml", mock_junit)
    monkeypatch.setattr("androflow.cli.generate_html_report", mock_html)

    junit_file = tmp_path / "out.xml"
    html_file = tmp_path / "out.html"

    result = runner.invoke(
        app,
        [
            "test",
            str(flow_file),
            "--record",
            "--report-junit",
            str(junit_file),
            "--report-html",
            str(html_file),
        ],
    )
    assert result.exit_code == 0
    mock_run.assert_called_once_with(flow_file, record=True)
    mock_junit.assert_called_once()
    mock_html.assert_called_once()


def test_cli_test_multiple_flows_and_directory(tmp_path: Path, monkeypatch):
    flow1 = tmp_path / "flow1.yaml"
    flow1.write_text("appId: com.demo\n---\n- sleep: 100\n")
    flow2 = tmp_path / "flow2.yaml"
    flow2.write_text("appId: com.demo\n---\n- sleep: 100\n")

    mock_driver = MagicMock()
    mock_run = MagicMock(return_value=FlowResult(path=flow1, total=1))

    monkeypatch.setattr("androflow.cli.AndroidDriver", lambda serial=None: mock_driver)
    monkeypatch.setattr("androflow.cli.FlowRunner.run", mock_run)

    # Testa passando múltiplos arquivos
    result = runner.invoke(app, ["test", str(flow1), str(flow2)])
    assert result.exit_code == 0
    assert mock_run.call_count == 2
    assert "Resumo da Suite: 2/2 flow(s)" in result.stdout

    mock_run.reset_mock()

    # Testa passando o diretório
    result_dir = runner.invoke(app, ["test", str(tmp_path)])
    assert result_dir.exit_code == 0
    assert mock_run.call_count == 2
    assert "Resumo da Suite: 2/2 flow(s)" in result_dir.stdout
