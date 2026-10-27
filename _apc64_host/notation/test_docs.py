"""The shipped schema, guide and example layout (T8: A47, d183; schema generated from the grammar)."""
import re
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from _apc64_host.notation import schema
from _apc64_host.notation.compiler import compile_text

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "layout-guide.md"
EXAMPLES = re.findall(r"```yaml\n(.*?)```", GUIDE.read_text(), re.DOTALL)


def test_the_schema_file_is_generated_from_the_grammar():
    assert (ROOT / "docs" / "layout.schema.json").read_text() == schema.render()


def test_the_guide_has_worked_examples():
    assert len(EXAMPLES) >= 7


@pytest.mark.parametrize("number", range(len(EXAMPLES)))
def test_every_worked_example_in_the_guide_validates(number):   # A47, d183
    result = compile_text(EXAMPLES[number], f"example-{number}.yaml")
    assert result.valid, [i.message() for i in result.issues]


def _keys_follow_the_schema(text: str):
    """A small structural check of a layout against the schema's key patterns (no third-party validator)."""
    generated = schema.generate()
    data = YAML(typ="safe").load(text)
    assert set(data) <= set(generated["properties"]), set(data)
    page_pattern = re.compile(schema.PAGE_KEY_PATTERN)
    control = re.compile(schema.PAGE_CONTROL_PATTERN)
    strip = re.compile(schema.STRIP_CONTROL_PATTERN)
    for key, body in (data.get("pages") or {}).items():
        assert page_pattern.match(str(key)), key
        for entry in (body or {}):
            if entry == "shift":
                assert all(control.match(c) for c in body[entry] or {}), body[entry]
            else:
                assert entry == "name" or control.match(entry), entry
    for key, body in (data.get("banks") or {}).items():
        assert re.match(schema.BANK_KEY_PATTERN, str(key)), key
        for entry in (body or {}):
            if entry == "shift":
                assert all(strip.match(c) for c in body[entry] or {})
            else:
                assert entry == "name" or strip.match(entry), entry


@pytest.mark.parametrize("number", range(len(EXAMPLES)))
def test_every_worked_example_follows_the_schema_key_patterns(number):
    _keys_follow_the_schema(EXAMPLES[number])


def test_the_shipped_jam_layout_is_valid_and_matches_the_acceptance_setup():
    text = (ROOT / "layouts" / "jam.yaml").read_text()
    result = compile_text(text, "jam.yaml", ["MPC Live III MIDI 1"])
    assert result.valid and result.warnings == ()
    layout = result.layout
    assert layout.display_name == "Jam" and layout.page(1).name == "Drums" and layout.bank(1).name == "Mix"
    assert "notes" in layout.routing
    _keys_follow_the_schema(text)


def test_the_eight_line_minimal_example_is_eight_lines():   # d182
    assert len(EXAMPLES[0].strip().splitlines()) <= 8
