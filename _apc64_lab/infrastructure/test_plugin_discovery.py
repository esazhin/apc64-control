"""T33: plugin discovery over a temporary plugin package and the shipped one (s17 supplier, s18 collaboration;
A18–A20 through the registry; d12, d15)."""
import sys
import textwrap

import pytest

from _apc64_lab.application.ports import DiscoveryError, GeneratorSource
from _apc64_lab.application.registry import GeneratorRegistry
from _apc64_lab.infrastructure.plugin_discovery import PluginDiscovery

WICKI = """
from _apc64_lab.domain.generators import ParamKind, ParamSpec

class WickiHayden:
    name = "wicki-hayden"
    params = (ParamSpec("base", ParamKind.NOTE, 36, 0, 127, "note on pad r1c1"),)

    def notes(self, params):
        return tuple(params["base"] + 2 * x + 5 * r for r in range(8) for x in range(8))

GENERATOR = WickiHayden()
"""
GREY = """
from _apc64_lab.domain.pads import WHITE, Rgb

class Grey:
    name = "grey"

    def colour(self, note, root):
        return Rgb(40, 40, 40), WHITE

SCHEME = Grey()
"""
SPIRAL = """
class Spiral:
    name = "spiral"
    params = ()

    def notes(self, params):
        return 1 / 0

GENERATOR = Spiral()
"""


@pytest.fixture
def plugins(tmp_path, monkeypatch):
    package = tmp_path / "lab_plugins_t33"
    package.mkdir()
    (package / "__init__.py").write_text("")
    files = {"a_wicki_hayden.py": WICKI, "b_grey.py": GREY, "c_raising.py": "raise RuntimeError('broken on import')\n",
             "d_empty.py": "X = 1\n", "e_spiral.py": SPIRAL, "f_tonnetz_again.py":
             "from _apc64_lab.domain.generators import TonnetzCheckerboard\nGENERATOR = TonnetzCheckerboard()\n",
             "test_skipped.py": "raise AssertionError('tests are never imported')\n"}
    for name, text in files.items():
        (package / name).write_text(textwrap.dedent(text))
    monkeypatch.syspath_prepend(str(tmp_path))
    yield PluginDiscovery("lab_plugins_t33")
    for name in [m for m in sys.modules if m.startswith("lab_plugins_t33")]:
        del sys.modules[name]


def test_each_file_gives_its_object_or_an_error_in_file_order(plugins):   # s17.c2, s18.c2
    assert isinstance(plugins, GeneratorSource)
    found = plugins.discover()
    assert [f for f, _ in found] == [f"lab_plugins_t33/{n}.py" for n in
                                     ("a_wicki_hayden", "b_grey", "c_raising", "d_empty", "e_spiral", "f_tonnetz_again")]
    objects = dict(found)
    assert objects["lab_plugins_t33/a_wicki_hayden.py"].name == "wicki-hayden"
    assert objects["lab_plugins_t33/b_grey.py"].name == "grey"
    assert objects["lab_plugins_t33/c_raising.py"] == DiscoveryError("broken on import")
    assert objects["lab_plugins_t33/d_empty.py"] == DiscoveryError("exposes neither GENERATOR nor SCHEME")


def test_the_registry_over_real_discovery(plugins):   # A18, A19, A20
    registry = GeneratorRegistry(plugins).load()
    listing = {g["name"]: g for g in registry.listing()["generators"]}
    assert listing["wicki-hayden"]["params"][0]["name"] == "base"
    assert listing["spiral"]["error"] == "division by zero"
    assert listing["c_raising"]["error"] == "broken on import"
    assert registry.refusals == ('two generators are named "tonnetz": _apc64_lab/domain/generators.py and '
                                 "lab_plugins_t33/f_tonnetz_again.py; the second is refused",)
    assert "grey" in registry.schemes() and "wicki-hayden" in registry.generators()


def test_the_shipped_plugin_directory():   # s18 (the root-highlight scheme ships)
    found = PluginDiscovery().discover()
    assert [f for f, _ in found] == ["_apc64_lab/generators/root_highlight.py"]
    assert found[0][1].name == "root-highlight"
