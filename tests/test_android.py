import shlex

import pytest

from androflow.android import _PNG_SIGNATURE, AndroidDriver, AndroidError


@pytest.fixture
def driver(monkeypatch: pytest.MonkeyPatch) -> AndroidDriver:
    driver = AndroidDriver()
    driver.calls = []
    driver.shell_output = ""

    def fake_shell(*args, timeout=30):
        driver.calls.append(args)
        return driver.shell_output

    monkeypatch.setattr(driver, "shell", fake_shell)
    return driver


def test_type_text_quotes_shell_metacharacters(driver: AndroidDriver):
    driver.type_text("p@ss&w;rd $(x) 'y'")
    assert driver.calls == [
        ("input", "text", shlex.quote("p@ss&w;rd%s$(x)%s'y'")),
    ]


def test_type_text_keeps_literal_percent_s(driver: AndroidDriver):
    driver.type_text("100%sure")
    assert driver.calls == [("input", "text", "100%"), ("input", "text", "sure")]


def test_type_text_rejects_non_ascii(driver: AndroidDriver):
    with pytest.raises(AndroidError, match="ASCII"):
        driver.type_text("ação")
    assert driver.calls == []


def test_dump_hierarchy_never_reads_stale_file(driver: AndroidDriver):
    driver.shell_output = (
        "UI hierchary dumped to: /sdcard/x.xml\n"
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
        '<hierarchy><node text="Oi" bounds="[0,0][1,1]" /></hierarchy>'
    )
    root = driver.dump_hierarchy()
    assert root.tag == "hierarchy"
    # Um único comando que apaga o dump anterior antes de gerar o novo.
    assert len(driver.calls) == 1
    assert driver.calls[0][0].startswith("rm -f ")


def test_dump_hierarchy_invalid_xml_raises(driver: AndroidDriver):
    driver.shell_output = "ERROR: could not get idle state."
    with pytest.raises(AndroidError, match="hierarquia XML"):
        driver.dump_hierarchy()


def test_screenshot_writes_png(tmp_path, monkeypatch: pytest.MonkeyPatch):
    driver = AndroidDriver()
    monkeypatch.setattr(driver, "_run", lambda args, timeout=30: _PNG_SIGNATURE)
    path = driver.screenshot(tmp_path / "out" / "shot.png")
    assert path.read_bytes() == _PNG_SIGNATURE


def test_screenshot_rejects_non_png(tmp_path, monkeypatch: pytest.MonkeyPatch):
    driver = AndroidDriver()
    monkeypatch.setattr(driver, "_run", lambda args, timeout=30: b"error: closed")
    with pytest.raises(AndroidError, match="Screenshot inválido"):
        driver.screenshot(tmp_path / "shot.png")
    assert not (tmp_path / "shot.png").exists()


def test_clear_app(driver: AndroidDriver):
    driver.clear_app("com.demo.app")
    assert driver.calls == [("pm", "clear", "com.demo.app")]


def test_press_key_named_and_custom(driver: AndroidDriver):
    driver.press_key("Enter")
    driver.press_key("volume_down")
    driver.press_key("KEYCODE_CAMERA")
    driver.press_key("66")
    assert driver.calls == [
        ("input", "keyevent", "KEYCODE_ENTER"),
        ("input", "keyevent", "KEYCODE_VOLUME_DOWN"),
        ("input", "keyevent", "KEYCODE_CAMERA"),
        ("input", "keyevent", "66"),
    ]


def test_erase_text(driver: AndroidDriver):
    driver.erase_text(3)
    assert driver.calls == [("input", "keyevent", "67", "67", "67")]


def test_screen_size_and_scroll(driver: AndroidDriver):
    driver.shell_output = "Physical size: 1080x2400"
    size = driver.screen_size()
    assert size == (1080, 2400)
    # Segundo acesso deve usar o cache
    driver.shell_output = "Physical size: 500x500"
    assert driver.screen_size() == (1080, 2400)

    driver.calls.clear()
    driver.scroll("DOWN")
    assert driver.calls == [("input", "swipe", "540", "1800", "540", "600", "400")]


def test_swipe_custom(driver: AndroidDriver):
    driver.swipe(10, 20, 30, 40, 500)
    assert driver.calls == [("input", "swipe", "10", "20", "30", "40", "500")]


def test_open_link(driver: AndroidDriver):
    driver.open_link("https://exemplo.com?q=1")
    assert driver.calls == [
        (
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            "'https://exemplo.com?q=1'",
        )
    ]


def test_hide_keyboard(driver: AndroidDriver):
    driver.hide_keyboard()
    assert driver.calls == [("input", "keyevent", "KEYCODE_BACK")]
