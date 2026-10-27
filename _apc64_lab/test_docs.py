"""T42: the lab's documents hold (inv10, inv14; contract 1's A47 check for the lab).

- every YAML example in docs/lab-guide.md validates, and its lab keys follow docs/lab.schema.json;
- every error line the guide quotes is the validator's own text;
- the guide's plugin example is a working generator;
- layouts/tonnetz-c.yaml and layouts/fourths.yaml validate as written and play as A8/A9 say;
- docs/lab-api.md names every /api/lab route and every `apc64 lab` command.
"""
import argparse
import re
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from _apc64_host.domain.controls import PadPos
from _apc64_host.notation.compiler import compile_text
from _apc64_lab.application.registry import GeneratorRegistry
from _apc64_lab.application.section_compiler import LabSectionCompiler
from _apc64_lab.domain.pads import WHITE
from _apc64_lab.infrastructure.plugin_discovery import PluginDiscovery
from _apc64_lab.presentation import lab_schema
from _apc64_lab.presentation.api import LabServices, lab_router
from _apc64_lab.presentation.cli import LabCli

ROOT = Path(__file__).resolve().parents[1]
GUIDE = (ROOT / "docs" / "lab-guide.md").read_text()
API = (ROOT / "docs" / "lab-api.md").read_text()
EXAMPLES = re.findall(r"```yaml\n(.*?)```", GUIDE, re.DOTALL)
PORTS = ["MPC Live III MIDI 1", "Bitwig Studio In"]
REGISTRY = GeneratorRegistry(PluginDiscovery()).load()


def compiled(text, file="example.yaml"):
    return compile_text(text, file, PORTS, sections={"lab": LabSectionCompiler(REGISTRY.generators, REGISTRY.schemes)})


def test_the_guide_has_worked_examples():
    assert len(EXAMPLES) >= 8


@pytest.mark.parametrize("number", range(len(EXAMPLES)))
def test_every_worked_example_validates(number):
    result = compiled(EXAMPLES[number], f"example-{number}.yaml")
    assert result.valid, [i.message() for i in result.issues]
    assert result.warnings == (), [w.message() for w in result.warnings]


@pytest.mark.parametrize("number", range(len(EXAMPLES)))
def test_every_worked_example_follows_the_schema(number):
    data = YAML(typ="safe").load(EXAMPLES[number])
    schema = lab_schema.generate(REGISTRY.listing())
    assert set(data) <= set(schema["properties"]) and set(schema["required"]) <= set(data)
    lab = data["lab"]
    branch = next(b["then"] for b in schema["$defs"]["lab"]["allOf"]
                  if b["if"]["properties"]["generator"]["const"] == lab["generator"])
    assert set(lab) <= set(branch["propertyNames"]["enum"]), set(lab)
    assert lab.get("scheme", "fifths") in schema["$defs"]["lab"]["properties"]["scheme"]["enum"]


ERROR_CASES = [
    "name: T\nlab:\n  base: 110\n  generator: tonnetz\n",
    "name: T\nlab:\n  generator: tonetz\n",
    "name: T\nlab:\n  generator: tonnetz\n  scheme: rainbow\n",
    "name: T\nlab:\n  generator: tonnetz\n  colours:\n    D: [0, 0, 0]\n    C: [300, 0, 0]\n",
    "name: T\nlab:\n  generator: tonnetz\n  colour: red\n",
    "name: T\nlab:\n  generator: tonnetz\n  strips:\n    9: {cc: 20}\n",
    "name: T\nlab:\n  generator: tonnetz\n  strips:\n    1-4: cc 20\n",
    "name: T\nlab:\n  base: 48\n",
    "name: T\ndevices:\n  mpc: MPC Live III MIDI 1\nlab:\n  generator: tonnetz\npages:\n  1:\n    encoder: cc 30 on mpc\n",
]


def test_every_error_the_guide_quotes_is_the_validators_text():   # A10, A11, A12
    produced = {i.message() for case in ERROR_CASES for i in compiled(case, "tonnetz-c.yaml").issues}
    quoted = [line for block in re.findall(r"```text\n(.*?)```", GUIDE, re.DOTALL) for line in block.splitlines()
              if line.startswith("tonnetz-c.yaml")]
    assert len(quoted) >= 9
    assert [line for line in quoted if line not in produced] == []


def test_the_guides_plugin_example_is_a_working_generator():   # A18
    code = re.search(r"```python\n(.*?)```", GUIDE, re.DOTALL).group(1)
    namespace = {}
    exec(compile(code, "wicki_hayden.py", "exec"), namespace)

    class Source:
        def discover(self):
            return [("_apc64_lab/generators/wicki_hayden.py", namespace["GENERATOR"])]
    registry = GeneratorRegistry(Source()).load()
    listed = {e.name: e for e in registry.listed()}
    assert not listed["wicki-hayden"].broken and "wicki-hayden" in registry.generators()


def test_the_shipped_tonnetz_c_layout_validates_and_plays_as_a8_says():
    result = compiled((ROOT / "layouts" / "tonnetz-c.yaml").read_text(), "tonnetz-c.yaml")
    assert result.valid and result.warnings == () and result.layout.display_name == "Tonnetz C"
    grid = result.layout.section("lab").grid(REGISTRY.generators(), REGISTRY.schemes())
    assert grid.at(PadPos(1, 1)).note == 48 and grid.at(PadPos(1, 1)).rest == WHITE
    assert grid.at(PadPos(1, 3)).note == 55 and grid.at(PadPos(2, 2)).note == 52
    assert grid.at(PadPos(1, 2)).silent and grid.at(PadPos(2, 1)).silent
    assert "custom" in {str(k).lower() for k in result.layout.routing}


def test_the_shipped_fourths_layout_validates_and_plays_as_a9_says():
    result = compiled((ROOT / "layouts" / "fourths.yaml").read_text(), "fourths.yaml")
    assert result.valid and result.warnings == () and result.layout.display_name == "Fourths"
    grid = result.layout.section("lab").grid(REGISTRY.generators(), REGISTRY.schemes())
    notes = {pos: grid.at(PadPos(*pos)).note for pos in ((1, 1), (1, 2), (2, 1), (8, 8), (1, 6))}
    assert notes == {(1, 1): 36, (1, 2): 37, (2, 1): 41, (8, 8): 78, (1, 6): 41}
    pads = [grid.at(PadPos(r, c)) for r in range(1, 9) for c in range(1, 9)]
    assert not any(p.silent for p in pads)
    by_pc = {}
    for pad in pads:
        by_pc.setdefault(pad.note % 12, set()).add(pad.rest)
    assert all(len(colours) == 1 for colours in by_pc.values())


def test_the_api_document_names_every_route():
    class Nothing:
        pass
    router = lab_router(LabServices(Nothing(), Nothing(), Nothing(), Nothing()))
    routes = {(method, route.path) for route in router.routes for method in route.methods}
    missing = [f"{m} {p}" for m, p in sorted(routes)
               if f"`{m} {p}" not in API and not (m == "GET" and f"`GET {p}`" in API)]
    assert len(routes) >= 20 and missing == []


def test_the_api_document_names_every_command():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    LabCli().register(sub, argparse.ArgumentParser(add_help=False))
    lab = sub.choices["lab"]
    commands = next(a for a in lab._actions if isinstance(a, argparse._SubParsersAction)).choices
    assert [c for c in commands if f"`apc64 lab {c}" not in API] == []
