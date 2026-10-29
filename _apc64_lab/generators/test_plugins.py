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


# --- the scale overlay -----------------------------------------------------------------------------------
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.notation.compiler import compile_text
from _apc64_lab.domain.generators import BUILTIN_GENERATORS, BUILTIN_SCHEMES, Isomorphic, configure
from _apc64_lab.domain.lab_section import compile_lab_section
from _apc64_lab.domain.pads import RED, WHITE
from _apc64_lab.generators.modes import GENERATOR as MODES
from _apc64_lab.generators.scale import OUT_OF_SCALE, SCHEME as SCALE

import pytest

GENERATORS = {g.name: g for g in (*BUILTIN_GENERATORS, MODES)}
SCHEMES = {s.name: s for s in (*BUILTIN_SCHEMES, SCALE)}


class _Lab:
    def compile(self, section, file, existing):
        return compile_lab_section(section, file, existing, GENERATORS, SCHEMES)


def lab(text):
    return compile_text(text, "fourths.yaml", sections={"lab": _Lab()})


def test_the_scale_scheme_lights_the_scale_marks_its_root_and_dims_the_rest():
    d_dorian = configure(SCALE, {"scale": "dorian", "root": 2})
    assert d_dorian.colour(62, 0) == (WHITE, RED)                      # D, the root
    rest, _ = d_dorian.colour(65, 0)                                   # F: in D Dorian
    assert rest not in (WHITE, OUT_OF_SCALE)
    assert d_dorian.colour(66, 0)[0] == OUT_OF_SCALE != (0, 0, 0)      # F♯: outside, dim but lit
    assert OUT_OF_SCALE.r + OUT_OF_SCALE.g + OUT_OF_SCALE.b > 0


def test_the_scale_root_defaults_to_the_layouts_root():
    major = configure(SCALE, {"scale": "major"})
    assert major.colour(55, 7) == (WHITE, RED) and major.colour(54, 7)[0] != OUT_OF_SCALE   # F♯ is in G major
    assert major.overlay(7).root == 7 and major.overlay(7).pitch_classes == frozenset({7, 9, 11, 0, 2, 4, 6})


def test_a_scale_layout_validates_and_the_overlay_is_spelled_in_key():
    result = lab("name: Fourths\nlab:\n  generator: isomorphic\n  base: 38\n  scheme: scale\n  scale: Harmonic Minor\n")
    assert result.valid and result.warnings == (), [i.message() for i in result.issues]
    definition = result.layout.section("lab")
    assert dict(definition.scheme_params) == {"scale": "harmonic-minor"} and definition.root == 2
    overlay = definition.overlay(SCHEMES)
    assert overlay.key == "harmonic-minor" and dict(overlay.names)[1] == "C♯"     # D harmonic minor: C♯, not D♭
    grid = definition.grid(GENERATORS, SCHEMES)
    assert grid.at(PadPos(1, 1)).rest == WHITE and grid.at(PadPos(1, 2)).rest == OUT_OF_SCALE   # D, then E♭


@pytest.mark.parametrize("line,expected", [
    ("  scale: dorain", 'fourths.yaml line 6: no scale "dorain"; did you mean dorian? available: chromatic,'),
    ("  root: H", "fourths.yaml line 6, root: 'H' is not a note name; write C, C♯ (or C#), D♭ (or Db) … B, without an octave"),
])
def test_scale_parameters_are_validated_with_precise_errors(line, expected):
    result = lab(f"name: Fourths\nlab:\n  generator: isomorphic\n  base: 38\n  scheme: scale\n{line}\n")
    assert not result.valid and result.issues[0].message().startswith(expected), result.issues[0].message()


def test_a_scale_parameter_without_the_scale_scheme_is_a_warning_naming_the_scheme():
    result = lab("name: Fourths\nlab:\n  generator: isomorphic\n  scale: dorian\n")
    assert result.valid
    assert [w.message() for w in result.warnings] == [
        "fourths.yaml line 4: scale is a parameter of the scale colour scheme, unused with fifths; remove it, "
        "or write 'scheme: scale'"]


# --- the modes explorer ----------------------------------------------------------------------------------
def modes_grid(base=48, scheme=None):
    return generate(MODES, parse_params(MODES.params, {"base": base}), scheme or FifthsHue())


IONIAN_TO_LOCRIAN = ("Ionian", "Dorian", "Phrygian", "Lydian", "Mixolydian", "Aeolian", "Locrian", "")


def test_the_modes_rows_go_from_ionian_to_locrian_root_to_octave_and_row_8_is_dark():
    grid = modes_grid(48)
    rows = [[grid.note_at(r, c) - 48 if grid.note_at(r, c) is not None else None for c in range(1, 9)]
            for r in range(1, 9)]
    assert rows[0] == [0, 2, 4, 5, 7, 9, 11, 12]     # Ionian
    assert rows[1] == [0, 2, 3, 5, 7, 9, 10, 12]     # Dorian
    assert rows[3] == [0, 2, 4, 6, 7, 9, 11, 12]     # Lydian
    assert rows[6] == [0, 1, 3, 5, 6, 8, 10, 12]     # Locrian
    assert rows[7] == [None] * 8 and all(grid.at(PadPos(8, c)).silent for c in range(1, 9))
    assert MODES.row_labels({}) == IONIAN_TO_LOCRIAN


def test_the_notes_that_differ_from_ionian_are_stressed_the_rest_dimmed_root_and_octave_white():
    grid = modes_grid(48)
    ionian = (0, 2, 4, 5, 7, 9, 11, 12)
    for r in range(1, 8):
        row = [grid.note_at(r, c) - 48 for c in range(1, 9)]
        assert grid.at(PadPos(r, 1)).rest == WHITE and grid.at(PadPos(r, 8)).rest == WHITE
        for c in range(2, 8):
            full = FifthsHue().colour(48 + row[c - 1], 0)[0]
            rest = grid.at(PadPos(r, c)).rest
            assert (rest == full) == (row[c - 1] != ionian[c - 1]), (r, c)   # full colour exactly where it differs
    assert grid.at(PadPos(7, 5)).rest == FifthsHue().colour(54, 0)[0]   # Locrian's ♭5 differs: full
    assert grid.at(PadPos(4, 4)).rest == FifthsHue().colour(54, 0)[0]   # Lydian's ♯4


def test_the_modes_range_is_one_octave_and_the_highest_base_is_115():
    grid = modes_grid(115)
    assert max(p.note for _, p in grid.active) == 127 and min(p.note for _, p in grid.active) == 115
    result = lab("name: Modes\nlab:\n  generator: modes\n  base: 116\n")
    assert [i.message() for i in result.issues] == [
        "fourths.yaml line 4, base: 116 is outside 0–115; base is 0–115"]


def test_the_modes_explorer_takes_any_scheme_and_a_scale_overlay():
    grid = modes_grid(48, configure(SCALE, {"scale": "major"}))
    assert grid.at(PadPos(3, 2)).rest == OUT_OF_SCALE   # D♭ in Phrygian: outside C major, at full (it differs)
    assert len(grid.active) == 56


def test_each_modes_row_is_spelled_in_its_mode_at_any_key():
    names = MODES.pad_names({"base": 48}, 0)
    rows = [names[r * 8:(r + 1) * 8] for r in range(8)]
    assert rows[6] == ("C", "D♭", "E♭", "F", "G♭", "A♭", "B♭", "C")      # Locrian
    assert rows[3] == ("C", "D", "E", "F♯", "G", "A", "B", "C")          # Lydian
    assert rows[7] == (None,) * 8
    assert MODES.pad_names({"base": 48}, 7)[:8] == ("G", "A", "B", "C", "D", "E", "F♯", "G")    # G Ionian
    assert MODES.pad_names({"base": 48}, 1)[:8] == ("D♭", "E♭", "F", "G♭", "A♭", "B♭", "C", "D♭")   # D♭ Ionian


def test_the_modes_window_walks_the_keys_by_semitone_or_fifth_and_shows_the_key():
    from _apc64_lab.domain.pads import NoteSpan
    from _apc64_lab.domain.window import StepWindow
    spec = MODES.window({"base": 49})                                      # D♭2
    window = StepWindow.starting(spec)
    assert window.oled("Modes").row1 == "Key Db" and [s.label for s in spec.steps] == ["Semitone", "Fifth"]
    span = NoteSpan(49, 61)
    fifths = window.cycled()
    assert fifths.flash_step("Modes").row1 == "Step: Fifth"
    keys = []
    for _ in range(12):
        fifths = fifths.shifted(+1, span)
        keys.append(fifths.oled("Modes").row1.removeprefix("Key "))
    assert keys == ["Ab", "Eb", "Bb", "F", "C", "G", "D", "A", "E", "B", "Gb", "Db"]   # round the circle and home
    assert 0 <= fifths.position <= 11 and window.shifted(-1, span).oled("Modes").row1 == "Key C"   # wraps


def test_the_modes_colours_and_marks_follow_the_key():
    params = parse_params(MODES.params, {"base": 48})
    in_c, in_d = generate(MODES, params, FifthsHue(), 0), generate(MODES, params, FifthsHue(), 2)
    assert [p.rest for _, p in in_c.active] == [p.rest for _, p in in_d.active]   # the same picture in every key
    assert in_d.note_at(1, 1) == 50 and in_d.at(PadPos(1, 1)).rest == WHITE


# --- the guitar neck (amendment 2026-10-27) --------------------------------------------------------------
from pathlib import Path

from _apc64_host.domain.effects import UnitView
from _apc64_lab.domain.memory_sysex import parse_project_dump
from _apc64_lab.domain.session import EdgeHit, LabSession, NeedBackup, SessionLayout, ShowOled
from _apc64_lab.domain.window import StepWindow
from _apc64_lab.generators.guitar import GENERATOR as GUITAR, TUNINGS

GENERATORS["guitar"] = GUITAR


def guitar(**given):
    params = parse_params(GUITAR.params, given)
    return generate(GUITAR, params, FifthsHue()), params


def rows_of(grid):
    """Row number → the notes of its 8 pads (None: a silent row)."""
    return {r: (None if grid.at(PadPos(r, 1)).silent else [grid.note_at(r, c) for c in range(1, 9)])
            for r in range(1, 9)}


def test_six_strings_take_rows_2_to_7_highest_on_top_frets_0_to_7_across():
    grid, _ = guitar()
    rows = rows_of(grid)
    assert rows[1] is None and rows[8] is None                         # the free rows: silent
    assert [rows[r][0] for r in range(2, 8)] == [40, 45, 50, 55, 59, 64]   # low E (row 2) … high E (row 7)
    assert rows[2] == list(range(40, 48)) and rows[2][5] == rows[3][0]   # low E fret 5 = the open A
    assert all(grid.at(PadPos(r, c)).silent and not grid.at(PadPos(r, c)).aftertouch for r in (1, 8) for c in range(1, 9))


def test_seven_and_eight_strings_fill_from_the_bottom_row():
    rows7 = rows_of(guitar(tuning="b-standard-7")[0])
    assert rows7[1][0] == 35 and rows7[7][0] == 64 and rows7[8] is None
    rows8 = rows_of(guitar(tuning="fs-standard-8")[0])
    assert [rows8[r][0] for r in range(1, 9)] == [30, 35, 40, 45, 50, 55, 59, 64]
    bass = rows_of(guitar(tuning="bass-4")[0])
    assert [r for r in bass if bass[r]] == [2, 3, 4, 5] and bass[2][0] == 28


def test_each_string_sends_on_its_own_channel_string_1_the_highest_on_channel_1():
    grid, _ = guitar()
    assert [grid.at(PadPos(r, 3)).channel for r in range(7, 1, -1)] == [1, 2, 3, 4, 5, 6]
    eight, _ = guitar(tuning="drop-e-8")
    assert eight.at(PadPos(8, 1)).channel == 1 and eight.at(PadPos(1, 8)).channel == 8


def test_the_strings_are_named_by_number_and_letter_and_the_root_is_the_lowest_string():
    _, params = guitar()
    assert GUITAR.row_labels(params) == ("", "6 E", "5 A", "4 D", "3 G", "2 B", "1 E", "")
    assert GUITAR.row_labels(parse_params(GUITAR.params, {"tuning": "fs-standard-8"}))[0] == "8 F♯"
    assert GUITAR.root(params) == 4 and GUITAR.root(parse_params(GUITAR.params, {"tuning": "drop-d"})) == 2


def test_the_presets_are_as_agreed_low_to_high():
    assert TUNINGS["e-standard"] == (40, 45, 50, 55, 59, 64) and TUNINGS["dadgad"] == (38, 45, 50, 55, 57, 62)
    assert TUNINGS["drop-a-7"] == (33, 40, 45, 50, 55, 59, 64) and TUNINGS["bass-5"] == (23, 28, 33, 38, 43)
    assert all(4 <= len(t) <= 8 and list(t) == sorted(t) for t in TUNINGS.values())


def test_the_fifths_scheme_gives_every_place_of_a_note_one_colour():
    grid, _ = guitar(fret_marks="off")
    by_pc = {}
    for _, pad in grid.active:
        by_pc.setdefault(pad.note % 12, set()).add(pad.rest)
    assert all(len(colours) == 1 for colours in by_pc.values())


def test_the_inlay_frets_are_marked_on_the_pads_and_move_with_the_window():   # 2026-10-27
    from _apc64_lab.domain.generators import _brightened, _shaded
    from _apc64_lab.domain.pads import Rgb
    plain, params = guitar(fret_marks="off")
    assert params["fret_marks"] == "off" and guitar(fret_marks="false")[1]["fret_marks"] == "off"
    marked, _ = guitar()
    low_e = lambda grid, c: grid.at(PadPos(2, c))
    for column, fret in enumerate(range(8), 1):                # t = 0: column c plays fret c − 1
        pad, base = low_e(marked, column), low_e(plain, column)
        expected = base.rest if fret in (3, 5, 7) else _shaded(base.rest)
        assert pad.rest == expected and pad.pressed == base.pressed, fret
    at = lambda t: generate(GUITAR, params | {"fret_marks": "on"}, FifthsHue(), t)
    assert at(5).at(PadPos(2, 8)).rest == _brightened(generate(GUITAR, params, FifthsHue(), 5).at(PadPos(2, 8)).rest)
    assert at(5).at(PadPos(2, 1)).rest == generate(GUITAR, params, FifthsHue(), 5).at(PadPos(2, 1)).rest   # fret 5
    assert at(5).at(PadPos(1, 8)).silent                       # the free rows stay silent
    assert _shaded(Rgb(24, 28, 40)) == Rgb(24, 28, 40)          # a colour dark already is kept (scale's outside)
    with pytest.raises(Exception):
        parse_params(GUITAR.params, {"fret_marks": "sometimes"})


def test_the_window_is_fret_and_page_within_the_neck():
    _, params = guitar()
    spec = GUITAR.window(params)
    assert [s.label for s in spec.steps] == ["Fret", "Page"] and (spec.lowest, spec.highest) == (0, 17)
    assert spec.pages == (0, 8, 16, 17) and spec.shown == 8
    assert GUITAR.window(parse_params(GUITAR.params, {"frets": 12})).pages == (0, 5)
    assert GUITAR.window(parse_params(GUITAR.params, {"frets": 23})).pages == (0, 8, 16)


def guitar_lab(body):
    return lab(f"name: Guitar\nlab:\n  generator: guitar\n{body}")


def test_a_guitar_layout_validates_with_a_preset_or_a_written_tuning():
    for body in ("  tuning: drop-d\n", "  tuning: Drop D\n", "  tuning: [E1, A1, D2, G2, B2, E3]\n  frets: 22\n",
                 "  tuning: [28, 33, 38, 43]\n  scheme: scale\n  scale: minor-pentatonic\n"):
        result = guitar_lab(body)
        assert result.valid and result.warnings == (), [i.message() for i in result.issues]
    definition = guitar_lab("  tuning: [E1, A1, D2, G2, B2, E3]\n").layout.section("lab")
    assert definition.parameters["tuning"] == (40, 45, 50, 55, 59, 64) and definition.root == 4
    overlay = guitar_lab("  scheme: scale\n").layout.section("lab").overlay(SCHEMES)
    assert overlay.root == 4 and overlay.key == "major"                    # E major: the lowest string's root


@pytest.mark.parametrize("body,expected", [
    ("  tuning: [40, 45, 50]\n", "fourths.yaml line 4, tuning: 3 notes; write 4 to 8 notes, "
                                "low to high, or one of: e-standard, drop-d,"),
    ("  tuning: [28, 30, 35, 40, 45, 50, 55, 59, 64]\n", "fourths.yaml line 4, tuning: 9 notes; write 4 to 8 notes"),
    ("  tuning: drop-f\n", 'fourths.yaml line 4: no tuning "drop-f"; did you mean drop-d? available: e-standard,'),
    ("  tuning: [E1, A1, D2, G2, B2, X3]\n", "fourths.yaml line 4, tuning: note 6: 'X3' is not a note"),
    ("  frets: 40\n", "fourths.yaml line 4, frets: 40 is outside 12–36; frets is 12–36"),
    ("  tuning: [120, 121, 122, 123]\n", "fourths.yaml line 4, tuning: pad r5c8 gets note 130; notes are 0–127"),
])
def test_a_guitar_layout_is_refused_precisely_at_its_line(body, expected):
    result = guitar_lab(body)
    assert not result.valid and result.issues[0].message().startswith(expected), result.issues[0].message()


def test_the_neck_lists_the_strings_highest_first_with_their_channels():
    neck = GUITAR.neck(parse_params(GUITAR.params, {"tuning": "drop-d", "frets": 22}))
    assert neck.frets == 22 and neck.shown == 8
    assert [(s.number, s.open, s.channel) for s in neck.strings] == [
        (1, 64, 1), (2, 59, 2), (3, 55, 3), (4, 50, 4), (5, 45, 5), (6, 38, 6)]
    assert neck.to_json()["strings"][5] == {"string": 6, "open": 38, "name": "D", "channel": 6}


@pytest.fixture
def factory_frame() -> bytes:
    return (Path(__file__).resolve().parents[2] / "fixtures" / "apc64-factory-project.syx").read_bytes()


def guitar_session(factory_frame, tuning="e-standard", frets=24):
    definition = guitar_lab(f"  tuning: {tuning}\n  frets: {frets}\n").layout.section("lab")
    layout = SessionLayout.of_grid("guitar", "Guitar", lambda t: definition.grid(GENERATORS, SCHEMES, t), definition,
                                   definition.window_spec(GENERATORS))
    session = LabSession()
    session.on_view(UnitView.CUSTOM)
    assert isinstance(session.activate(layout), NeedBackup)
    first = session.started(parse_project_dump(factory_frame)[1], "slot0-backup", None, 0.0)
    return session, first


def r2c1(decision):
    return decision.record.pad(PadPos(2, 1)).note


def test_a_guitar_session_moves_by_fret_and_by_page(factory_frame):
    session, first = guitar_session(factory_frame)
    assert first.oled.rows == ("Guitar", "Frets 0-7") and r2c1(first) == 40      # row 2: what is shown (2026-10-27)
    assert first.record.pad(PadPos(7, 1)).channel == 1 and first.record.pad(PadPos(2, 1)).channel == 6
    moved = session.shift(+3)
    assert moved.oled.row1 == "Frets 3-10" and r2c1(moved) == 43 and session.window.transposition() == 3
    toggled = session.cycle_interval()
    assert isinstance(toggled, ShowOled) and toggled.flash.row1 == "Step: Page" and toggled.oled.row1 == "Frets 3-10"
    assert session.window.label() == "Page 3-10"
    assert session.shift(+1).oled.row1 == "Frets 8-15" and session.shift(+2).oled.row1 == "Frets 17-24"
    edge = session.shift(+1)
    assert isinstance(edge, EdgeHit) and edge.flash.row1 == "Neck end" and edge.oled.row1 == "Frets 17-24"
    assert session.window.position == 17 and session.shift(-1).oled.row1 == "Frets 16-23"
    assert session.cycle_interval().flash.row1 == "Step: Fret"


def test_a_guitar_tweak_reloads_at_the_same_fret_while_it_fits(factory_frame):
    session, _ = guitar_session(factory_frame)
    session.shift(+10)
    definition = guitar_lab("  tuning: drop-d\n  frets: 24\n").layout.section("lab")
    same = SessionLayout.of_grid("guitar", "Guitar", lambda t: definition.grid(GENERATORS, SCHEMES, t), definition,
                                 definition.window_spec(GENERATORS))
    reloaded = session.reloaded(same)
    assert reloaded.oled.row1 == "Frets 10-17" and r2c1(reloaded) == 48    # drop D's low D + 10
    short = guitar_lab("  frets: 12\n").layout.section("lab")
    shorter = SessionLayout.of_grid("guitar", "Guitar", lambda t: short.grid(GENERATORS, SCHEMES, t), short,
                                    short.window_spec(GENERATORS))
    assert session.reloaded(shorter).oled.row1 == "Frets 0-7"                # 10 is past a 12-fret neck's end
    assert isinstance(session.window, StepWindow)


def test_every_modes_row_starts_on_the_keys_root_name_and_spells_each_letter_once_in_all_twelve_keys():
    from _apc64_lab.domain.window import KEY_NAMES
    for t in range(12):
        names = MODES.pad_names({"base": 48}, t)
        root = KEY_NAMES[t].replace("b", "♭") if len(KEY_NAMES[t]) > 1 else KEY_NAMES[t]
        for r in range(7):
            row = names[r * 8:(r + 1) * 8]
            assert row[0] == root and row[7] == root, (KEY_NAMES[t], r, row)
            assert len({name[0] for name in row[:7]}) == 7, (KEY_NAMES[t], r, row)
    eb = MODES.pad_names({"base": 51}, 0)
    assert eb[16:24] == ("E♭", "F♭", "G♭", "A♭", "B♭", "C♭", "D♭", "E♭")     # E♭ Phrygian
    assert eb[48:56] == ("E♭", "F♭", "G♭", "A♭", "B𝄫", "C♭", "D♭", "E♭")    # E♭ Locrian: the key needs B𝄫
