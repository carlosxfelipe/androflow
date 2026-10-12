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
_VALUE_REQUIRED = _SELECTOR_COMMANDS | {"inputText", "takeScreenshot", "sleep"}


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
        self._handlers: dict[str, Callable[[Any], None]] = {
            "launchApp": self._launch_app,
            "tapOn": self._tap_on,
            "inputText": self._input_text,
            "assertVisible": self._assert_visible,
            "assertNotVisible": self._assert_not_visible,
            "waitFor": self._wait_for,
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
            available = ", ".join(self._handlers)
            raise FlowError(
                f"Etapa {index}: comando desconhecido '{command}'. "
                f"Disponíveis: {available}."
            )
        if command in _VALUE_REQUIRED and value is None:
            raise FlowError(f"Etapa {index} ({command}): informe um valor.")
        try:
            if command == "tapOn" and self._parse_point(value) is not None:
                return
            if command in _SELECTOR_COMMANDS:
                self._parse_selector(command, value)
            elif command == "launchApp":
                self._launch_target(value, app_id)
            elif command == "inputText":
                self._parse_text(value)
            elif command == "sleep":
                self._parse_seconds(value)
            elif command == "takeScreenshot" and not (
                isinstance(value, str) and value.strip()
            ):
                raise FlowError("takeScreenshot: informe o nome do arquivo.")
        except FlowError as exc:
            raise FlowError(f"Etapa {index}: {exc}") from exc

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
    def _parse_point(value: Any) -> tuple[int, int] | None:
        if not (isinstance(value, dict) and "point" in value):
            return None
        point = value["point"]
        if not (
            isinstance(point, list)
            and len(point) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in point)
        ):
            raise FlowError("tapOn: point deve ser [x, y] com números inteiros.")
        return point[0], point[1]

    @staticmethod
    def _parse_seconds(value: Any, name: str = "sleep") -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise FlowError(f"{name} deve ser um número de segundos >= 0.")
        return float(value)

    @staticmethod
    def _parse_text(value: Any) -> str:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise FlowError(
                "inputText deve ser um texto (use aspas em valores como yes/no)."
            )
        return str(value)

    @staticmethod
    def _launch_target(value: Any, default: str | None) -> tuple[str, bool]:
        """Retorna (appId, stopApp). Como no Maestro, stopApp é true por padrão."""
        stop_app: Any = True
        if value is None:
            package = default
        elif isinstance(value, str):
            package = value
        elif isinstance(value, dict):
            package = value.get("appId", default)
            stop_app = value.get("stopApp", True)
        else:
            raise FlowError(
                "launchApp: use '- launchApp', '- launchApp: <appId>' "
                "ou '- launchApp: {appId: ..., stopApp: true}'."
            )
        if not package:
            raise FlowError("launchApp: informe appId no cabeçalho do fluxo.")
        if not isinstance(stop_app, bool):
            raise FlowError("launchApp: stopApp deve ser true ou false.")
        return str(package), stop_app

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
        package, stop_app = self._launch_target(value, self._app_id)
        if stop_app:
            self.driver.stop_app(package)
        self.driver.launch_app(package)

    def _tap_on(self, value: Any) -> None:
        point = self._parse_point(value)
        if point is None:
            selector, timeout = self._parse_selector("tapOn", value)
            element = self._find(selector, timeout)
            if element is None:
                raise FlowError(f"Elemento não encontrado: {selector}")
            point = element.center
        self.driver.tap(*point)

    def _input_text(self, value: Any) -> None:
        self.driver.type_text(self._parse_text(value))

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
