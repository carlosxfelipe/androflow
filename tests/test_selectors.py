import xml.etree.ElementTree as ET

import pytest

from androflow.selectors import find_element, parse_elements


def test_find_element_by_exact_text_and_resource_id_suffix():
    root = ET.fromstring(
        '<hierarchy><node text="Entrar" resource-id="com.demo:id/login" '
        'content-desc="" bounds="[10,20][110,70]" clickable="true" '
        'displayed-to-user="true" /></hierarchy>'
    )
    elements = parse_elements(root)
    assert find_element(elements, {"text": "Entrar"}).bounds == (10, 20, 110, 70)
    assert find_element(elements, {"resourceId": "login"}) is not None
    assert find_element(elements, {"text": "Sair"}) is None


def test_contains_selector():
    root = ET.fromstring(
        '<hierarchy><node text="Bem-vindo de volta" resource-id="" '
        'content-desc="" bounds="[0,0][100,50]" displayed-to-user="true" /></hierarchy>'
    )
    assert find_element(parse_elements(root), {"text": "Bem-vindo", "contains": True})


def test_rejects_unknown_selector_key():
    with pytest.raises(ValueError, match="txt"):
        find_element([], {"txt": "Entrar"})


def test_rejects_selector_without_match_key():
    with pytest.raises(ValueError, match="precisa conter"):
        find_element([], {"contains": True})


def test_element_center():
    root = ET.fromstring('<hierarchy><node bounds="[10,20][110,70]" /></hierarchy>')
    assert parse_elements(root)[0].center == (60, 45)
