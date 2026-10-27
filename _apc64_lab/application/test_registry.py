"""T23: the generator registry over a GeneratorSource double (s17 collaboration, s33 supplier; A11, A17–A20, d13–d15)."""
import logging

import pytest

from _apc64_host.domain.issues import DomainInvariantError
from _apc64_lab.application.ports import DiscoveryError
from _apc64_lab.application.registry import BUILTIN_FILE, DefinitionIndex, GeneratorRegistry
from _apc64_lab.domain.generators import ParamKind, ParamSpec, TonnetzCheckerboard
from _apc64_lab.domain.lab_section import LabDefinition
from _apc64_lab.domain.pads import WHITE, Rgb
from _apc64_lab.domain.records import refusal_text


class WickiHayden:
    name = "wicki-hayden"
    params = (ParamSpec("base", ParamKind.NOTE, 36, 0, 127, "note on pad r1c1"),)

    def notes(self, params):
        return tuple(params["base"] + 2 * x + 5 * r for r in range(8) for x in range(8))


class Spiral:
    name = "spiral"
    params = ()

    def notes(self, params):
        return 1 / 0


class Short:
    name = "short"
    params = ()

    def notes(self, params):
        return (60,) * 12


class Grey:
    name = "grey"

    def colour(self, note, root):
        return Rgb(40, 40, 40), WHITE


class Source:
    def __init__(self, found):
        self.found, self.calls = found, 0

    def discover(self):
        self.calls += 1
        return list(self.found)


PLUGINS = [("_apc64_lab/generators/grey.py", Grey()),
           ("_apc64_lab/generators/spiral.py", Spiral()),
           ("_apc64_lab/generators/tonnetz_again.py", TonnetzCheckerboard()),
           ("_apc64_lab/generators/wicki_hayden.py", WickiHayden()),
           ("_apc64_lab/generators/short.py", Short()),
           ("_apc64_lab/generators/typo.py", DiscoveryError("name 'colur' is not defined"))]


def loaded(found=PLUGINS):
    return GeneratorRegistry(Source(found)).load()


def test_the_shipped_generators_are_listed_with_their_parameters():   # A17, d11
    registry = GeneratorRegistry().load()
    listing = registry.listing()
    assert [g["name"] for g in listing["generators"]] == ["tonnetz", "isomorphic"]
    tonnetz = listing["generators"][0]
    assert [p["name"] for p in tonnetz["params"]] == ["base", "channel"] and "broken" not in tonnetz
    assert [s["name"] for s in listing["schemes"]] == ["fifths"]


def test_a_new_generator_file_appears_with_its_parameters():   # A18, d12
    registry = loaded()
    wicki = next(g for g in registry.listing()["generators"] if g["name"] == "wicki-hayden")
    assert wicki["params"][0]["name"] == "base" and wicki["file"].endswith("wicki_hayden.py")
    assert "wicki-hayden" in registry.generators() and "grey" in registry.schemes()


def test_a_failing_generator_is_listed_broken_and_the_others_work():   # A19, d13
    registry = loaded()
    spiral = next(g for g in registry.listing()["generators"] if g["name"] == "spiral")
    assert spiral["broken"] is True and spiral["error"] == "division by zero"
    short = next(g for g in registry.listing()["generators"] if g["name"] == "short")
    assert short["error"] == "returned 12 pads, expected 64"
    typo = next(g for g in registry.listing()["generators"] if g["name"] == "typo")
    assert typo["broken"] and typo["error"] == "name 'colur' is not defined"
    assert set(registry.generators()) == {"tonnetz", "isomorphic", "wicki-hayden"}
    definition = LabDefinition("tonnetz", (("base", 48), ("channel", 1)))
    assert definition.grid(registry.generators(), registry.schemes()).note_at(1, 1) == 48   # Tonnetz C still works


def test_a_duplicate_name_is_refused_naming_both_files(caplog):   # A20, d14
    with caplog.at_level(logging.WARNING):
        registry = loaded()
    assert registry.refusals == (
        f'two generators are named "tonnetz": {BUILTIN_FILE} and _apc64_lab/generators/tonnetz_again.py; '
        "the second is refused",)
    assert registry.listing()["refusals"] == list(registry.refusals) and "tonnetz_again.py" in caplog.text
    assert registry.generators()["tonnetz"] is not PLUGINS[2][1]          # the first one stays


def test_an_unknown_name_lists_the_available_ones():   # A11, d6
    with pytest.raises(DomainInvariantError) as error:
        GeneratorRegistry().load().generator("tonetz")
    assert refusal_text(error.value) == 'no generator "tonetz"; available: isomorphic, tonnetz'


def test_discovery_runs_once_at_start():   # s17.c1, d15
    source = Source(PLUGINS)
    registry = GeneratorRegistry(source).load()
    registry.generators(), registry.listing()
    assert source.calls == 1


def test_the_definition_index_resolves_by_id_or_name():
    index = DefinitionIndex()
    definition = LabDefinition("tonnetz", (("base", 48), ("channel", 1)))
    index.record("tonnetz-c", definition)
    assert index.resolve("tonnetz-c").name == "tonnetz-c"
    index.named("tonnetz-c", "Tonnetz C")
    assert index.resolve("tonnetz c").definition == definition and index.resolve("Jam") is None
