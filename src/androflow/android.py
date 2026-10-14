from __future__ import annotations

import re
import shlex
import subprocess
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path


class AndroidError(RuntimeError):
    """Raised when an ADB operation fails."""


_HIERARCHY_REMOTE = "/sdcard/androflow-window.xml"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_KEY_NAMES: dict[str, str] = {
    "enter": "KEYCODE_ENTER",
    "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME",
    "tab": "KEYCODE_TAB",
    "delete": "KEYCODE_DEL",
    "backspace": "KEYCODE_DEL",
    "volumeup": "KEYCODE_VOLUME_UP",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volumedown": "KEYCODE_VOLUME_DOWN",
    "volume_down": "KEYCODE_VOLUME_DOWN",
    "search": "KEYCODE_SEARCH",
    "space": "KEYCODE_SPACE",
    "escape": "KEYCODE_ESCAPE",
    "power": "KEYCODE_POWER",
}


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").strip()


class AndroidDriver:
    def __init__(self, serial: str | None = None, adb_path: str = "adb") -> None:
        self.serial = serial
        self.adb_path = adb_path
        self._cached_screen_size: tuple[int, int] | None = None

    def _run(self, args: Sequence[str], *, timeout: float = 30) -> bytes:
        """Executa o adb e devolve o stdout bruto (bytes)."""
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=timeout, check=False
            )
        except FileNotFoundError as exc:
            raise AndroidError(
                "ADB não foi encontrado. Instale Android SDK Platform Tools e "
                "adicione o executável adb ao PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AndroidError(
                f"Comando ADB excedeu o timeout: {shlex.join(cmd)}"
            ) from exc
        if result.returncode != 0:
            detail = _decode(result.stderr or result.stdout)
            raise AndroidError(f"ADB falhou ({result.returncode}): {detail}")
        return result.stdout

    def _command(self, args: Sequence[str], *, timeout: float = 30) -> str:
        return _decode(self._run(args, timeout=timeout))

    def devices(self) -> list[tuple[str, str]]:
        output = self._command(["devices"])
        rows: list[tuple[str, str]] = []
        for line in output.splitlines()[1:]:
            line = line.strip()
            if not line or "\t" not in line:
                continue
            serial, state = line.split("\t", 1)
            rows.append((serial, state.strip()))
        return rows

    def shell(self, *args: str, timeout: float = 30) -> str:
        return self._command(["shell", *args], timeout=timeout)

    @staticmethod
    def _check_app_id(app_id: str) -> None:
        if not app_id or "/" in app_id or " " in app_id:
            raise ValueError(
                "appId deve ser o nome de pacote Android, por exemplo com.exemplo.app"
            )

    def launch_app(self, app_id: str) -> None:
        self._check_app_id(app_id)
        self.shell(
            "monkey",
            "-p",
            app_id,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
            timeout=30,
        )

    def stop_app(self, app_id: str) -> None:
        self._check_app_id(app_id)
        self.shell("am", "force-stop", app_id)

    def tap(self, x: int, y: int) -> None:
        self.shell("input", "tap", str(int(x)), str(int(y)))

    def type_text(self, value: str, *, transliterate: bool = False) -> None:
        if not value.isascii():
            if transliterate:
                normalized = (
                    unicodedata.normalize("NFKD", value)
                    .encode("ascii", "ignore")
                    .decode("ascii")
                )
                if not normalized:
                    raise AndroidError(
                        f"O texto {value!r} continha apenas emojis ou caracteres "
                        "sem representação ASCII compatível com o ADB."
                    )
                value = normalized
            else:
                raise AndroidError(
                    f"`adb shell input text` só suporta caracteres ASCII ({value!r}); "
                    "acentos e emojis não são aceitos pelo ADB nativo. "
                    "Use 'transliterate: true' no seu inputText (ou no cabeçalho) "
                    "para normalizar automaticamente (ex.: 'Cartão' -> 'Cartao')."
                )
        # `input text` converte "%s" em espaço. Um "%s" literal é dividido em
        # chamadas separadas ("...%" e "s...") para não virar espaço.
        chunks = value.split("%s")
        pieces = [chunks[0]]
        for chunk in chunks[1:]:
            pieces[-1] += "%"
            pieces.append("s" + chunk)
        for piece in pieces:
            if piece:
                # O adb repassa a linha ao `sh` do dispositivo: as aspas impedem que
                # &, ;, |, $, aspas etc. sejam interpretados pelo shell.
                self.shell("input", "text", shlex.quote(piece.replace(" ", "%s")))

    def back(self) -> None:
        self.shell("input", "keyevent", "KEYCODE_BACK")

    def hide_keyboard(self) -> None:
        self.back()

    def clear_app(self, app_id: str) -> None:
        self._check_app_id(app_id)
        self.shell("pm", "clear", app_id)

    def press_key(self, key: str | int) -> None:
        raw = str(key).strip()
        normalized = raw.lower().replace("-", "_").replace(" ", "_")
        code = _KEY_NAMES.get(normalized)
        if not code:
            if raw.isdigit() or raw.startswith("KEYCODE_"):
                code = raw
            else:
                code = f"KEYCODE_{raw.upper()}"
        self.shell("input", "keyevent", code)

    def erase_text(self, characters: int = 50) -> None:
        count = max(1, int(characters))
        chunks = [min(count - i, 50) for i in range(0, count, 50)]
        for chunk in chunks:
            self.shell("input", "keyevent", *["67"] * chunk)

    def screen_size(self) -> tuple[int, int]:
        if self._cached_screen_size is not None:
            return self._cached_screen_size
        output = self.shell("wm", "size")
        matches = re.findall(r"(\d+)x(\d+)", output)
        if matches:
            w, h = int(matches[-1][0]), int(matches[-1][1])
            self._cached_screen_size = (w, h)
            return (w, h)
        return (1080, 2400)

    def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int = 400,
    ) -> None:
        self.shell(
            "input",
            "swipe",
            str(int(start_x)),
            str(int(start_y)),
            str(int(end_x)),
            str(int(end_y)),
            str(int(duration_ms)),
        )

    def scroll(self, direction: str = "DOWN") -> None:
        w, h = self.screen_size()
        direction_upper = direction.upper()
        if direction_upper == "DOWN":
            self.swipe(w // 2, int(h * 0.75), w // 2, int(h * 0.25))
        elif direction_upper == "UP":
            self.swipe(w // 2, int(h * 0.25), w // 2, int(h * 0.75))
        elif direction_upper == "LEFT":
            self.swipe(int(w * 0.8), h // 2, int(w * 0.2), h // 2)
        elif direction_upper == "RIGHT":
            self.swipe(int(w * 0.2), h // 2, int(w * 0.8), h // 2)
        else:
            raise ValueError(f"Direção de rolagem desconhecida: {direction}")

    def open_link(self, url: str) -> None:
        if not url:
            raise ValueError("URL não pode ser vazia.")
        self.shell(
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            shlex.quote(str(url)),
        )

    def dump_hierarchy(self) -> ET.Element:
        # Remove o dump anterior antes de gerar um novo: se o uiautomator falhar
        # (ex.: "could not get idle state") mas retornar 0, o `cat` falha em vez
        # de ler uma tela antiga. Tudo em um único round-trip ADB.
        remote = _HIERARCHY_REMOTE
        script = (
            f"rm -f {remote} && "
            f"uiautomator dump --compressed {remote} >&2 && "
            f"cat {remote}"
        )
        output = self.shell(script, timeout=30)
        # Em dispositivos antigos (sem shell protocol v2) stderr vem misturado.
        start = output.find("<?xml")
        if start < 0:
            start = output.find("<hierarchy")
        try:
            return ET.fromstring(output[max(start, 0) :])
        except ET.ParseError as exc:
            raise AndroidError(
                "Não foi possível interpretar a hierarquia XML da tela. "
                "Verifique se o emulador está desbloqueado."
            ) from exc

    def screenshot(self, destination: str | Path) -> Path:
        path = Path(destination)
        data = self._run(["exec-out", "screencap", "-p"], timeout=30)
        if not data.startswith(_PNG_SIGNATURE):
            raise AndroidError(
                f"Screenshot inválido recebido do dispositivo: {_decode(data[:200])}"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def wait(self, seconds: float) -> None:
        time.sleep(max(0, seconds))

    def disable_animations(self) -> None:
        """Desativa animações do Android via ADB para acelerar testes."""
        for setting in (
            "window_animation_scale",
            "transition_animation_scale",
            "animator_duration_scale",
        ):
            self.shell("settings", "put", "global", setting, "0")

    def enable_animations(self) -> None:
        """Restaura animações do Android para a escala padrão (1.0) via ADB."""
        for setting in (
            "window_animation_scale",
            "transition_animation_scale",
            "animator_duration_scale",
        ):
            self.shell("settings", "put", "global", setting, "1")
