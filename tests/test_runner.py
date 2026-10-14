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

    def type_text(self, value, *, transliterate=False):
        if transliterate:
            self.actions.append(("type_text", value, transliterate))
        else:
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

    def disable_animations(self):
        self.actions.append(("disable_animations",))

    def enable_animations(self):
        self.actions.append(("enable_animations",))

    def grant_permission(self, app_id, permission):
        self.actions.append(("grant_permission", app_id, permission))

    def revoke_permission(self, app_id, permission):
        self.actions.append(("revoke_permission", app_id, permission))

    def wake_up_and_unlock(self):
        self.actions.append(("wake_up_and_unlock",))

    def dismiss_system_dialogs(self):
        self.actions.append(("dismiss_system_dialogs",))

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
        ("- scrollUntilVisible\n", "scrollUntilVisible"),
        ("- scrollUntilVisible:\n    direction: INVALID\n    text: X\n", "direction"),
        ("- scrollUntilVisible:\n    maxScrolls: 0\n    text: X\n", "maxScrolls"),
        ("- disableAnimations: 123\n", "disableAnimations"),
        ("- grantPermissions\n", "grantPermissions"),
        ("- grantPermissions: 123\n", "grantPermissions"),
        ("- wakeUp: 123\n", "wakeUp"),
        ("- dismissSystemDialogs: 123\n", "dismissSystemDialogs"),
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
        runner.execute("waitFor", {"text": "Entrar", "timeout": 1500})


def test_wait_for_surfaces_read_error_when_last_attempt_fails(tmp_path: Path):
    driver = FakeDriver([AndroidError("idle state")])
    with pytest.raises(FlowError, match="Falha ao ler a tela: idle state"):
        make_runner(driver, tmp_path).execute("waitFor", "Entrar")


def test_sleep_units_and_milliseconds(tmp_path: Path):
    driver = FakeDriver()
    runner = make_runner(driver, tmp_path)
    # Milissegundos puros (padrão Maestro)
    runner.execute("sleep", 2000)
    runner.execute("sleep", 500)
    # Unidades explícitas
    runner.execute("sleep", "500ms")
    runner.execute("sleep", "3s")
    assert driver.actions == [
        ("wait", 2.0),
        ("wait", 0.5),
        ("wait", 0.5),
        ("wait", 3.0),
    ]


def test_parse_duration_milliseconds_and_units():
    # Padrão numérico é milissegundos
    assert FlowRunner._parse_duration(2000) == 2.0
    assert FlowRunner._parse_duration(500) == 0.5
    assert FlowRunner._parse_duration(0) == 0.0
    assert FlowRunner._parse_duration("3000") == 3.0
    # Unidades explícitas
    assert FlowRunner._parse_duration("500ms") == 0.5
    assert FlowRunner._parse_duration("2s") == 2.0
    assert FlowRunner._parse_duration("1.5s") == 1.5
    # Inválidos
    with pytest.raises(FlowError, match="milissegundos"):
        FlowRunner._parse_duration(-1)
    with pytest.raises(FlowError, match="ms"):
        FlowRunner._parse_duration(True)
    with pytest.raises(FlowError, match="com 's' inválido"):
        FlowRunner._parse_duration("-5s")
    with pytest.raises(FlowError, match="com 'ms' inválido"):
        FlowRunner._parse_duration("-500ms")


def test_timeout_with_explicit_units_in_selector(tmp_path: Path):
    driver = FakeDriver([LOGIN_SCREEN, LOGIN_SCREEN, LOGIN_SCREEN])
    runner = make_runner(driver, tmp_path)
    # Suporta timeout em milissegundos ou com unidade
    runner.execute("waitFor", {"text": "Entrar", "timeout": 5000})
    runner.execute("waitFor", {"text": "Entrar", "timeout": "5s"})
    runner.execute("waitFor", {"text": "Entrar", "timeout": "500ms"})


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


def test_input_text_with_selector_auto_focus(tmp_path: Path):
    driver = FakeDriver([LOGIN_SCREEN])
    runner = make_runner(driver, tmp_path)
    runner.execute(
        "inputText",
        {
            "id": "login",
            "text": "carlos@exemplo.com",
        },
    )
    assert driver.actions == [
        ("tap", 60, 45),
        ("wait", 0.3),
        ("type_text", "carlos@exemplo.com"),
    ]


def test_input_text_with_selector_value_key(tmp_path: Path):
    driver = FakeDriver([LOGIN_SCREEN])
    runner = make_runner(driver, tmp_path)
    runner.execute(
        "inputText",
        {
            "resourceId": "login",
            "value": "12345",
        },
    )
    assert driver.actions == [
        ("tap", 60, 45),
        ("wait", 0.3),
        ("type_text", "12345"),
    ]


def test_input_text_with_invalid_selector_raises(tmp_path: Path):
    driver = FakeDriver()
    runner = make_runner(driver, tmp_path)
    with pytest.raises(FlowError, match="informe o texto"):
        runner.execute("inputText", {"id": "login"})
    with pytest.raises(FlowError, match="desconhecida"):
        runner.execute("inputText", {"text": "abc", "chave_invalida": 123})


def test_input_text_with_simple_dict(tmp_path: Path):
    driver = FakeDriver()
    runner = make_runner(driver, tmp_path)
    runner.execute("inputText", {"text": "apenas_texto"})
    assert driver.actions == [("type_text", "apenas_texto")]


def test_input_text_transliterate_option(tmp_path: Path):
    driver = FakeDriver()
    runner = make_runner(driver, tmp_path)
    runner.execute(
        "inputText",
        {
            "text": "Cartão de Crédito",
            "transliterate": True,
        },
    )
    assert driver.actions == [("type_text", "Cartão de Crédito", True)]


def test_input_text_transliterate_invalid_type_raises(tmp_path: Path):
    driver = FakeDriver()
    runner = make_runner(driver, tmp_path)
    with pytest.raises(FlowError, match="booleano"):
        runner.execute("inputText", {"text": "abc", "transliterate": "sim"})


def test_input_text_flow_header_transliterate_default(tmp_path: Path):
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text(
        "appId: com.demo\ntransliterate: true\n---\n- inputText: 'Cartão'\n"
    )
    driver = FakeDriver()
    runner = FlowRunner(driver, artifacts_dir=tmp_path / "artifacts")
    res = runner.run(flow_file)
    assert res.ok
    assert driver.actions == [("type_text", "Cartão", True)]


def test_scroll_until_visible_already_visible(tmp_path: Path):
    driver = FakeDriver([LOGIN_SCREEN])
    runner = make_runner(driver, tmp_path)
    runner.execute("scrollUntilVisible", "Entrar")
    assert not any(action[0] == "scroll" for action in driver.actions)


def test_scroll_until_visible_after_scrolling(tmp_path: Path):
    driver = FakeDriver([EMPTY_SCREEN, EMPTY_SCREEN, LOGIN_SCREEN])
    runner = make_runner(driver, tmp_path)
    runner.execute(
        "scrollUntilVisible",
        {"text": "Entrar", "direction": "DOWN", "maxScrolls": 5},
    )
    scroll_count = sum(1 for a in driver.actions if a == ("scroll", "DOWN"))
    assert scroll_count == 2


def test_scroll_until_visible_with_element_dict(tmp_path: Path):
    driver = FakeDriver([EMPTY_SCREEN, LOGIN_SCREEN])
    runner = make_runner(driver, tmp_path)
    runner.execute(
        "scrollUntilVisible",
        {"element": {"id": "login"}, "direction": "UP", "maxScrolls": 3},
    )
    assert ("scroll", "UP") in driver.actions


def test_scroll_until_visible_fails_when_not_found(tmp_path: Path):
    driver = FakeDriver([EMPTY_SCREEN])
    runner = make_runner(driver, tmp_path)
    with pytest.raises(FlowError, match="não encontrado após 2 rolagens"):
        runner.execute(
            "scrollUntilVisible",
            {"text": "Inexistente", "maxScrolls": 2},
        )


def test_disable_animations_flow_and_steps(tmp_path: Path):
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text(
        "appId: com.demo\ndisableAnimations: true\n---\n"
        "- enableAnimations\n- disableAnimations\n"
    )
    driver = FakeDriver()
    runner = FlowRunner(driver, artifacts_dir=tmp_path / "artifacts")
    res = runner.run(flow_file)
    assert res.ok
    assert driver.actions == [
        ("disable_animations",),
        ("enable_animations",),
        ("disable_animations",),
    ]


def test_env_interpolation_in_flow(tmp_path: Path):
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text(
        "appId: ${APP_PKG}\n"
        "env:\n"
        "  BASE_URL: https://example.com\n"
        "  DEFAULT_USER: convidado\n"
        "---\n"
        "- launchApp\n"
        "- inputText: ${USER:-${DEFAULT_USER}}\n"
        "- inputText: ${PASSWORD:segredo123}\n"
        "- openLink: ${BASE_URL}/login\n"
    )
    driver = FakeDriver()
    runner = FlowRunner(
        driver,
        env={"APP_PKG": "com.exemplo.app", "USER": "carlos"},
        artifacts_dir=tmp_path / "artifacts",
    )
    config, steps = runner.load_flow(flow_file)
    assert config["appId"] == "com.exemplo.app"
    assert steps[1] == {"inputText": "carlos"}
    assert steps[2] == {"inputText": "segredo123"}
    assert steps[3] == {"openLink": "https://example.com/login"}


def test_env_missing_variable_raises(tmp_path: Path):
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text("appId: com.demo\n---\n- inputText: ${INEXISTENTE}\n")
    driver = FakeDriver()
    runner = FlowRunner(driver, artifacts_dir=tmp_path / "artifacts")
    with pytest.raises(
        FlowError, match="Variável de ambiente 'INEXISTENTE' não definida"
    ):
        runner.load_flow(flow_file)


def test_env_file_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# Comentário\nAPP_NAME=meu_app\nAPI_KEY='12345'\nSECRET=\"token\"\n"
    )
    monkeypatch.chdir(tmp_path)
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text("appId: com.${APP_NAME}\n---\n- inputText: ${API_KEY}\n")
    driver = FakeDriver()
    runner = FlowRunner(driver, artifacts_dir=tmp_path / "artifacts")
    config, steps = runner.load_flow(flow_file)
    assert config["appId"] == "com.meu_app"
    assert steps[0] == {"inputText": "12345"}


def test_launch_app_with_permissions_and_wake_up(tmp_path: Path):
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text(
        "appId: com.demo\n"
        "wakeUp: true\n"
        "permissions:\n"
        "  - POST_NOTIFICATIONS\n"
        "---\n"
        "- launchApp\n"
    )
    driver = FakeDriver()
    runner = FlowRunner(driver, artifacts_dir=tmp_path / "artifacts")
    res = runner.run(flow_file)
    assert res.ok
    assert driver.actions == [
        ("wake_up_and_unlock",),
        ("stop_app", "com.demo"),
        ("grant_permission", "com.demo", "POST_NOTIFICATIONS"),
        ("launch_app", "com.demo"),
    ]


def test_launch_app_custom_permissions_override(tmp_path: Path):
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text(
        "appId: com.demo\n---\n- launchApp:\n    permissions:\n      - CAMERA\n"
    )
    driver = FakeDriver()
    runner = FlowRunner(driver, artifacts_dir=tmp_path / "artifacts")
    res = runner.run(flow_file)
    assert res.ok
    assert driver.actions == [
        ("stop_app", "com.demo"),
        ("grant_permission", "com.demo", "CAMERA"),
        ("launch_app", "com.demo"),
    ]


def test_grant_and_revoke_permissions_steps(tmp_path: Path):
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text(
        "appId: com.demo\n"
        "---\n"
        "- grantPermissions: RECORD_AUDIO\n"
        "- grantPermissions:\n"
        "    - ACCESS_FINE_LOCATION\n"
        "- revokePermissions: RECORD_AUDIO\n"
    )
    driver = FakeDriver()
    runner = FlowRunner(driver, artifacts_dir=tmp_path / "artifacts")
    res = runner.run(flow_file)
    assert res.ok
    assert driver.actions == [
        ("grant_permission", "com.demo", "RECORD_AUDIO"),
        ("grant_permission", "com.demo", "ACCESS_FINE_LOCATION"),
        ("revoke_permission", "com.demo", "RECORD_AUDIO"),
    ]


def test_wake_up_and_dismiss_system_dialogs(tmp_path: Path):
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text("appId: com.demo\n---\n- wakeUp\n- dismissSystemDialogs\n")
    driver = FakeDriver()
    runner = FlowRunner(driver, artifacts_dir=tmp_path / "artifacts")
    res = runner.run(flow_file)
    assert res.ok
    assert driver.actions == [
        ("wake_up_and_unlock",),
        ("dismiss_system_dialogs",),
    ]
