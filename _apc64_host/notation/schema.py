"""docs/layout.schema.json, generated from the grammar tables and SURFACE so the schema cannot drift from the
validator. Regenerate with:  python -m _apc64_host.notation.schema
"""
import json
import re
import sys
from pathlib import Path

from ..domain.controls import SURFACE, ControlRole, Strip, StripTouch
from ..domain.layout import MAX_BANKS, MAX_PAGES
from ..domain.palette import ALIASES, NAMES
from .grammar import (
    AFTERTOUCH_WORDS, BINDING_KEYS, CANONICAL_WORD, DEVICE_KEYS, MESSAGE_WORDS, NAMED_BUTTONS, OPTION_WORDS,
    ROUTING_FIELDS, ROUTING_KEYS, TOP_KEYS,
)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs" / "layout.schema.json"

PAGE_KEY_PATTERN = rf"^(page )?[1-{MAX_PAGES}]( .+)?$"
BANK_KEY_PATTERN = rf"^(bank )?[1-{MAX_BANKS}]( .+)?$"
DEVICE_NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]*$"
PAGE_CONTROL_PATTERN = ("^(pads? r[1-8]c[1-8](-r[1-8]c[1-8])?|(tracks?|trackctls?) [1-8](-[1-8])?|"
                        + "|".join(re.escape(n) for n in NAMED_BUTTONS) + ")$")
STRIP_CONTROL_PATTERN = r"^strips? [1-8](-[1-8])?$"
PHRASE_PATTERN = "^(none|(" + "|".join(sorted(MESSAGE_WORDS, key=len, reverse=True)) + r")(\s.*)?)$"


def _page_controls() -> list[str]:
    return [e.name for e in SURFACE if e.role is ControlRole.BINDABLE and not isinstance(e.id, (Strip, StripTouch))]


def generate() -> dict:
    phrase = {"type": "string", "pattern": PHRASE_PATTERN,
              "description": "A binding phrase: a message (note 36, notes from 36, cc 20, cc 20-27, cc14 20, "
                             "program 5, pitchbend), then 'on <device>', 'ch <1-16>', options; 'none' unbinds."}
    binding = {"oneOf": [
        phrase,
        {"type": "array", "items": phrase, "minItems": 1,
         "description": "Several messages, sent in the written order."},
        {"type": "object", "required": ["send"], "additionalProperties": False,
         "properties": {key: ({"oneOf": [phrase, {"type": "array", "items": phrase}]} if key == "send" else
                              {"type": ["string", "integer", "boolean"]}) for key in BINDING_KEYS},
         "description": "The same words as the phrase, as keys: {send: note 36, colour: red, toggle: true}."},
    ]}
    layer = {"type": ["object", "null"], "additionalProperties": False,
             "patternProperties": {PAGE_CONTROL_PATTERN: {"$ref": "#/$defs/binding"}}}
    page = {"type": ["object", "null"], "additionalProperties": False,
            "properties": {"name": {"type": "string"}, "shift": {"$ref": "#/$defs/pageLayer"}},
            "patternProperties": {PAGE_CONTROL_PATTERN: {"$ref": "#/$defs/binding"}}}
    strip_layer = {"type": ["object", "null"], "additionalProperties": False,
                   "patternProperties": {STRIP_CONTROL_PATTERN: {"$ref": "#/$defs/binding"}}}
    bank = {"type": ["object", "null"], "additionalProperties": False,
            "properties": {"name": {"type": "string"}, "shift": {"$ref": "#/$defs/bankLayer"}},
            "patternProperties": {STRIP_CONTROL_PATTERN: {"$ref": "#/$defs/binding"}}}
    route = {"oneOf": [
        {"type": "string", "description": "'<device> ch <n> aftertouch pass|pressure|drop transpose <n> "
                                          "remap <a>><b> …'"},
        {"type": "object", "additionalProperties": False,
         "properties": {k: {"type": ["string", "integer", "object"]} for k in ROUTING_FIELDS}},
    ]}
    device = {"oneOf": [
        {"type": "string", "description": "The ALSA port name, or a unique part of it."},
        {"type": "object", "required": ["port"], "additionalProperties": False,
         "properties": {"port": {"type": "string"},
                        **{k: {"type": "integer", "minimum": 1, "maximum": 16} for k in DEVICE_KEYS if k != "port"}}},
    ]}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://apc64-host.local/layout.schema.json",
        "title": "APC64 Host layout",
        "description": "One layout file in layouts/ (YAML). Read docs/layout-guide.md for the phrases and worked "
                       "examples; validate with 'apc64 validate <file>'.",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string", "description": "Display name (the OLED shows 14 ASCII characters)."},
            "device": {"type": "string", "pattern": DEVICE_NAME_PATTERN,
                       "description": "The default device for bindings without 'on <device>'."},
            "devices": {"type": "object", "additionalProperties": False,
                        "patternProperties": {DEVICE_NAME_PATTERN: device}},
            "pages": {"type": "object", "additionalProperties": False,
                      "patternProperties": {PAGE_KEY_PATTERN: {"$ref": "#/$defs/page"}}},
            "banks": {"type": "object", "additionalProperties": False,
                      "patternProperties": {BANK_KEY_PATTERN: {"$ref": "#/$defs/bank"}}},
            "routing": {"type": "object", "additionalProperties": False,
                        "properties": {k: {"$ref": "#/$defs/route"} for k in ROUTING_KEYS}},
        },
        "$defs": {"binding": binding, "page": page, "pageLayer": layer, "bank": bank, "bankLayer": strip_layer,
                  "route": route},
        "x-apc64": {
            "topLevelKeys": list(TOP_KEYS),
            "pageControls": _page_controls(),
            "stripControls": [f"strip {n}" for n in range(1, 9)],
            "rangeForms": ["pads r1c1-r2c8 (reading order from the bottom-left)", "tracks 1-8", "trackctls 1-8",
                           "strips 1-8"],
            "messages": sorted(set(CANONICAL_WORD.values()) | {"notes", "none"}),
            "options": list(OPTION_WORDS),
            "colours": {**NAMES, **ALIASES},
            "aftertouch": sorted(set(AFTERTOUCH_WORDS.values())),
            "noteNames": "C3 = 60, so C1 = 36 and C-2 = 0 (Ableton/Akai/MPC convention)",
            "channels": "1-16",
            "limits": {"pages": MAX_PAGES, "banks": MAX_BANKS},
        },
    }


def render() -> str:
    return json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":   # tooling: rewrite docs/layout.schema.json
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render())
    print(f"wrote {target}")
