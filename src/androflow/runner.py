from __future__ import annotations

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

# Comandos cujo valor é um seletor (texto ou objeto YAML).
_SELECTOR_COMMANDS = frozenset(
    {"tapOn", "assertVisible", "assertNotVisible", "waitFor"}
)
# Comandos que exigem um valor (ex.: `- sleep: 2`, e não apenas `- sleep`).
_VALUE_REQUIRED = _SELECTOR_COMMANDS | {
    "inputText",
    "takeScreenshot",
    "sleep",
    "pressKey",
    "openLink",
    "swipe",
    "repeat",
}


class FlowError(RuntimeError):
    """Raised when a flow is invalid or one of its steps fails."""


@dataclass(frozen=True)
class StepResult:
    index: int
    command: str
    passed: bool
    error: str | None = None


@dataclass
class FlowResult:
    path: Path
    total: int
    steps: list[StepResult] = field(default_factory=list)

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
        artifacts_dir: str | Path = "artifacts",
        poll_interval: float = 0.25,
        echo: Callable[[str], None] = print,
    ) -> None:
        self.driver = driver
        self.default_timeout = default_timeout
        self.artifacts_dir = Path(artifacts_dir)
        self.poll_interval = poll_interval
        self.echo = echo
        self._app_id: str | None = None
        self._transliterate: bool = False
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
        }

    # ------------------------------------------------------------------
    # Carregamento e validação
    # ------------------------------------------------------------------

    def load_flow(self, path: str | Path) -> tuple[dict[str, Any], list[Step]]:
        flow_path = Path(path)
        try:
            docs = list(yaml.safe_load_all(flow_path.read_text(encoding="utf-8")))
        except FileNotFoundError as exc:
            raise FlowError(f"Arquivo de fluxo não encontrado: {flow_path}") from exc
        except yaml.YAMLError as exc:
            raise FlowError(f"YAML inválido em {flow_path}: {exc}") from exc

        if len(docs) == 2 and isinstance(docs[0], dict) and isinstance(docs[1], list):
            config, raw_steps = docs
        elif (
            len(docs) == 1
            and isinstance(docs[0], dict)
            and isinstance(docs[0].get("steps"), list)
        ):
            config, raw_steps = docs[0], docs[0]["steps"]
        else:
            raise FlowError(
                "Formato esperado: cabeçalho com appId, separador '---' e lista de "
                "comandos; ou um objeto com 'appId' e 'steps'."
            )

        self._transliterate = bool(config.get("transliterate", False))

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
                self._parse_seconds(value)
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
        timeout = self._parse_seconds(
            selector.pop("timeout", self.default_timeout), name="timeout"
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
    def _parse_seconds(value: Any, name: str = "sleep") -> float:
        if isinstance(value, bool):
            raise FlowError(f"{name} deve ser um número de segundos ou milissegundos.")
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
                value = float(val_str)
            except ValueError:
                raise FlowError(
                    f"{name} deve ser um número de segundos ou milissegundos."
                ) from None

        if not isinstance(value, (int, float)) or value < 0:
            raise FlowError(f"{name} deve ser um número de segundos >= 0.")
        return float(value)

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
            timeout = self._parse_seconds(
                val.pop("timeout", self.default_timeout), name="timeout"
            )
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

    @staticmethod
    def _launch_target(value: Any, default: str | None) -> tuple[str, bool, bool]:
        """Retorna (appId, stopApp, clearState).

        Como no Maestro, stopApp é true por padrão.
        """
        stop_app: Any = True
        clear_state: Any = False
        if value is None:
            package = default
        elif isinstance(value, str):
            package = value
        elif isinstance(value, dict):
            package = value.get("appId", default)
            stop_app = value.get("stopApp", True)
            clear_state = value.get("clearState", False)
        else:
            raise FlowError(
                "launchApp: use '- launchApp', '- launchApp: <appId>' "
                "ou '- launchApp: {appId: ..., stopApp: true, clearState: false}'."
            )
        if not package:
            raise FlowError("launchApp: informe appId no cabeçalho do fluxo.")
        if not isinstance(stop_app, bool):
            raise FlowError("launchApp: stopApp deve ser true ou false.")
        if not isinstance(clear_state, bool):
            raise FlowError("launchApp: clearState deve ser true ou false.")
        return str(package), stop_app, clear_state

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

    def run(self, path: str | Path) -> FlowResult:
        flow_path = Path(path)
        config, steps = self.load_flow(flow_path)
        self._app_id = config.get("appId")
        self._transliterate = bool(config.get("transliterate", False))
        result = FlowResult(path=flow_path, total=len(steps))
        self.echo(f"AndroFlow: {flow_path} ({len(steps)} etapas)")
        for index, step in enumerate(steps, start=1):
            command, value = next(iter(step.items()))
            try:
                self.execute(command, value)
            except (FlowError, AndroidError, ValueError) as exc:
                error = str(exc)
            except Exception as exc:  # inesperado: mostra o tipo para depuração
                error = f"{type(exc).__name__}: {exc}"
            else:
                result.steps.append(StepResult(index, command, passed=True))
                self.echo(f"  PASS {index:02d} {command}")
                continue
            result.steps.append(StepResult(index, command, passed=False, error=error))
            self.echo(f"  FAIL {index:02d} {command}: {error}")
            self._capture_failure(flow_path, index)
            break
        self.echo(
            f"\nResultado: {result.passed} ok, {result.failed} falha(s), "
            f"{result.skipped} pulada(s) de {result.total} etapas."
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
        except (AndroidError, OSError) as exc:
            self.echo(f"       Não foi possível salvar artefatos da falha: {exc}")
            return
        self.echo(f"       Artefatos da falha: {png}, {xml}")

    # ------------------------------------------------------------------
    # Comandos
    # ------------------------------------------------------------------

    def _launch_app(self, value: Any) -> None:
        package, stop_app, clear_state = self._launch_target(value, self._app_id)
        if clear_state and hasattr(self.driver, "clear_app"):
            self.driver.clear_app(package)
        if stop_app:
            self.driver.stop_app(package)
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
        self.echo(f"       Screenshot: {path}")

    def _back(self, _value: Any) -> None:
        self.driver.back()

    def _sleep(self, value: Any) -> None:
        self.driver.wait(self._parse_seconds(value))

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
