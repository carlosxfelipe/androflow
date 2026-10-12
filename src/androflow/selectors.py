from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UiElement:
    text: str
    resource_id: str
    content_desc: str
    bounds: tuple[int, int, int, int]
    clickable: bool
    visible: bool

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2


_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

# Chave do seletor no YAML -> atributo de UiElement.
MATCH_KEYS: dict[str, str] = {
    "text": "text",
    "resourceId": "resource_id",
    "id": "resource_id",
    "contentDesc": "content_desc",
}
OPTION_KEYS = frozenset({"contains", "visible", "regex"})


def _bool(value: str | None) -> bool:
    return (value or "").lower() == "true"


def parse_elements(root: ET.Element) -> list[UiElement]:
    elements: list[UiElement] = []
    for node in root.iter():
        match = _BOUNDS_RE.fullmatch(node.attrib.get("bounds", ""))
        if not match:
            continue
        x1, y1, x2, y2 = (int(v) for v in match.groups())
        elements.append(
            UiElement(
                text=node.attrib.get("text", ""),
                resource_id=node.attrib.get("resource-id", ""),
                content_desc=node.attrib.get("content-desc", ""),
                bounds=(x1, y1, x2, y2),
                clickable=_bool(node.attrib.get("clickable")),
                visible=_bool(node.attrib.get("displayed-to-user", "true"))
                and x2 > x1
                and y2 > y1,
            )
        )
    return elements


def validate_selector(selector: dict[str, Any]) -> None:
    """Valida as chaves do seletor, rejeitando chaves desconhecidas (ex.: typos)."""
    unknown = set(selector) - MATCH_KEYS.keys() - OPTION_KEYS
    if unknown:
        allowed = ", ".join([*MATCH_KEYS, *sorted(OPTION_KEYS)])
        raise ValueError(
            f"Chave(s) de seletor desconhecida(s): {', '.join(sorted(unknown))}. "
            f"Permitidas: {allowed}."
        )
    if not any(key in selector for key in MATCH_KEYS):
        raise ValueError(
            "Seletor precisa conter 'text', 'resourceId', 'id' ou 'contentDesc'."
        )


def _matches(
    element: UiElement,
    attr: str,
    expected: str,
    contains: bool,
    regex: bool = False,
) -> bool:
    actual = getattr(element, attr)
    if attr == "resource_id" and "/" not in expected:
        actual = actual.rsplit("/", 1)[-1]
    if regex:
        try:
            return bool(re.search(expected, actual))
        except re.error:
            return False
    return expected in actual if contains else expected == actual


def find_element(
    elements: list[UiElement],
    selector: dict[str, Any],
) -> UiElement | None:
    validate_selector(selector)
    active = [
        (attr, str(selector[key]))
        for key, attr in MATCH_KEYS.items()
        if key in selector
    ]
    contains = bool(selector.get("contains", False))
    regex = bool(selector.get("regex", False))
    visible_only = bool(selector.get("visible", True))
    for element in elements:
        if visible_only and not element.visible:
            continue
        if all(
            _matches(element, attr, expected, contains, regex)
            for attr, expected in active
        ):
            return element
    return None
