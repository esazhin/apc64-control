"""Every shipped plugin exposes GENERATOR or SCHEME and yields a 64-pad grid in 0–127 (contract s18 supplier)."""
import importlib
import pkgutil

import _apc64_lab.generators as plugins
from _apc64_lab.domain.generators import (
    ColourScheme, PadLayoutGenerator, TonnetzCheckerboard, FifthsHue, generate, parse_params,
)


def _modules():
    return [importlib.import_module(f"{plugins.__name__}.{info.name}")
            for info in pkgutil.iter_modules(plugins.__path__) if not info.name.startswith("test_")]


def test_each_plugin_exposes_exactly_one_generator_or_scheme():
    modules = _modules()
    assert modules, "at least the shipped root-highlight scheme"
    for module in modules:
        exposed = [name for name in ("GENERATOR", "SCHEME") if hasattr(module, name)]
        assert len(exposed) == 1, module.__name__


def test_each_plugin_gives_64_pads_in_range():
    for module in _modules():
        if hasattr(module, "GENERATOR"):
            gen = module.GENERATOR
            assert isinstance(gen, PadLayoutGenerator)
            grid = generate(gen, parse_params(gen.params, {}), FifthsHue())
        else:
            assert isinstance(module.SCHEME, ColourScheme)
            gen = TonnetzCheckerboard()
            grid = generate(gen, parse_params(gen.params, {"base": 48}), module.SCHEME)
        assert len(grid.pads) == 64 and all(0 <= p.note <= 127 for _, p in grid.active)


def test_root_highlight_marks_the_root_and_its_triad():   # the scheme A15 switches to
    from _apc64_lab.generators.root_highlight import SCHEME
    root, third, other = SCHEME.colour(48, 0), SCHEME.colour(52, 0), SCHEME.colour(50, 0)
    assert root[0].to_hex() == "#FFFFFF" and third[0] != other[0] and root[0] != third[0]
