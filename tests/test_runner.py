import itertools
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from androflow.android import AndroidError
from androflow.runner import FlowError, FlowRunner

LOGIN_SCREEN = (
    '<hierarchy><node text="Entrar" resource-id="com.demo:id/login" '
    'bounds="[10,20][110,70]" clickable="true" /></hierarchy>'
)
EMPTY_SCREEN = "<hierarchy />"


class FakeDriver:
    def __init__(self, screens=None):
        self.actions = []
        # Cada dump consome uma tela; a última se repete indefinidamente.
        # Um item que seja uma exceção é lançado em vez de retornado.
        self.screens = list(screens or [EMPTY_SCREEN])

    def launch_app(self, app_id):
        self.actions.append(("launch_app", app_id))

    def stop_app(self, app_id):
        self.actions.append(("stop_app", app_id))

    def tap(self, x, y):
        self.actions.append(("tap", x, y))

    def type_text(self, value):
        self.actions.append(("type_text", value))

    def back(self):
        self.actions.append(("back",))

    def wait(self, seconds):
        self.actions.append(("wait", seconds))

    def dump_hierarchy(self):
        screen = self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]
        if isinstance(screen, Exception):
            raise screen
        return ET.fromstring(screen)

    def screenshot(self, destination):
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        self.actions.append(("screenshot", path))
        return path

    def clear_app(self, app_id):
        self.actions.append(("clear_app", app_id))

    def press_key(self, key):
        self.actions.append(("press_key", key))

    def erase_text(self, characters):
        self.actions.append(("erase_text", characters))

    def hide_keyboard(self):
        self.actions.append(("hide_keyboard",))

    def scroll(self, direction="DOWN"):
        self.actions.append(("scroll", direction))

    def swipe(self, start_x, start_y, end_x, end_y, duration_ms=400):
        self.actions.append(("swipe", start_x, start_y, end_x, end_y, duration_ms))

    def open_link(self, url):
        self.actions.append(("open_link", url))

    def screen_size(self):
        return (1000, 2000)


def write_flow(tmp_path: Path, body: str, header: str = "appId: com.demo.app"):
    path = tmp_path / "flow.yaml"
    path.write_text(f"{header}\n---\n{body}", encoding="utf-8")
    return path


def make_runner(driver: FakeDriver, tmp_path: Path) -> FlowRunner:
    return FlowRunner(
        driver,
        default_timeout=0,
        artifacts_dir=tmp_path / "artifacts",
        poll_interval=0,
        echo=lambda _message: None,
    )


# ----------------------------------------------------------------------
# Carregamento / validação
# ----------------------------------------------------------------------


def test_load_maestro_style_yaml(tmp_path: Path):
    path = tmp_path / "flow.yaml"
    path.write_text(
        "appId: com.demo.app\n---\n- launchApp\n- sleep: 0\n", encoding="utf-8"
    )
    runner = FlowRunner(FakeDriver())
    config, steps = runner.load_flow(path)
    assert config["appId"] == "com.demo.app"
    assert steps == [{"launchApp": None}, {"sleep": 0}]


def test_rejects_bad_yaml_shape(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text("hello: world\n", encoding="utf-8")
    with pytest.raises(FlowError):
        FlowRunner(FakeDriver()).load_flow(path)


def test_unknown_command_fails_before_running_any_step(tmp_path: Path):
    driver = FakeDriver()
    path = write_flow(tmp_path, "- launchApp\n- tapOnn: Entrar\n")
    with pytest.raises(FlowError, match="Etapa 2.*tapOnn"):
        make_runner(driver, tmp_path).run(path)
    assert driver.actions == []


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("- inputText\n", "inputText"),
        ("- sleep\n", "sleep"),
        ("- takeScreenshot\n", "takeScreenshot"),
        ("- sleep: -1\n", "sleep"),
        ("- tapOn:\n    txt: Entrar\n", "txt"),
        ("- tapOn:\n    point: [1]\n", "point"),
        ("- waitFor:\n    text: X\n    timeout: abc\n", "timeout"),
        ("- inputText: yes\n", "inputText"),
        ('- launchApp:\n    stopApp: "sim"\n', "stopApp"),
    ],
)
def test_rejects_invalid_step_values(tmp_path: Path, body: str, match: str):
    with pytest.raises(FlowError, match=match):
        make_runner(FakeDriver(), tmp_path).load_flow(write_flow(tmp_path, body))


def test_rejects_launch_app_without_app_id(tmp_path: Path):
    path = write_flow(tmp_path, "- launchApp\n", header="name: demo")
    with pytest.raises(FlowError, match="appId"):
        make_runner(FakeDriver(), tmp_path).load_flow(path)


# ----------------------------------------------------------------------
# Execução / relatório
# ----------------------------------------------------------------------


def test_run_counts_passed_failed_and_skipped(tmp_path: Path):
    driver = FakeDriver([LOGIN_SCREEN])
    path = write_flow(tmp_path, "- launchApp\n- tapOn: Sair\n- back\n")
    result = make_runner(driver, tmp_path).run(path)

    assert (result.passed, result.failed, result.skipped) == (1, 1, 1)
    assert not result.ok
    assert result.steps[1].error.startswith("Elemento não encontrado")
    assert ("back",) not in driver.actions


def test_successful_run_is_ok(tmp_path: Path):
    driver = FakeDriver([LOGIN_SCREEN])
    path = write_flow(tmp_path, "- launchApp\n- tapOn: Entrar\n- back\n")
    result = make_runner(driver, tmp_path).run(path)

    assert result.ok
    assert (result.passed, result.failed, result.skipped) == (3, 0, 0)
    assert driver.actions == [
        ("stop_app", "com.demo.app"),
        ("launch_app", "com.demo.app"),
        ("tap", 60, 45),
        ("back",),
    ]


def test_launch_app_without_stop(tmp_path: Path):
    driver = FakeDriver()
    make_runner(driver, tmp_path).execute(
        "launchApp", {"appId": "com.outro.app", "stopApp": False}
    )
    assert driver.actions == [("launch_app", "com.outro.app")]


def test_failure_saves_screenshot_and_hierarchy(tmp_path: Path):
    path = write_flow(tmp_path, "- assertVisible: Sair\n")
    make_runner(FakeDriver([LOGIN_SCREEN]), tmp_path).run(path)

    artifacts = tmp_path / "artifacts"
    assert (artifacts / "flow-falha-01.png").exists()
    xml = (artifacts / "flow-falha-01.xml").read_text(encoding="utf-8")
    assert "Entrar" in xml


# ----------------------------------------------------------------------
# Comandos
# ----------------------------------------------------------------------


def test_tap_on_element_taps_center(tmp_path: Path):
    driver = FakeDriver([LOGIN_SCREEN])
    make_runner(driver, tmp_path).execute("tapOn", {"resourceId": "login"})
    assert driver.actions == [("tap", 60, 45)]


def test_tap_on_point(tmp_path: Path):
    driver = FakeDriver()
    make_runner(driver, tmp_path).execute("tapOn", {"point": [5, 7]})
    assert driver.actions == [("tap", 5, 7)]


def test_selector_from_flow_is_not_mutated(tmp_path: Path):
    value = {"text": "Entrar", "timeout": 0}
    make_runner(FakeDriver([LOGIN_SCREEN]), tmp_path).execute("tapOn", value)
    assert value == {"text": "Entrar", "timeout": 0}


def test_assert_not_visible_waits_until_element_disappears(tmp_path: Path):
    driver = FakeDriver([LOGIN_SCREEN, LOGIN_SCREEN, EMPTY_SCREEN])
    runner = make_runner(driver, tmp_path)
    runner.execute("assertNotVisible", {"text": "Entrar", "timeout": 5})


def test_assert_not_visible_fails_if_element_stays(tmp_path: Path):
    runner = make_runner(FakeDriver([LOGIN_SCREEN]), tmp_path)
    with pytest.raises(FlowError, match="não estivesse visível"):
        runner.execute("assertNotVisible", "Entrar")


def test_take_screenshot_goes_to_artifacts_dir(tmp_path: Path):
    driver = FakeDriver()
    make_runner(driver, tmp_path).execute("takeScreenshot", "login")
    assert driver.actions == [("screenshot", tmp_path / "artifacts" / "login.png")]


def test_wait_for_reports_latest_state_instead_of_stale_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Relógio falso: cada consulta avança 1s, permitindo exatamente 2 tentativas.
    ticks = itertools.count()
    monkeypatch.setattr("androflow.runner.time.monotonic", lambda: next(ticks))
    driver = FakeDriver([AndroidError("idle state"), EMPTY_SCREEN])
    runner = make_runner(driver, tmp_path)
    with pytest.raises(FlowError, match="Timeout aguardando"):
        runner.execute("waitFor", {"text": "Entrar", "timeout": 1.5})


def test_wait_for_surfaces_read_error_when_last_attempt_fails(tmp_path: Path):
    driver = FakeDriver([AndroidError("idle state")])
    with pytest.raises(FlowError, match="Falha ao ler a tela: idle state"):
        make_runner(driver, tmp_path).execute("waitFor", "Entrar")


def test_sleep_units_and_seconds(tmp_path: Path):
    driver = FakeDriver()
    runner = make_runner(driver, tmp_path)
    # Segundos puros
    runner.execute("sleep", 2)
    runner.execute("sleep", 0.5)
    # Unidades explícitas
    runner.execute("sleep", "500ms")
    runner.execute("sleep", "3s")
    assert driver.actions == [
        ("wait", 2.0),
        ("wait", 0.5),
        ("wait", 0.5),
        ("wait", 3.0),
    ]


def test_tap_on_percent_and_string_point(tmp_path: Path):
    driver = FakeDriver()
    runner = make_runner(driver, tmp_path)
    # FakeDriver.screen_size() é (1000, 2000)
    runner.execute("tapOn", {"point": "50%,50%"})
    runner.execute("tapOn", {"point": "100, 250"})
    assert driver.actions == [
        ("tap", 500, 1000),
        ("tap", 100, 250),
    ]


def test_press_key_command(tmp_path: Path):
    driver = FakeDriver()
    make_runner(driver, tmp_path).execute("pressKey", "Enter")
    assert driver.actions == [("press_key", "Enter")]


def test_erase_text_command(tmp_path: Path):
    driver = FakeDriver()
    runner = make_runner(driver, tmp_path)
    runner.execute("eraseText")
    runner.execute("eraseText", 12)
    assert driver.actions == [
        ("erase_text", 50),
        ("erase_text", 12),
    ]


def test_scroll_and_swipe_commands(tmp_path: Path):
    driver = FakeDriver()
    runner = make_runner(driver, tmp_path)
    runner.execute("scroll")
    runner.execute("swipe", {"direction": "UP"})
    runner.execute("swipe", {"start": "10%,20%", "end": "30%,40%", "duration": 300})
    assert driver.actions == [
        ("scroll", "DOWN"),
        ("scroll", "UP"),
        ("swipe", 100, 400, 300, 800, 300),
    ]


def test_open_link_and_hide_keyboard(tmp_path: Path):
    driver = FakeDriver()
    runner = make_runner(driver, tmp_path)
    runner.execute("openLink", "https://app.link")
    runner.execute("hideKeyboard")
    assert driver.actions == [
        ("open_link", "https://app.link"),
        ("hide_keyboard",),
    ]


def test_launch_app_clear_state_and_stop_app(tmp_path: Path):
    driver = FakeDriver()
    runner = make_runner(driver, tmp_path)
    runner._app_id = "com.demo.app"
    runner.execute("launchApp", {"clearState": True, "stopApp": True})
    runner.execute("stopApp")
    assert driver.actions == [
        ("clear_app", "com.demo.app"),
        ("stop_app", "com.demo.app"),
        ("launch_app", "com.demo.app"),
        ("stop_app", "com.demo.app"),
    ]


def test_repeat_command(tmp_path: Path):
    driver = FakeDriver()
    runner = make_runner(driver, tmp_path)
    runner.execute(
        "repeat",
        {
            "times": 3,
            "commands": [
                {"pressKey": "Enter"},
            ],
        },
    )
    assert driver.actions == [
        ("press_key", "Enter"),
        ("press_key", "Enter"),
        ("press_key", "Enter"),
    ]
