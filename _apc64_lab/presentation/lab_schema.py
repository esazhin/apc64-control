"""docs/lab.schema.json, generated from the registered generators and schemes and the lab section's own keys, so
the schema cannot drift from the validator (contract T38; inv10). Regenerate with:

    python -m _apc64_lab.presentation.lab_schema

The schema describes one layout file with a 'lab:' section. The host's keys (devices, pages, banks, routing) keep
their meaning and point into docs/layout.schema.json. Each generator's parameters are allowed only with that
generator ('if generator is tonnetz, then base and channel'); a colour scheme's parameters (the scale scheme's
scale and root) are described in a branch of that scheme and may be written with any generator.
"""
import json
import sys
from pathlib import Path

from _apc64_host.notation.grammar import TOP_KEYS

from ..domain.bulk_edit import NAMED_COLOURS
from ..domain.generators import DEFAULT_SCHEME, ParamKind, ParamSpec
from ..domain.lab_section import OWN_KEYS, STRIP_KEYS
from ..domain.performer_block import ADDRESSING, KEYS as PERFORMER_KEYS, MAX_BPM, MIN_BPM, PLAY_MODES
from performer import CHORD_TYPES, DEFAULT_TYPES, KEY_TYPES

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs" / "lab.schema.json"
HOST_SCHEMA = "layout.schema.json"
NOTE_NAME_PATTERN = r"^[A-Ga-g][#b]?-?\d+$"
PITCH_CLASS_PATTERN = r"^[A-Ga-g](♯|#|♭|b|𝄪|𝄫)*$"
STRIP_KEY_PATTERN = r"^(strips? )?[1-8](-[1-8])?$"
HEX_PATTERN = r"^#?[0-9A-Fa-f]{6}$"


def param_schema(spec: ParamSpec) -> dict:
    doc = spec.doc or spec.name
    if spec.kind == ParamKind.CHOICE:
        return {"type": "string", "enum": list(spec.choices), "default": spec.default,
                "description": f"{doc}: one of the names listed (any case; spaces for '-' are accepted too)."}
    if spec.kind == ParamKind.NOTE_LIST:
        note = {"oneOf": [{"type": "integer", "minimum": 0, "maximum": 127},
                          {"type": "string", "pattern": NOTE_NAME_PATTERN}]}
        return {"oneOf": [{"type": "string", "enum": list(spec.choices)},
                          {"type": "array", "items": note, "minItems": spec.minimum, "maxItems": spec.maximum}],
                "default": spec.default,
                "description": f"{doc}: one of the names listed, or a list of {spec.minimum}–{spec.maximum} notes "
                               "(numbers 0–127 or names such as E1 (40), C3 = 60)."}
    if spec.kind == ParamKind.PITCH_CLASS:
        found = {"type": "string", "pattern": PITCH_CLASS_PATTERN,
                 "description": f"{doc}: a note name without octave such as D, F# or B♭."}
        if spec.default is not None:
            found["default"] = spec.default
        return found
    if spec.kind == ParamKind.NOTE:
        return {"oneOf": [{"type": "integer", "minimum": spec.minimum, "maximum": spec.maximum},
                          {"type": "string", "pattern": NOTE_NAME_PATTERN}],
                "default": spec.default,
                "description": f"{doc}: a note number {spec.minimum}–{spec.maximum} or a note name such as C2 "
                               "(48) or F#3 (66)."}
    return {"type": "integer", "minimum": spec.minimum, "maximum": spec.maximum, "default": spec.default,
            "description": f"{doc} ({spec.minimum}–{spec.maximum})."}


def generate(listing: dict | None = None) -> dict:
    """The schema for the generators and schemes in `listing` (GeneratorRegistry.listing(); the shipped ones by
    default). Broken plugins are left out: they can never be used."""
    if listing is None:
        listing = _shipped_listing()
    generators = [g for g in listing["generators"] if not g.get("broken")]
    working = [s for s in listing["schemes"] if not s.get("broken")]
    schemes = [s["name"] for s in working]
    colour = {"oneOf": [
        {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 255}, "minItems": 3, "maxItems": 3,
         "description": "[red, green, blue], each 0–255."},
        {"type": "string", "pattern": HEX_PATTERN, "description": "#RRGGBB."},
        {"type": "string", "enum": sorted(NAMED_COLOURS), "description": "A colour name."},
    ]}
    strip = {"type": "object", "required": ["cc"], "additionalProperties": False, "properties": {
        "cc": {"type": "integer", "minimum": 0, "maximum": 127,
               "description": "The controller (over a range 1-8 it rises by one per strip)."},
        "lsb": {"type": "integer", "minimum": 0, "maximum": 127,
                "description": "With lsb the strip sends 14-bit MSB/LSB pairs; it rises by one per strip too."},
        "channel": {"type": "integer", "minimum": 1, "maximum": 16, "default": 1},
        "ch": {"type": "integer", "minimum": 1, "maximum": 16, "description": "Same as channel."},
        "bar": {"$ref": "#/$defs/colour", "description": "Bar colour (default red)."},
        "indicator": {"$ref": "#/$defs/colour", "description": "Indicator colour (default white)."},
        "bipolar": {"type": "boolean", "default": False, "description": "Bipolar bar display."},
        "outputs": {"type": "integer", "minimum": 0, "maximum": 7, "default": 7,
                    "description": "Output bitmask: 7 = all outputs (factory), 0 = silent; the single bits are [TBD]."},
    }}
    assert set(strip["properties"]) == set(STRIP_KEYS), "the strip keys follow lab_section.STRIP_KEYS"
    switch = {"oneOf": [{"type": "boolean"}, {"type": "string", "enum": ["on", "off"]}]}
    performer = {"type": "object", "required": ["pattern"], "additionalProperties": False, "properties": {
        "pattern": {"type": "string", "description": "A pattern in patterns/: its file name without .yaml (travis) or "
                                                     "its name (docs/performer-format.md)."},
        "latch": {**switch, "default": "off", "description": "On: what was held keeps playing after release; the "
                                                              "unit's Play toggles it."},
        "play": {"type": "string", "enum": list(PLAY_MODES), "description": "Overrides the pattern's play mode: all "
                 "(every string plays at its hits, an unpressed one open) or pressed (only pressed strings)."},
        "tempo": {"oneOf": [{"type": "number", "minimum": MIN_BPM, "maximum": MAX_BPM}, {"const": "clock"}],
                  "default": 100, "description": "BPM (quarter notes a minute), or clock: follow the MIDI clock of "
                                                 "the 'clock' input."},
        "clock": {"type": "string", "description": "The MIDI input that sends the clock (with tempo: clock), as "
                                                   "'apc64 ports' lists it, or auto: the first input that sends one."},
        "addressing": {"type": "string", "enum": list(ADDRESSING), "description": "strings: lane k is string k "
                       "(a generator with a string per channel, the guitar; its default); voices: the k-th held note "
                       "from the top (the default elsewhere)."},
        "chords": {"type": "array", "minItems": 1, "maxItems": 8, "uniqueItems": True,
                   "items": {"type": ["string", "integer"], "enum": [*KEY_TYPES, *CHORD_TYPES, *[
                       int(n) for n in CHORD_TYPES if n.isdigit()]]},
                   "default": list(DEFAULT_TYPES), "description": "The chord types of the type pads, in order (a guitar "
                   "with 6 strings or fewer: the top row; 7 or 8 strings: Shift + a pad in the column). With one "
                   "chosen, a single note pressed is the root of that chord, voiced on the strings; key and key 7: "
                   "the key's own triad and seventh from that root (the key: the scheme's scale)."},
        "slots": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": ["string", "null"]},
                  "description": "The patterns of the slot pads, in order, ~ for an empty one (a guitar with 6 strings "
                  "or fewer: the bottom row; 7 strings: the top row; 8 strings: Shift + a pad on the top row)."},
    }, "description": "Optional (contract 2 §2.10): a performer pattern played over what is held; with it Play "
                      "toggles the latch and Stop stops the pattern. Do not bind play or stop on a page then."}
    assert set(performer["properties"]) == set(PERFORMER_KEYS), "the performer keys follow performer_block.KEYS"
    own = {
        "generator": {"type": "string", "enum": [g["name"] for g in generators],
                      "description": "Required: which generator fills the 64 pads."},
        "scheme": {"type": "string", "enum": schemes, "default": DEFAULT_SCHEME,
                   "description": "The colour scheme (any scheme works with any generator)."},
        "colours": {"type": "object", "propertyNames": {"pattern": PITCH_CLASS_PATTERN},
                    "additionalProperties": {"$ref": "#/$defs/colour"},
                    "description": "Rest colours by pitch class, over the scheme's: C: [255, 255, 255]."},
        "strips": {"type": "object", "propertyNames": {"pattern": STRIP_KEY_PATTERN},
                   "additionalProperties": {"$ref": "#/$defs/strip"},
                   "description": "Optional (§2.7 q6): strips 1-8 by number or range. Without it the unit's strips "
                                  "are written back exactly as read."},
        "performer": {"$ref": "#/$defs/performer"},
    }
    assert set(own) == set(OWN_KEYS), "the lab section's own keys follow lab_section.OWN_KEYS"
    params: dict = {}
    branches = []
    scheme_specs = {s["name"]: [_spec(p) for p in s.get("params", [])] for s in working}
    scheme_names = list(dict.fromkeys(spec.name for specs in scheme_specs.values() for spec in specs))
    for g in generators:
        specs = [_spec(p) for p in g["params"]]
        for spec in specs:
            params.setdefault(spec.name, {"description": f"A generator parameter (see the {g['name']} branch)."})
        branches.append({
            "if": {"properties": {"generator": {"const": g["name"]}}, "required": ["generator"]},
            "then": {"properties": {spec.name: param_schema(spec) for spec in specs},
                     "propertyNames": {"enum": [*OWN_KEYS, *(spec.name for spec in specs),
                                                *(n for n in scheme_names if n not in {x.name for x in specs})]}},
        })
    for name, specs in scheme_specs.items():
        if not specs:
            continue
        for spec in specs:
            params.setdefault(spec.name, {"description": f"A colour scheme parameter (see the {name} scheme's branch)."})
        branches.append({
            "if": {"properties": {"scheme": {"const": name}}, "required": ["scheme"]},
            "then": {"properties": {spec.name: param_schema(spec) for spec in specs}},
        })
    lab = {"type": "object", "required": ["generator"], "additionalProperties": False,
           "properties": {**own, **params}, "allOf": branches,
           "description": "A generated layout. Its encoder shifts the window one step of the interval "
                          "(right +1, left -1) and Tempo cycles octave → fifth → third, or the generator's own "
                          "steps (the guitar: Fret and Page); Shift + encoder still browses layouts. Do not bind "
                          "encoder or tempo on a page of a lab layout."}
    host = {key: {"$ref": f"{HOST_SCHEMA}#/properties/{key}"} for key in TOP_KEYS if key != "name"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://apc64-host.local/lab.schema.json",
        "title": "APC64 Lab generated layout",
        "description": "One layout file in layouts/ (YAML) with a 'lab:' section. Read docs/lab-guide.md for worked "
                       "examples; validate with 'apc64 lab validate <file>'. The host keys are as in "
                       "layout.schema.json; 'routing: custom:' overrides the lab's default note target.",
        "type": "object",
        "required": ["name", "lab"],
        "additionalProperties": False,
        "properties": {"name": {"type": "string", "description": "Display name (the OLED shows 14 characters)."},
                       "lab": {"$ref": "#/$defs/lab"}, **host},
        "$defs": {"lab": lab, "colour": colour, "strip": strip, "performer": performer},
    }


def _spec(p: dict) -> ParamSpec:
    return ParamSpec(p["name"], p["kind"], p["default"], p["min"], p["max"], p.get("doc", ""), tuple(p.get("choices", ())))


def _shipped_listing() -> dict:
    """The built-ins and the plugins shipped in _apc64_lab/generators (tooling: a composition of its own)."""
    from ..application.registry import GeneratorRegistry
    from ..infrastructure.plugin_discovery import PluginDiscovery
    return GeneratorRegistry(PluginDiscovery()).load().listing()


def render(listing: dict | None = None) -> str:
    return json.dumps(generate(listing), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":   # tooling: rewrite docs/lab.schema.json
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render())
    print(f"wrote {target}")
