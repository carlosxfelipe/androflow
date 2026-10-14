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
