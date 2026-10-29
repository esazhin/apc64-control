"""The pattern format (docs/performer-format.md): parsing, every refusal with its place and fix, the canonical data."""
import json
from fractions import Fraction

import pytest

from performer import ACCENT, HIT, REST, PatternError, check_pattern, parse_pattern, to_data
from performer.pattern import Issue, row_cells, row_text

ARP = {"name": "Arpeggio 1-2-3", "meter": "4/4", "step": "1/8", "length": 8,
       "lanes": {1: ". . . x | . . . x", 2: ". x . . | . x . .", 3: ". . x . | . . x ."}, "manual": [4, 5, 6]}


def issues(data):
    with pytest.raises(PatternError) as caught:
        parse_pattern(data)
    return [(i.path, i.text()) for i in caught.value.issues if i.is_error]


def test_the_users_example_parses_with_its_manual_lanes():
    p = parse_pattern(ARP)
    assert p.name == "Arpeggio 1-2-3" and str(p.meter) == "4/4" and p.step == "1/8" and p.length == 8
    assert p.cells(1) == (REST, REST, REST, HIT, REST, REST, REST, HIT)
    assert p.cells(4) == (REST,) * 8 and p.manual == frozenset({4, 5, 6})
    assert p.hits_at(1) == ((2, HIT),) and p.hits_at(0) == ()
    assert (p.step_quarters, p.bar_steps) == (Fraction(1, 2), 8) and p.gate is None and p.warnings == ()


def test_defaults_meter_step_and_a_length_from_the_rows():
    p = parse_pattern({"name": "Pulse", "lanes": {"1": "X x x x"}})
    assert (str(p.meter), p.step, p.length) == ("4/4", "1/8", 4)
    assert p.cells(1) == (ACCENT, HIT, HIT, HIT) and (p.swing, p.play, p.hit, p.accent) == (50, "all", 100, 127)
    assert [w.text() for w in p.warnings] == [
        "length: 4 steps are not a whole number of 4/4 bars of 1/8 steps (8 a bar); the pattern loops after its length all the same"]


def test_triplet_steps_and_other_meters():
    p = parse_pattern({"name": "Waltz", "meter": "3/4", "step": "1/8t", "lanes": {6: "x . . " * 3 + "x . ."}})
    assert p.step_fraction == Fraction(1, 12) and p.bar_steps == 9 and p.length == 12
    assert parse_pattern({"name": "S", "meter": "6/8", "step": "1/16", "lanes": {1: "x" * 12}}).bar_steps == 12


def test_strum_swing_gate_velocity_humanize_and_play():
    p = parse_pattern({"name": "Strum", "lanes": {k: "x . x x . x x x" for k in range(1, 7)},
                       "strum": "d . d u . u d u", "spread": 12, "swing": 58, "gate": 0.5, "play": "pressed",
                       "velocity": {"hit": 90, "accent": 120}, "humanize": {"timing": 4, "velocity": 6}})
    assert p.strum == ("down", None, "down", "up", None, "up", "down", "up") and p.strum_at(3) == "up"
    assert (p.spread, p.swing, p.gate, p.play, p.hit, p.accent, p.timing, p.jitter) == (12, 58, 0.5, "pressed", 90, 120, 4, 6)


@pytest.mark.parametrize("data,expected", [
    ({**ARP, "lanes": {1: ". . x"}}, [(("lanes", "1"), "lane 1: 3 steps; length is 8; write one cell per step: . (rest), x (hit) or X (accent); spaces and | are ignored")]),
    ({**ARP, "lanes": {1: ". y . . . . . ."}}, [(("lanes", "1"), "lane 1: 'y' at step 2 is not a cell; write one cell per step: . (rest), x (hit) or X (accent); spaces and | are ignored")]),
    ({**ARP, "lanes": {17: "x . . . . . . ."}}, [(("lanes", "17"), "lane 17: '17' is not a lane; lanes are 1–16 (1 is the highest string), R (the root string) or A (the alternate bass)")]),
    ({**ARP, "lanes": {4: "x . . . . . . ."}}, [(("lanes", "4"), "lane 4 is manual and has a row; remove its row, or take 4 out of manual")]),
    ({**ARP, "step": "1/5"}, [(("step",), "'1/5' is not a step; write one of 1/4, 1/8, 1/16, 1/8t, 1/16t")]),
    ({**ARP, "meter": "four"}, [(("meter",), "'four' is not a meter; write beats per bar / beat unit, e.g. 4/4, 3/4 or 6/8")]),
    ({**ARP, "length": 40}, [(("length",), "'40' is not a length; write the number of steps, 1–32")]),
    ({**ARP, "swing": 90}, [(("swing",), "swing: '90' is outside 50–75; swing is 50–75: 50 is straight, 66 a triplet feel, 75 the most")]),
    ({**ARP, "strum": "d . d"}, [(("strum",), "strum: 3 steps; length is 8; write one mark per step: d, u or .")]),
    ({**ARP, "play": "held"}, [(("play",), "play: 'held' is not all or pressed; all: every lane plays at its hits, an unpressed string open; pressed: only pressed lanes play")]),
    ({**ARP, "gate": 0}, [(("gate",), "'0' is not a gate; write ring (a note rings until its lane's next hit) or a length in steps, e.g. 0.5 (0–32)")]),
    ({**ARP, "swng": 60}, [(("swng",), "unknown key 'swng'; did you mean swing? a pattern takes format, name, description, meter, step, length, lanes, strum, spread, swing, play, gate, velocity, humanize, manual")]),
    ({"lanes": {1: "x"}}, [(("name",), "the pattern has no name; add 'name: Travis pick'")]),
    ({"name": "N"}, [(("lanes",), "the pattern has no lanes; add 'lanes:' with one row per lane, e.g. '  1: x . x .'")]),
    ({"name": "N", "lanes": {1: ". . . ."}}, [(("lanes",), "lanes: the pattern has no hit; put an x (or X) in a lane")]),
    ({"name": "N", "lanes": {1: "x .", 2: "x . ."}}, [(("lanes",), "the lanes have 2, 3 steps; give every lane the same number of cells, or write 'length:'")]),
    ({**ARP, "velocity": {"hit": 200}}, [(("velocity", "hit"), "velocity.hit: '200' is outside 1–127; write the hit's velocity at full press, 1–127")]),
    ({**ARP, "humanize": {"timing": 80}}, [(("humanize", "timing"), "humanize.timing: '80' is outside 0–50; timing is ± milliseconds, 0–50")]),
    ({**ARP, "manual": ["low"]}, [(("manual",), "manual: 'low' is not a lane; write lane numbers 1–16, e.g. [4, 5, 6]")]),
    ({**ARP, "format": 2}, [(("format",), "format 2 is not known here; this is format 1; write 'format: 1' or leave it out")]),
])
def test_every_refusal_names_its_place_and_a_fix(data, expected):
    assert issues(data) == expected


def test_every_issue_is_found_at_once():
    found = issues({"name": "N", "step": "1/5", "swing": 10, "lanes": {1: "x . . ."}})
    assert [path for path, _ in found] == [("step",), ("swing",)]


def test_issue_text_takes_the_file_and_line_in_the_projects_style():
    issue = Issue(("lanes", "2"), "7 steps; length is 8", "write one cell per step")
    assert issue.text("travis.yaml", 6) == "travis.yaml line 6, lane 2: 7 steps; length is 8; write one cell per step"
    assert Issue((), "a pattern is a mapping").text("x.yaml", 1) == "x.yaml line 1: a pattern is a mapping"
    assert check_pattern("nope")[0] is None


def test_a_long_name_is_a_warning_and_spread_without_strum_too():
    p = parse_pattern({"name": "A very long pattern name", "lanes": {1: "x" * 8}, "spread": 10})
    assert [w.field for w in p.warnings] == ["name", "spread"]


def test_rows_ignore_spaces_and_bars_and_canonical_data_round_trips():
    assert row_cells(". x |X  .") == [".", "x", "X", "."]
    assert row_text([0, 1, 2, 0, 0, 1, 0, 0], 4) == ". x X . | . x . ."
    p = parse_pattern({**ARP, "length": 16, "lanes": {1: "x . . . . . . . x . . . . . . ."}, "strum": "d" + " ." * 15})
    data = to_data(p)
    assert data["lanes"] == {"1": "x . . . . . . . | x . . . . . . ."} and data["strum"].startswith("d . . . . . . . |")
    assert json.loads(json.dumps(data)) == data and parse_pattern(data) == p



def test_the_schema_names_every_key_and_the_steps():   # docs/performer.schema.json follows the parser
    import json
    from pathlib import Path
    from performer import KEYS, STEPS
    schema = json.loads((Path(__file__).resolve().parents[1] / "docs" / "performer.schema.json").read_text())
    assert list(schema["properties"]) == list(KEYS) and schema["required"] == ["name", "lanes"]
    assert schema["properties"]["step"]["enum"] == list(STEPS)


def test_relative_lanes_r_and_a_parse_order_and_round_trip():   # chord-aware lanes (Phase 2)
    p = parse_pattern({"name": "T", "lanes": {"a": ". x . x", "R": "X . x .", 1: "x . . ."}})
    assert [lane for lane, _ in p.lanes] == [1, "R", "A"] and p.relative and p.highest_lane == 1
    assert p.hits_at(0) == ((1, 1), ("R", 2)) and p.cells("r") == (2, 0, 1, 0)
    data = to_data(p)
    assert list(data["lanes"]) == ["1", "R", "A"] and parse_pattern(json.loads(json.dumps(data))) == p
    assert issues({**ARP, "manual": ["R"]}) == [(("manual",), "manual: 'R' is not a lane a player holds; R and A "
                                                             "follow the chord; write lane numbers 1–16, e.g. [4, 5, 6]")]
    assert issues({"name": "N", "lanes": {"B": "x"}}) == [(("lanes", "B"), "lane B: 'B' is not a lane; lanes are 1–16 "
                                                          "(1 is the highest string), R (the root string) or A (the "
                                                          "alternate bass)")]
