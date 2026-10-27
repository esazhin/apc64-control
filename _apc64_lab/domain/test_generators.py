"""Built-in generators and the default scheme on the contract §4.2 values (T3)."""
import pytest

from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_lab.domain.generators import (
    BUILTIN_GENERATORS, BUILTIN_SCHEMES, ColourScheme, FifthsHue, GeneratorFault, Isomorphic, PadLayoutGenerator,
    TonnetzCheckerboard, defaults, generate, out_of_range, parse_params, raw_notes,
)
from _apc64_lab.domain.pads import BLACK, RED, WHITE


def tonnetz_c(transposition=0):
    gen = TonnetzCheckerboard()
    return generate(gen, parse_params(gen.params, {"base": 48}), FifthsHue(), transposition)


def test_tonnetz_c_plays_c_g_e_and_leaves_the_odd_pads_dark():   # A8, d1, d3
    grid = tonnetz_c()
    assert grid.note_at(1, 1) == 48 and grid.at(PadPos(1, 1)).rest == WHITE
    assert grid.note_at(1, 3) == 55 and grid.note_at(2, 2) == 52
    for pad in (PadPos(1, 2), PadPos(2, 1)):
        assert grid.at(pad).silent and grid.at(pad).rest == BLACK
    assert len(grid.active) == 32


def test_tonnetz_axes_are_fifth_major_third_and_minor_third():   # p13, d1
    grid = tonnetz_c()
    assert grid.note_at(1, 3) - grid.note_at(1, 1) == 7    # two pads right
    assert grid.note_at(2, 2) - grid.note_at(1, 1) == 4    # up-right
    assert grid.note_at(2, 2) - grid.note_at(1, 3) == -3   # up-left from G: a minor third down


def test_fourths_isomorphic_lights_all_64_and_shares_colours_by_pitch_class():   # A9, d2
    gen = Isomorphic()
    grid = generate(gen, parse_params(gen.params, {"base": 36, "column": 1, "row": 5}), FifthsHue())
    assert (grid.note_at(1, 1), grid.note_at(1, 2), grid.note_at(2, 1), grid.note_at(8, 8)) == (36, 37, 41, 78)
    assert len(grid.active) == 64
    by_class = {}
    for _, pad in grid.active:
        by_class.setdefault(pad.note % 12, set()).add(pad.rest)
    assert all(len(colours) == 1 for colours in by_class.values()) and len(by_class) == 12


def test_the_fifths_scheme_is_the_prototypes():   # d17
    scheme = FifthsHue()
    assert scheme.colour(48, 0) == (WHITE, RED)
    assert scheme.colour(55, 0) == (scheme.colour(43, 0)[0], WHITE)       # G: same hue in every octave
    assert scheme.colour(55, 0)[0] != scheme.colour(50, 0)[0]
    assert scheme.colour(55, 0)[0].to_hex() == "#FF8000"                     # 30° (one fifth up)


def test_every_active_pad_has_aftertouch_and_the_channel_parameter():   # d45, q8
    gen = TonnetzCheckerboard()
    grid = generate(gen, parse_params(gen.params, {"base": "C3", "channel": 3}), FifthsHue())
    assert grid.note_at(1, 1) == 60
    assert all(p.aftertouch and p.channel == 3 for _, p in grid.active)


def test_the_window_transposes_every_active_pad():
    assert tonnetz_c(7).note_at(1, 1) == 55 and tonnetz_c(7).note_at(1, 3) == 62


def test_base_110_puts_r8c8_at_138_and_names_the_highest_base():   # A10 (domain half), d4
    gen = TonnetzCheckerboard()
    params = parse_params(gen.params, {"base": 110})
    problem = out_of_range(raw_notes(gen, params), params)
    assert problem.problem(110) == "110 puts pad r8c8 at note 138" and problem.fix() == "the highest base is 99"
    assert out_of_range(raw_notes(gen, parse_params(gen.params, {"base": 99})), {"base": 99}) is None


def test_a_negative_note_names_the_lowest_base():
    gen = Isomorphic()
    params = parse_params(gen.params, {"base": 0, "column": -1, "row": 0})
    problem = out_of_range(raw_notes(gen, params), params)
    assert problem.problem(0) == "0 puts pad r1c8 at note -7" and problem.fix() == "the lowest base is 7"


def test_parameters_are_validated_and_unknown_ones_refused():   # d5
    gen = Isomorphic()
    assert parse_params(gen.params, {}) == defaults(gen.params) == {"base": 36, "column": 1, "row": 5, "channel": 1}
    with pytest.raises(DomainInvariantError) as error:
        parse_params(gen.params, {"channel": 17})
    assert (error.value.field, error.value.problem, error.value.fix) == (
        "channel", "17 is outside 1–16", "channels are 1–16")
    with pytest.raises(DomainInvariantError) as error:
        parse_params(gen.params, {"rows": 4})
    assert error.value.problem == "unknown parameter 'rows'" and "base, column, row, channel" in error.value.fix


class Spiral:
    name, params = "spiral", ()

    def notes(self, params):
        return 1 / 0


class Short:
    name, params = "short", ()

    def notes(self, params):
        return [60] * 10


def test_a_broken_generator_is_a_fault_with_its_error():   # d13 (A19's error text)
    with pytest.raises(GeneratorFault, match="division by zero"):
        raw_notes(Spiral(), {})
    with pytest.raises(GeneratorFault, match="returned 10 pads, expected 64"):
        raw_notes(Short(), {})


def test_builtins_satisfy_the_protocols():   # d11, A17 (names)
    assert [g.name for g in BUILTIN_GENERATORS] == ["tonnetz", "isomorphic"]
    assert all(isinstance(g, PadLayoutGenerator) for g in BUILTIN_GENERATORS)
    assert all(isinstance(s, ColourScheme) for s in BUILTIN_SCHEMES)
    assert [p.name for p in TonnetzCheckerboard().params] == ["base", "channel"]


# --- the guitar amendment (2026-10-27): per-pad channels, a generator's root, a list parameter -------------
from _apc64_lab.domain.generators import ParamKind, ParamSpec, channels_of, root_of


class _TwoChannels(Isomorphic):
    """Rows 1–4 on channel 3, the rest on the layout's channel."""
    def channels(self, params):
        return tuple(3 if r < 4 else None for r in range(8) for x in range(8))

    def root(self, params):
        return 9


def test_a_generator_may_give_pads_channels_of_their_own():
    gen = _TwoChannels()
    grid = generate(gen, parse_params(gen.params, {"base": 36, "channel": 5}), FifthsHue())
    assert grid.at(PadPos(1, 1)).channel == 3 and grid.at(PadPos(4, 8)).channel == 3
    assert grid.at(PadPos(5, 1)).channel == 5 and grid.at(PadPos(8, 8)).channel == 5


def test_generators_without_the_hook_keep_one_channel_for_every_pad():
    gen = Isomorphic()
    assert channels_of(gen, {}) is None
    grid = generate(gen, parse_params(gen.params, {"channel": 4}), FifthsHue())
    assert {p.channel for _, p in grid.active} == {4}


def test_a_channels_hook_answering_badly_is_a_fault():
    class Bad(Isomorphic):
        def channels(self, params):
            return (17,) * 64
    with pytest.raises(GeneratorFault, match="channels must be 64 of 1–16"):
        generate(Bad(), parse_params(Bad.params, {}), FifthsHue())


def test_the_layouts_root_is_the_generators_own_when_it_has_one():
    assert root_of(_TwoChannels(), {"base": 36}) == 9
    assert root_of(Isomorphic(), {"base": 38}) == 2 and root_of(None, {}) == 0


TUNING = ParamSpec("tuning", ParamKind.NOTE_LIST, "e-standard", 4, 8, "the open strings",
                   choices=("e-standard", "drop-d"))


def test_a_note_list_parameter_takes_a_preset_or_a_list_of_notes():
    assert TUNING.parse("drop-d") == "drop-d"
    assert TUNING.parse(["E1", "A1", 50, "G2", "B2", "E3"]) == (40, 45, 50, 55, 59, 64)   # C3 = 60: E1 is 40
    assert TUNING.describe()["choices"] == ["e-standard", "drop-d"]


@pytest.mark.parametrize("value,problem,fix", [
    ([40, 45, 50], "3 notes", "write 4 to 8 notes, low to high, or one of: e-standard, drop-d"),
    (["E1", "H1", 50, 55], "note 2: 'H1' is not a note", "write a number 0–127 or a name like C1 (36), F#2 or Bb3 (C3 = 60)"),
    ("drop-q", 'no tuning "drop-q"', "did you mean drop-d? available: e-standard, drop-d"),
])
def test_a_note_list_parameter_is_refused_precisely(value, problem, fix):
    with pytest.raises(DomainInvariantError) as error:
        TUNING.parse(value)
    assert (error.value.field, error.value.problem, error.value.fix) == ("tuning", problem, fix)
