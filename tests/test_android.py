import shlex
from pathlib import Path
from unittest.mock import MagicMock

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


def test_type_text_transliterates_accents(driver: AndroidDriver):
    driver.type_text("ação", transliterate=True)
    assert driver.calls == [("input", "text", "acao")]

    driver.calls.clear()
    driver.type_text("Cartão de Crédito", transliterate=True)
    assert driver.calls == [("input", "text", shlex.quote("Cartao%sde%sCredito"))]


def test_type_text_transliterate_only_emojis_raises(driver: AndroidDriver):
    with pytest.raises(AndroidError, match="emojis"):
        driver.type_text("🚀🎉", transliterate=True)
    assert driver.calls == []


def test_dump_hierarchy_never_reads_stale_file(driver: AndroidDriver):
    driver.shell_output = (
        "UI hierchary dumped to: /sdcard/x.xml\n"
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
        '<hierarchy><node text="Oi" bounds="[0,0][1,1]" /></hierarchy>'
    )
    root = driver.dump_hierarchy()
    assert root.tag == "hierarchy"
    # Um único comando que apaga o dump anterior e gera novo dump comprimido.
    assert len(driver.calls) == 1
    assert driver.calls[0][0].startswith("rm -f ")
    assert "--compressed" in driver.calls[0][0]


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


def test_disable_and_enable_animations(driver: AndroidDriver):
    driver.disable_animations()
    assert driver.calls == [
        ("settings", "put", "global", "window_animation_scale", "0"),
        ("settings", "put", "global", "transition_animation_scale", "0"),
        ("settings", "put", "global", "animator_duration_scale", "0"),
    ]
    driver.calls.clear()
    driver.enable_animations()
    assert driver.calls == [
        ("settings", "put", "global", "window_animation_scale", "1"),
        ("settings", "put", "global", "transition_animation_scale", "1"),
        ("settings", "put", "global", "animator_duration_scale", "1"),
    ]


def test_grant_and_revoke_permission(driver: AndroidDriver):
    driver.grant_permission("com.demo", "POST_NOTIFICATIONS")
    driver.grant_permission("com.demo", "android.permission.CAMERA")
    driver.revoke_permission("com.demo", "POST_NOTIFICATIONS")
    assert driver.calls == [
        ("pm", "grant", "com.demo", "android.permission.POST_NOTIFICATIONS"),
        ("pm", "grant", "com.demo", "android.permission.CAMERA"),
        ("pm", "revoke", "com.demo", "android.permission.POST_NOTIFICATIONS"),
    ]


def test_wake_up_and_dismiss_system_dialogs(driver: AndroidDriver):
    driver.wake_up_and_unlock()
    assert driver.calls == [
        ("input", "keyevent", "KEYCODE_WAKEUP"),
        ("wm", "dismiss-keyguard"),
    ]
    driver.calls.clear()
    driver.dismiss_system_dialogs()
    assert driver.calls == [
        ("am", "broadcast", "-a", "android.intent.action.CLOSE_SYSTEM_DIALOGS"),
    ]


def test_start_and_stop_recording(
    driver: AndroidDriver, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    mock_proc = MagicMock()
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: mock_proc)
    monkeypatch.setattr(driver, "_run", lambda *args, **kwargs: b"pulled")

    proc = driver.start_recording()
    assert proc == mock_proc

    dest = tmp_path / "video.mp4"
    dest.write_bytes(b"dummy mp4 data")

    res = driver.stop_recording(proc, dest)
    assert res == dest
    mock_proc.send_signal.assert_called_once()
    assert ("rm", "-f", "/sdcard/androflow_record.mp4") in driver.calls
