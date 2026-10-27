"""T38: docs/lab.schema.json is generated from the registered generators and the lab section's keys (inv10)."""
import json

from _apc64_lab.application.registry import GeneratorRegistry
from _apc64_lab.domain.generators import ParamKind, ParamSpec
from _apc64_lab.domain.lab_section import OWN_KEYS, STRIP_KEYS
from _apc64_lab.presentation import lab_schema


def test_the_committed_schema_is_the_generated_one():
    assert lab_schema.SCHEMA_PATH.read_text() == lab_schema.render(), \
        "regenerate: python -m _apc64_lab.presentation.lab_schema"


def test_it_names_the_shipped_generators_and_schemes_with_their_parameters():   # A17
    lab = lab_schema.generate()["$defs"]["lab"]
    assert lab["properties"]["generator"]["enum"] == ["tonnetz", "isomorphic", "guitar", "modes"]
    assert lab["properties"]["scheme"]["enum"] == ["fifths", "root-highlight", "scale"]
    branches = {b["if"]["properties"]["generator"]["const"]: b["then"] for b in lab["allOf"]
                if "generator" in b["if"]["properties"]}
    assert set(branches["tonnetz"]["properties"]) == {"base", "channel"}
    assert set(branches["isomorphic"]["properties"]) == {"base", "column", "row", "channel"}
    assert branches["isomorphic"]["properties"]["row"] | {} == {
        "type": "integer", "minimum": -12, "maximum": 12, "default": 5,
        "description": "semitones per row upwards (-12–12)."}
    assert branches["tonnetz"]["propertyNames"]["enum"] == [*OWN_KEYS, "base", "channel", "scale", "root"]
    assert set(branches["modes"]["properties"]) == {"base", "channel"}
    tuning = branches["guitar"]["properties"]["tuning"]   # a preset or a list of 4–8 notes (the guitar amendment)
    assert tuning["oneOf"][0]["enum"][:2] == ["e-standard", "drop-d"] and tuning["default"] == "e-standard"
    assert (tuning["oneOf"][1]["minItems"], tuning["oneOf"][1]["maxItems"]) == (4, 8)
    assert set(branches["guitar"]["properties"]) == {"tuning", "frets", "fret_marks"}
    scale = next(b["then"] for b in lab["allOf"] if b["if"]["properties"].get("scheme", {}).get("const") == "scale")
    assert scale["properties"]["scale"]["enum"][:3] == ["chromatic", "major", "melodic-minor"]
    assert scale["properties"]["scale"]["default"] == "major"
    assert scale["properties"]["root"]["type"] == "string" and "default" not in scale["properties"]["root"]
    assert set(lab_schema.generate()["$defs"]["strip"]["properties"]) == set(STRIP_KEYS)
    assert lab["required"] == ["generator"] and lab["additionalProperties"] is False


class WickiHayden:
    name = "wicki-hayden"
    params = (ParamSpec("base", ParamKind.NOTE, 48, 0, 127, "note on pad r1c1"),)

    def notes(self, params):
        return tuple(params["base"] + 2 * x + 5 * r for r in range(8) for x in range(8))


class Source:
    def __init__(self, *found):
        self.found = found

    def discover(self):
        return list(self.found)


def test_a_new_generator_file_appears_in_the_schema_and_a_broken_one_does_not():   # A18, A19
    from _apc64_lab.application.ports import DiscoveryError
    listing = GeneratorRegistry(Source(("_apc64_lab/generators/wicki_hayden.py", WickiHayden()),
                                       ("_apc64_lab/generators/spiral.py", DiscoveryError("division by zero")))
                                ).load().listing()
    schema = lab_schema.generate(listing)
    lab = schema["$defs"]["lab"]
    assert lab["properties"]["generator"]["enum"] == ["tonnetz", "isomorphic", "wicki-hayden"]
    assert "spiral" not in json.dumps(schema)
    assert [b["if"]["properties"]["generator"]["const"] for b in lab["allOf"]] == ["tonnetz", "isomorphic",
                                                                                  "wicki-hayden"]   # built-ins only


def test_the_host_keys_point_into_the_host_schema():
    schema = lab_schema.generate()
    assert schema["required"] == ["name", "lab"]
    assert schema["properties"]["routing"] == {"$ref": "layout.schema.json#/properties/routing"}
    assert set(schema["properties"]) == {"name", "lab", "device", "devices", "pages", "banks", "routing"}
