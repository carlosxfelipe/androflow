from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .android import AndroidDriver, AndroidError
from .selectors import UiElement, find_element, parse_elements, validate_selector

Step = dict[str, Any]

# Regex para variáveis de ambiente: ${VAR}, ${VAR:-default} ou ${VAR:default}
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^{}]*)|:([^{}]*))?\}")


def load_env_file(path: str | Path = ".env") -> dict[str, str]:
    """Lê variáveis de um arquivo .env se ele existir."""
    env_vars: dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return env_vars
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            env_vars[key] = val
    return env_vars


def interpolate_string(text: str, env: dict[str, str]) -> str:
    """Substitui ${VAR}, ${VAR:-padrao} ou ${VAR:padrao} pelo valor do ambiente."""
    for _ in range(20):
        if "${" not in text:
            break
        match = _VAR_RE.search(text)
        if not match:
            break
        var_name = match.group(1)
        default_val = match.group(2) if match.group(2) is not None else match.group(3)
        if var_name in env and (env[var_name] != "" or match.group(2) is None):
            val = env[var_name]
        elif default_val is not None:
            val = default_val
        else:
            raise FlowError(f"Variável de ambiente '{var_name}' não definida.")
        text = text[: match.start()] + val + text[match.end() :]
    return text


def interpolate_data(data: Any, env: dict[str, str]) -> Any:
    """Interpola recursivamente variáveis de ambiente em strings, dicts e listas."""
    if isinstance(data, str):
        return interpolate_string(data, env)
    if isinstance(data, dict):
        return {
            (interpolate_string(k, env) if isinstance(k, str) else k): interpolate_data(
                v, env
            )
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [interpolate_data(item, env) for item in data]
    return data


# Comandos cujo valor é um seletor (texto ou objeto YAML).
_SELECTOR_COMMANDS = frozenset(
    {"tapOn", "assertVisible", "assertNotVisible", "waitFor"}
)
# Comandos que exigem um valor (ex.: `- sleep: 2000`, e não apenas `- sleep`).
_VALUE_REQUIRED = _SELECTOR_COMMANDS | {
    "inputText",
    "takeScreenshot",
    "sleep",
    "pressKey",
    "openLink",
    "swipe",
    "repeat",
    "scrollUntilVisible",
    "grantPermissions",
    "revokePermissions",
}


class FlowError(RuntimeError):
    """Raised when a flow is invalid or one of its steps fails."""


@dataclass(frozen=True)
class StepResult:
    index: int
    command: str
    passed: bool
    error: str | None = None
    duration: float = 0.0


@dataclass
class FlowResult:
    path: Path
    total: int
    steps: list[StepResult] = field(default_factory=list)
    duration: float = 0.0
    video_path: Path | None = None
    artifacts: list[Path] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(step.passed for step in self.steps)

    @property
    def failed(self) -> int:
        return len(self.steps) - self.passed

    @property
    def skipped(self) -> int:
        return self.total - len(self.steps)

    @property
    def ok(self) -> bool:
        return self.failed == 0


class FlowRunner:
    def __init__(
        self,
        driver: AndroidDriver,
        default_timeout: float = 10,
        *,
        env: dict[str, str] | None = None,
        artifacts_dir: str | Path = "artifacts",
        poll_interval: float = 0.25,
        echo: Callable[[str], None] = print,
    ) -> None:
        self.driver = driver
        self.default_timeout = default_timeout
        self.env = dict(env or {})
        self.artifacts_dir = Path(artifacts_dir)
        self.poll_interval = poll_interval
        self.echo = echo
        self._app_id: str | None = None
        self._transliterate: bool = False
        self._default_permissions: list[str] = []
        self._default_wake_up: bool = False
        self._current_result: FlowResult | None = None
        self._handlers: dict[str, Callable[[Any], None]] = {
            "launchApp": self._launch_app,
            "stopApp": self._stop_app,
            "tapOn": self._tap_on,
            "inputText": self._input_text,
            "eraseText": self._erase_text,
            "pressKey": self._press_key,
            "hideKeyboard": self._hide_keyboard,
            "scroll": self._scroll,
            "swipe": self._swipe,
            "openLink": self._open_link,
            "assertVisible": self._assert_visible,
            "assertNotVisible": self._assert_not_visible,
            "waitFor": self._wait_for,
            "repeat": self._repeat,
            "takeScreenshot": self._take_screenshot,
            "back": self._back,
            "sleep": self._sleep,
            "scrollUntilVisible": self._scroll_until_visible,
            "disableAnimations": self._disable_animations,
            "enableAnimations": self._enable_animations,
            "grantPermissions": self._grant_permissions,
            "revokePermissions": self._revoke_permissions,
            "wakeUp": self._wake_up,
            "dismissSystemDialogs": self._dismiss_system_dialogs,
        }

    # ------------------------------------------------------------------
    # Carregamento e validação
    # ------------------------------------------------------------------

    def load_flow(
        self, path: str | Path, env: dict[str, str] | None = None
    ) -> tuple[dict[str, Any], list[Step]]:
        flow_path = Path(path)
        try:
            docs = list(yaml.safe_load_all(flow_path.read_text(encoding="utf-8")))
        except FileNotFoundError as exc:
            raise FlowError(f"Arquivo de fluxo não encontrado: {flow_path}") from exc
        except yaml.YAMLError as exc:
            raise FlowError(f"YAML inválido em {flow_path}: {exc}") from exc

        if len(docs) == 2 and isinstance(docs[0], dict) and isinstance(docs[1], list):
            raw_config, raw_steps = docs
        elif (
            len(docs) == 1
            and isinstance(docs[0], dict)
            and isinstance(docs[0].get("steps"), list)
        ):
            raw_config, raw_steps = docs[0], docs[0]["steps"]
        else:
            raise FlowError(
                "Formato esperado: cabeçalho com appId, separador '---' e lista de "
                "comandos; ou um objeto com 'appId' e 'steps'."
            )

        # Monta o ambiente: os.environ + .env + self.env + env da chamada + header env
        resolved_env = dict(os.environ)
        resolved_env.update(load_env_file(".env"))
        resolved_env.update(self.env)
        if env:
            resolved_env.update(env)

        if isinstance(raw_config.get("env"), dict):
            for k, v in raw_config["env"].items():
                if k not in self.env and (env is None or k not in env):
                    resolved_env.setdefault(str(k), str(v))

        config = interpolate_data(raw_config, resolved_env)
        raw_steps = interpolate_data(raw_steps, resolved_env)

        self._app_id = config.get("appId")
        self._transliterate = bool(config.get("transliterate", False))
        self._default_wake_up = bool(config.get("wakeUp", False))
        raw_perms = config.get("permissions", [])
        if isinstance(raw_perms, str):
            self._default_permissions = [raw_perms]
        elif isinstance(raw_perms, list) and all(isinstance(p, str) for p in raw_perms):
            self._default_permissions = list(raw_perms)
        else:
            self._default_permissions = []

        # Valida o fluxo inteiro antes de executar qualquer etapa (fail-fast).
        steps: list[Step] = []
        for index, raw_step in enumerate(raw_steps, start=1):
            if isinstance(raw_step, str):
                step: Step = {raw_step: None}
            elif isinstance(raw_step, dict) and len(raw_step) == 1:
                step = raw_step
            else:
                raise FlowError(
                    f"Etapa {index}: cada comando deve ser uma string ou um objeto "
                    "com uma única chave."
                )
            command, value = next(iter(step.items()))
            self._validate_step(index, command, value, config.get("appId"))
            steps.append(step)
        return config, steps

    def _validate_step(
        self, index: int, command: str, value: Any, app_id: str | None
    ) -> None:
        if command not in self._handlers:
            available = ", ".join(sorted(self._handlers))
            raise FlowError(
                f"Etapa {index}: comando desconhecido '{command}'. "
                f"Disponíveis: {available}."
            )
        if command in _VALUE_REQUIRED and value is None:
            raise FlowError(f"Etapa {index} ({command}): informe um valor.")
        try:
            if command == "tapOn":
                if self._parse_point_spec(value) is not None:
                    return
                self._parse_selector(command, value)
            elif command in _SELECTOR_COMMANDS:
                self._parse_selector(command, value)
            elif command == "launchApp":
                self._launch_target(value, app_id)
            elif command == "stopApp":
                if value is not None and not isinstance(value, str):
                    raise FlowError("stopApp: informe o appId em texto.")
            elif command == "inputText":
                self._parse_input_text_spec(value)
            elif command == "eraseText":
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, int) or value <= 0
                ):
                    raise FlowError("eraseText deve ser um número inteiro > 0.")
            elif command == "pressKey":
                if not isinstance(value, (str, int)) or isinstance(value, bool):
                    raise FlowError("pressKey: informe o nome ou código da tecla.")
            elif command == "openLink":
                if not isinstance(value, str) or not value.strip():
                    raise FlowError("openLink: informe a URL em texto.")
            elif command == "scroll":
                if value is not None and str(value).upper() not in {
                    "DOWN",
                    "UP",
                    "LEFT",
                    "RIGHT",
                }:
                    raise FlowError("scroll: direção deve ser DOWN, UP, LEFT ou RIGHT.")
            elif command == "swipe":
                self._validate_swipe(value)
            elif command == "repeat":
                self._validate_repeat(value, app_id)
            elif command == "sleep":
                self._parse_duration(value, name="sleep")
            elif command == "scrollUntilVisible":
                self._parse_scroll_until_visible_spec(value)
            elif command in {"disableAnimations", "enableAnimations"}:
                if value is not None and not isinstance(value, bool):
                    raise FlowError(
                        f"{command}: aceita apenas valor booleano ou vazio."
                    )
            elif command in {"grantPermissions", "revokePermissions"}:
                perms = [value] if isinstance(value, str) else value
                if (
                    not isinstance(perms, list)
                    or not perms
                    or not all(isinstance(p, str) for p in perms)
                ):
                    raise FlowError(
                        f"{command}: informe uma permissão ou lista de permissões."
                    )
            elif command in {"wakeUp", "dismissSystemDialogs"}:
                if value is not None and not isinstance(value, bool):
                    raise FlowError(
                        f"{command}: comando não aceita argumentos adicionais."
                    )
            elif command == "takeScreenshot" and not (
                isinstance(value, str) and value.strip()
            ):
                raise FlowError("takeScreenshot: informe o nome do arquivo.")
        except FlowError as exc:
            raise FlowError(f"Etapa {index}: {exc}") from exc

    def _validate_swipe(self, value: Any) -> None:
        if not isinstance(value, dict):
            raise FlowError("swipe deve ser um objeto com direction ou start e end.")
        if "direction" in value:
            if str(value["direction"]).upper() not in {"DOWN", "UP", "LEFT", "RIGHT"}:
                raise FlowError("swipe: direction deve ser DOWN, UP, LEFT ou RIGHT.")
            return
        if "start" in value and "end" in value:
            for key in ("start", "end"):
                pt = self._parse_point_value(value[key])
                if pt is None:
                    raise FlowError(f"swipe: {key} deve ser [x, y], 'x,y' ou 'x%,y%'.")
            return
        raise FlowError("swipe deve conter 'direction' ou 'start' e 'end'.")

    def _validate_repeat(self, value: Any, app_id: str | None) -> None:
        if not isinstance(value, dict):
            raise FlowError("repeat deve ser um objeto com 'times' e 'commands'.")
        times = value.get("times")
        if isinstance(times, bool) or not isinstance(times, int) or times <= 0:
            raise FlowError("repeat: 'times' deve ser um inteiro > 0.")
        commands = value.get("commands")
        if not isinstance(commands, list) or not commands:
            raise FlowError(
                "repeat: 'commands' deve ser uma lista não vazia de comandos."
            )
        for sub_idx, raw_step in enumerate(commands, start=1):
            if isinstance(raw_step, str):
                step = {raw_step: None}
            elif isinstance(raw_step, dict) and len(raw_step) == 1:
                step = raw_step
            else:
                raise FlowError(f"repeat comando {sub_idx}: comando inválido.")
            cmd, val = next(iter(step.items()))
            self._validate_step(sub_idx, cmd, val, app_id)

    # ------------------------------------------------------------------
    # Parsing dos valores das etapas
    # ------------------------------------------------------------------

    def _parse_selector(self, command: str, value: Any) -> tuple[dict[str, Any], float]:
        if isinstance(value, str):
            selector: dict[str, Any] = {"text": value}
        elif isinstance(value, dict):
            selector = dict(value)  # cópia: não altera o fluxo carregado
        else:
            raise FlowError(f"{command}: seletor deve ser texto ou objeto YAML.")
        raw_timeout = selector.pop("timeout", None)
        timeout = (
            self.default_timeout
            if raw_timeout is None
            else self._parse_duration(raw_timeout, name="timeout")
        )
        try:
            validate_selector(selector)
        except ValueError as exc:
            raise FlowError(f"{command}: {exc}") from exc
        return selector, timeout

    @staticmethod
    def _parse_point_value(point: Any) -> Any:
        if isinstance(point, list):
            if len(point) == 2 and all(
                isinstance(v, int) and not isinstance(v, bool) for v in point
            ):
                return point[0], point[1]
            return None
        if isinstance(point, str):
            parts = [p.strip() for p in point.split(",")]
            if len(parts) == 2:
                for p in parts:
                    clean = p[:-1] if p.endswith("%") else p
                    try:
                        float(clean)
                    except ValueError:
                        return None
                return point
            return None
        return None

    def _parse_point_spec(self, value: Any) -> Any:
        if not (isinstance(value, dict) and "point" in value):
            return None
        pt = self._parse_point_value(value["point"])
        if pt is None:
            raise FlowError("tapOn: point deve ser [x, y], 'x,y' ou 'x%,y%'.")
        return pt

    @classmethod
    def _parse_point(cls, value: Any) -> tuple[int, int] | None:
        if not (isinstance(value, dict) and "point" in value):
            return None
        pt = cls._parse_point_value(value["point"])
        if isinstance(pt, tuple):
            return pt
        return None

    def _resolve_point(self, point_spec: Any) -> tuple[int, int]:
        if isinstance(point_spec, (tuple, list)):
            return int(point_spec[0]), int(point_spec[1])
        if isinstance(point_spec, str):
            parts = [p.strip() for p in point_spec.split(",")]
            size_fn = getattr(self.driver, "screen_size", None)
            w, h = size_fn() if callable(size_fn) else (1080, 2400)
            coords: list[int] = []
            for val, total in zip(parts, (w, h), strict=False):
                if val.endswith("%"):
                    pct = float(val[:-1]) / 100.0
                    coords.append(int(total * pct))
                else:
                    coords.append(int(float(val)))
            return coords[0], coords[1]
        raise FlowError(f"Formato de coordenadas inválido: {point_spec}")

    @staticmethod
    def _parse_duration(value: Any, name: str = "sleep") -> float:
        """Converte duração (ms puro ou string como '500ms'/'5s') para segundos.

        Como no Maestro, o padrão para números puros são milissegundos (2000 = 2s).
        Strings com unidade explícita ('s' ou 'ms') também são aceitas.
        """
        if isinstance(value, bool):
            raise FlowError(
                f"{name} deve ser um número (ms) ou conter unidade ('s'/'ms')."
            )
        if isinstance(value, str):
            val_str = value.strip().lower()
            if val_str.endswith("ms"):
                try:
                    ms = float(val_str[:-2])
                    if ms < 0:
                        raise ValueError
                    return ms / 1000.0
                except ValueError:
                    raise FlowError(f"{name} com 'ms' inválido: {value}") from None
            if val_str.endswith("s"):
                try:
                    s = float(val_str[:-1])
                    if s < 0:
                        raise ValueError
                    return s
                except ValueError:
                    raise FlowError(f"{name} com 's' inválido: {value}") from None
            try:
                ms = float(val_str)
                if ms < 0:
                    raise ValueError
                return ms / 1000.0
            except ValueError:
                raise FlowError(
                    f"{name} deve ser um número (ms) ou conter unidade ('s'/'ms')."
                ) from None

        if not isinstance(value, (int, float)) or value < 0:
            raise FlowError(f"{name} deve ser um número de milissegundos >= 0.")
        return float(value) / 1000.0

    _parse_seconds = _parse_duration

    @staticmethod
    def _parse_text(value: Any) -> str:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise FlowError(
                "inputText deve ser um texto (use aspas em valores como yes/no)."
            )
        return str(value)

    def _parse_input_text_spec(
        self, value: Any
    ) -> tuple[dict[str, Any] | None, str, float, bool]:
        if isinstance(value, dict):
            val = dict(value)
            raw_timeout = val.pop("timeout", None)
            if raw_timeout is None:
                timeout = self.default_timeout
            else:
                timeout = self._parse_duration(raw_timeout, name="timeout")
            raw_transliterate = val.pop("transliterate", self._transliterate)
            if not isinstance(raw_transliterate, bool):
                raise FlowError(
                    "inputText: 'transliterate' deve ser booleano (true/false)."
                )
            transliterate = raw_transliterate
            has_selector = any(k in val for k in ("id", "resourceId", "contentDesc"))
            if "value" in val:
                text_to_type = self._parse_text(val.pop("value"))
            elif "text" in val:
                text_to_type = self._parse_text(val.pop("text"))
            else:
                raise FlowError("inputText: informe o texto em 'text' ou 'value'.")

            if has_selector:
                validate_selector(val)
                return val, text_to_type, timeout, transliterate

            if val:
                raise FlowError(
                    f"inputText: chave(s) desconhecida(s): {', '.join(sorted(val))}."
                )
            return None, text_to_type, timeout, transliterate

        return None, self._parse_text(value), self.default_timeout, self._transliterate

    def _parse_scroll_until_visible_spec(
        self, value: Any
    ) -> tuple[dict[str, Any], str, int, float | None]:
        if isinstance(value, str):
            selector: dict[str, Any] = {"text": value}
            direction = "DOWN"
            max_scrolls = 10
            timeout = None
        elif isinstance(value, dict):
            val = dict(value)
            direction = str(val.pop("direction", "DOWN")).upper()
            if direction not in {"DOWN", "UP", "LEFT", "RIGHT"}:
                raise FlowError(
                    "scrollUntilVisible: direction deve ser DOWN, UP, LEFT ou RIGHT."
                )
            raw_max_scrolls = val.pop("maxScrolls", 10)
            if (
                isinstance(raw_max_scrolls, bool)
                or not isinstance(raw_max_scrolls, int)
                or raw_max_scrolls <= 0
            ):
                raise FlowError(
                    "scrollUntilVisible: maxScrolls deve ser um inteiro > 0."
                )
            max_scrolls = raw_max_scrolls

            raw_timeout = val.pop("timeout", None)
            timeout = (
                None
                if raw_timeout is None
                else self._parse_duration(raw_timeout, name="timeout")
            )

            if "element" in val:
                elem = val.pop("element")
                if not isinstance(elem, dict):
                    raise FlowError(
                        "scrollUntilVisible: 'element' deve ser um objeto seletor."
                    )
                selector = dict(elem)
                if val:
                    raise FlowError(
                        f"scrollUntilVisible: chave(s) desconhecida(s): "
                        f"{', '.join(sorted(val))}."
                    )
            else:
                selector = val
        else:
            raise FlowError(
                "scrollUntilVisible: seletor deve ser texto ou objeto YAML."
            )

        try:
            validate_selector(selector)
        except ValueError as exc:
            raise FlowError(f"scrollUntilVisible: {exc}") from exc

        return selector, direction, max_scrolls, timeout

    def _launch_target(
        self, value: Any, default: str | None
    ) -> tuple[str, bool, bool, list[str], bool]:
        """Retorna (appId, stopApp, clearState, permissions, wakeUp).

        Como no Maestro, stopApp é true por padrão.
        """
        stop_app: Any = True
        clear_state: Any = False
        permissions: list[str] = list(self._default_permissions)
        wake_up: Any = self._default_wake_up
        if value is None:
            package = default
        elif isinstance(value, str):
            package = value
        elif isinstance(value, dict):
            package = value.get("appId", default)
            stop_app = value.get("stopApp", True)
            clear_state = value.get("clearState", False)
            wake_up = value.get("wakeUp", self._default_wake_up)
            if "permissions" in value:
                raw_perms = value["permissions"]
                if isinstance(raw_perms, str):
                    permissions = [raw_perms]
                elif isinstance(raw_perms, list) and all(
                    isinstance(p, str) for p in raw_perms
                ):
                    permissions = list(raw_perms)
                else:
                    raise FlowError(
                        "launchApp: permissions deve ser uma lista de permissões."
                    )
        else:
            raise FlowError(
                "launchApp: use '- launchApp', '- launchApp: <appId>' "
                "ou '- launchApp: {appId: ..., stopApp: true, clearState: false}'."
            )

        def _parse_bool(val: Any, field_name: str) -> bool:
            if isinstance(val, bool):
                return val
            if isinstance(val, str) and val.lower() in ("true", "false"):
                return val.lower() == "true"
            raise FlowError(f"launchApp: {field_name} deve ser true ou false.")

        stop_app = _parse_bool(stop_app, "stopApp")
        clear_state = _parse_bool(clear_state, "clearState")
        wake_up = _parse_bool(wake_up, "wakeUp")
        if not package:
            raise FlowError("launchApp: informe appId no cabeçalho do fluxo.")
        return str(package), stop_app, clear_state, permissions, wake_up

    def _screenshot_path(self, value: Any) -> Path:
        path = Path(str(value))
        if not path.is_absolute():
            path = self.artifacts_dir / path
        if path.suffix.lower() != ".png":
            path = path.with_name(path.name + ".png")
        return path

    # ------------------------------------------------------------------
    # Execução
    # ------------------------------------------------------------------

    def run(self, path: str | Path, *, record: bool = False) -> FlowResult:
        flow_path = Path(path)
        config, steps = self.load_flow(flow_path)
        self._app_id = config.get("appId")
        self._transliterate = bool(config.get("transliterate", False))
        if config.get("disableAnimations") is True and hasattr(
            self.driver, "disable_animations"
        ):
            self.echo("Desativando animações do Android via ADB...")
            self.driver.disable_animations()

        should_record = record or bool(config.get("record", False))
        recording_proc = None
        video_dest = self.artifacts_dir / f"{flow_path.stem}.mp4"
        if should_record and hasattr(self.driver, "start_recording"):
            self.echo("Iniciando gravação de tela via ADB screenrecord...")
            recording_proc = self.driver.start_recording()

        result = FlowResult(path=flow_path, total=len(steps))
        self._current_result = result
        flow_start = time.monotonic()
        self.echo(f"AndroFlow: {flow_path} ({len(steps)} etapas)")
        try:
            for index, step in enumerate(steps, start=1):
                command, value = next(iter(step.items()))
                step_start = time.monotonic()
                try:
                    self.execute(command, value)
                except (FlowError, AndroidError, ValueError) as exc:
                    error = str(exc)
                except Exception as exc:  # inesperado: mostra o tipo para depuração
                    error = f"{type(exc).__name__}: {exc}"
                else:
                    duration = round(time.monotonic() - step_start, 3)
                    result.steps.append(
                        StepResult(index, command, passed=True, duration=duration)
                    )
                    self.echo(
                        f"  PASS {index:02d} {command} ({int(duration * 1000)}ms)"
                    )
                    continue
                duration = round(time.monotonic() - step_start, 3)
                result.steps.append(
                    StepResult(
                        index, command, passed=False, error=error, duration=duration
                    )
                )
                self.echo(
                    f"  FAIL {index:02d} {command}: {error} ({int(duration * 1000)}ms)"
                )
                self._capture_failure(flow_path, index)
                break
        finally:
            result.duration = round(time.monotonic() - flow_start, 3)
            if recording_proc is not None and hasattr(self.driver, "stop_recording"):
                self.echo("Finalizando gravação de tela...")
                saved_video = self.driver.stop_recording(recording_proc, video_dest)
                if saved_video:
                    result.video_path = saved_video
                    result.artifacts.append(saved_video)
                    self.echo(f"       Vídeo da execução: {saved_video}")
            self._current_result = None

        self.echo(
            f"\nResultado: {result.passed} ok, {result.failed} falha(s), "
            f"{result.skipped} pulada(s) de {result.total} etapas "
            f"({result.duration:.2f}s)."
        )
        return result

    def execute(self, command: str, value: Any = None) -> None:
        handler = self._handlers.get(command)
        if handler is None:
            raise FlowError(f"Comando desconhecido: {command}")
        handler(value)

    def _capture_failure(self, flow_path: Path, index: int) -> None:
        """Salva screenshot e hierarquia da tela no momento da falha."""
        base = f"{flow_path.stem}-falha-{index:02d}"
        png = self.artifacts_dir / f"{base}.png"
        xml = self.artifacts_dir / f"{base}.xml"
        try:
            self.driver.screenshot(png)
            root = self.driver.dump_hierarchy()
            xml.parent.mkdir(parents=True, exist_ok=True)
            ET.ElementTree(root).write(xml, encoding="utf-8", xml_declaration=True)
            if self._current_result is not None:
                self._current_result.artifacts.extend([png, xml])
        except (AndroidError, OSError) as exc:
            self.echo(f"       Não foi possível salvar artefatos da falha: {exc}")
            return
        self.echo(f"       Artefatos da falha: {png}, {xml}")

    # ------------------------------------------------------------------
    # Comandos
    # ------------------------------------------------------------------

    def _launch_app(self, value: Any) -> None:
        package, stop_app, clear_state, permissions, wake_up = self._launch_target(
            value, self._app_id
        )
        self._app_id = package
        if wake_up and hasattr(self.driver, "wake_up_and_unlock"):
            self.driver.wake_up_and_unlock()
        if clear_state and hasattr(self.driver, "clear_app"):
            self.driver.clear_app(package)
        if stop_app:
            self.driver.stop_app(package)
        if permissions and hasattr(self.driver, "grant_permission"):
            for perm in permissions:
                self.driver.grant_permission(package, perm)
        self.driver.launch_app(package)

    def _stop_app(self, value: Any) -> None:
        package = value or self._app_id
        if not package:
            raise FlowError("stopApp: informe o appId ou declare no cabeçalho.")
        self.driver.stop_app(str(package))

    def _tap_on(self, value: Any) -> None:
        point_spec = self._parse_point_spec(value)
        if point_spec is not None:
            point = self._resolve_point(point_spec)
        else:
            selector, timeout = self._parse_selector("tapOn", value)
            element = self._find(selector, timeout)
            if element is None:
                raise FlowError(f"Elemento não encontrado: {selector}")
            point = element.center
        self.driver.tap(*point)

    def _input_text(self, value: Any) -> None:
        selector, text_to_type, timeout, transliterate = self._parse_input_text_spec(
            value
        )
        if selector is not None:
            element = self._find(selector, timeout)
            if element is None:
                raise FlowError(f"Elemento não encontrado para inputText: {selector}")
            self.driver.tap(*element.center)
            self.driver.wait(0.3)
        try:
            self.driver.type_text(text_to_type, transliterate=transliterate)
        except TypeError:
            self.driver.type_text(text_to_type)

    def _erase_text(self, value: Any) -> None:
        chars = 50
        if value is not None:
            chars = int(value)
        if hasattr(self.driver, "erase_text"):
            self.driver.erase_text(chars)
        elif hasattr(self.driver, "press_key"):
            for _ in range(chars):
                self.driver.press_key("KEYCODE_DEL")

    def _press_key(self, value: Any) -> None:
        if hasattr(self.driver, "press_key"):
            self.driver.press_key(value)
        elif str(value).lower() == "back":
            self.driver.back()

    def _hide_keyboard(self, _value: Any) -> None:
        if hasattr(self.driver, "hide_keyboard"):
            self.driver.hide_keyboard()
        else:
            self.driver.back()

    def _scroll(self, value: Any) -> None:
        direction = "DOWN" if value is None else str(value).upper()
        if hasattr(self.driver, "scroll"):
            self.driver.scroll(direction)

    def _swipe(self, value: Any) -> None:
        if isinstance(value, dict):
            if "direction" in value:
                direction = str(value["direction"]).upper()
                if hasattr(self.driver, "scroll"):
                    self.driver.scroll(direction)
                return
            if "start" in value and "end" in value:
                start_pt = self._resolve_point(self._parse_point_value(value["start"]))
                end_pt = self._resolve_point(self._parse_point_value(value["end"]))
                duration = int(value.get("duration", 400))
                if hasattr(self.driver, "swipe"):
                    self.driver.swipe(
                        start_pt[0], start_pt[1], end_pt[0], end_pt[1], duration
                    )
                return

    def _open_link(self, value: Any) -> None:
        if hasattr(self.driver, "open_link"):
            self.driver.open_link(str(value))

    def _assert_visible(self, value: Any) -> None:
        selector, timeout = self._parse_selector("assertVisible", value)
        if self._find(selector, timeout) is None:
            raise FlowError(f"Esperava encontrar elemento visível: {selector}")

    def _assert_not_visible(self, value: Any) -> None:
        selector, timeout = self._parse_selector("assertNotVisible", value)
        if not self._wait_until_gone(selector, timeout):
            raise FlowError(
                f"Esperava que o elemento não estivesse visível: {selector}"
            )

    def _wait_for(self, value: Any) -> None:
        selector, timeout = self._parse_selector("waitFor", value)
        if self._find(selector, timeout) is None:
            raise FlowError(f"Timeout aguardando elemento: {selector}")

    def _repeat(self, value: Any) -> None:
        times = int(value["times"])
        commands = value["commands"]
        for _ in range(times):
            for raw_step in commands:
                if isinstance(raw_step, str):
                    cmd, val = raw_step, None
                elif isinstance(raw_step, dict) and len(raw_step) == 1:
                    cmd, val = next(iter(raw_step.items()))
                else:
                    continue
                self.execute(cmd, val)

    def _take_screenshot(self, value: Any) -> None:
        path = self._screenshot_path(value)
        self.driver.screenshot(path)
        if (
            self._current_result is not None
            and path not in self._current_result.artifacts
        ):
            self._current_result.artifacts.append(path)
        self.echo(f"       Screenshot: {path}")

    def _back(self, _value: Any) -> None:
        self.driver.back()

    def _sleep(self, value: Any) -> None:
        self.driver.wait(self._parse_duration(value, name="sleep"))

    def _scroll_until_visible(self, value: Any) -> None:
        selector, direction, max_scrolls, timeout = (
            self._parse_scroll_until_visible_spec(value)
        )
        deadline = time.monotonic() + timeout if timeout is not None else None

        if self._find(selector, timeout=0) is not None:
            return

        for _ in range(max_scrolls):
            if deadline is not None and time.monotonic() >= deadline:
                break
            if hasattr(self.driver, "scroll"):
                self.driver.scroll(direction)
            if self.poll_interval > 0:
                time.sleep(self.poll_interval)
            if self._find(selector, timeout=0) is not None:
                return

        if deadline is not None:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining > 0 and self._find(selector, timeout=remaining) is not None:
                return

        raise FlowError(
            f"scrollUntilVisible: elemento não encontrado após {max_scrolls} "
            f"rolagens: {selector}"
        )

    def _disable_animations(self, value: Any) -> None:
        if value is False:
            if hasattr(self.driver, "enable_animations"):
                self.driver.enable_animations()
        elif hasattr(self.driver, "disable_animations"):
            self.driver.disable_animations()

    def _enable_animations(self, value: Any) -> None:
        if value is False:
            if hasattr(self.driver, "disable_animations"):
                self.driver.disable_animations()
        elif hasattr(self.driver, "enable_animations"):
            self.driver.enable_animations()

    def _grant_permissions(self, value: Any) -> None:
        if not self._app_id:
            raise FlowError("grantPermissions: declare 'appId' no cabeçalho do fluxo.")
        perms = [value] if isinstance(value, str) else value
        if hasattr(self.driver, "grant_permission"):
            for perm in perms:
                self.driver.grant_permission(self._app_id, perm)

    def _revoke_permissions(self, value: Any) -> None:
        if not self._app_id:
            raise FlowError("revokePermissions: declare 'appId' no cabeçalho do fluxo.")
        perms = [value] if isinstance(value, str) else value
        if hasattr(self.driver, "revoke_permission"):
            for perm in perms:
                self.driver.revoke_permission(self._app_id, perm)

    def _wake_up(self, _value: Any) -> None:
        if hasattr(self.driver, "wake_up_and_unlock"):
            self.driver.wake_up_and_unlock()

    def _dismiss_system_dialogs(self, _value: Any) -> None:
        if hasattr(self.driver, "dismiss_system_dialogs"):
            self.driver.dismiss_system_dialogs()

    # ------------------------------------------------------------------
    # Polling da tela
    # ------------------------------------------------------------------

    def _elements(self) -> list[UiElement]:
        return parse_elements(self.driver.dump_hierarchy())

    def _poll(
        self, selector: dict[str, Any], timeout: float, *, present: bool
    ) -> tuple[bool, UiElement | None]:
        """Consulta a tela até o elemento estar presente/ausente ou o timeout."""
        deadline = time.monotonic() + timeout
        while True:
            # Só o erro da última tentativa importa: se a tela foi lida com
            # sucesso depois de uma falha, o resultado real é "não encontrado".
            error: AndroidError | None = None
            element: UiElement | None = None
            try:
                element = find_element(self._elements(), selector)
            except AndroidError as exc:
                error = exc
            else:
                if (element is not None) == present:
                    return True, element
            if time.monotonic() >= deadline:
                if error is not None:
                    raise FlowError(f"Falha ao ler a tela: {error}") from error
                return False, element
            time.sleep(self.poll_interval)

    def _find(self, selector: dict[str, Any], timeout: float) -> UiElement | None:
        found, element = self._poll(selector, timeout, present=True)
        return element if found else None

    def _wait_until_gone(self, selector: dict[str, Any], timeout: float) -> bool:
        gone, _ = self._poll(selector, timeout, present=False)
        return gone
