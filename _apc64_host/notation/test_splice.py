"""plan_splice: each tweak kind changes one entry line and leaves every other byte as written (T8)."""
import difflib

import pytest

from _apc64_host.domain.controls import PadPos, Strip, TrackButton
from _apc64_host.domain.layout import ContentHash, Layer, MessageKind, TweakField, TweakRequest
from _apc64_host.domain.palette import parse_colour
from _apc64_host.notation.compiler import compile_text
from _apc64_host.notation.splice import SpliceRefused, plan_splice, spec_of
from _apc64_host.notation.grammar import parse_phrase, render_phrase

JAM = """# Jam — drums and a mixer for the MPC.
# Written by the agent; tweaks from the page add one line each.
name: Jam
devices: {mpc: MPC Live III MIDI 1}
pages:
  1 Drums:
    pads r1c1-r1c8: notes from 36 colour blue  # bass line
    track 1: cc 20 toggle
  2 Keys:
    pad r1c1: note 60
banks:
  1 Mix:
    strips 1-8: cc 20-27
"""


def tweak(control, field, value, page=1, bank=None, layer=Layer.BASE):
    return TweakRequest("jam", layer, control, field, value, ContentHash.of(JAM),
                        page=None if bank else page, bank=bank)


def changed_lines(old: str, new: str) -> list[str]:
    return [line for line in difflib.ndiff(old.splitlines(), new.splitlines()) if line[:1] in "+-"]


def binding(text, control, page=1, layer=Layer.BASE):
    return compile_text(text, "jam.yaml").layout.page(page).binding(layer, control)


def test_a_colour_tweak_inside_a_range_adds_one_entry_and_keeps_every_other_byte():   # A135
    new = plan_splice(JAM, tweak(PadPos(1, 3), TweakField.COLOUR, "red"), "jam.yaml")
    assert changed_lines(JAM, new) == ["+     pad r1c3: note 38 on mpc ch 1 colour red"]
    assert binding(new, PadPos(1, 3)).colour == parse_colour("red")
    assert binding(new, PadPos(1, 4)).colour == parse_colour("blue")
    kept = [line for line in new.splitlines() if line != "    pad r1c3: note 38 on mpc ch 1 colour red"]
    assert kept == JAM.splitlines()


def test_setting_it_back_to_the_range_value_removes_the_entry_byte_for_byte():   # A137, d173
    red = plan_splice(JAM, tweak(PadPos(1, 3), TweakField.COLOUR, "red"), "jam.yaml")
    assert plan_splice(red, tweak(PadPos(1, 3), TweakField.COLOUR, "blue"), "jam.yaml") == JAM


def test_a_shift_tweak_on_page_2_adds_a_shift_block_there_only():   # A138
    new = plan_splice(JAM, tweak(PadPos(1, 1), TweakField.ASSIGNMENT, "note 52", page=2, layer=Layer.SHIFT),
                      "jam.yaml")
    assert changed_lines(JAM, new) == ["+     shift:", "+       pad r1c1: note 52"]
    assert binding(new, PadPos(1, 1), page=2, layer=Layer.SHIFT).actions[0].number == 52
    assert binding(new, PadPos(1, 1), page=2).actions[0].number == 60
    assert binding(new, PadPos(1, 1)).actions[0].number == 36


def test_a_second_shift_tweak_goes_into_the_existing_shift_block():
    once = plan_splice(JAM, tweak(PadPos(1, 1), TweakField.ASSIGNMENT, "note 52", page=2, layer=Layer.SHIFT), "jam.yaml")
    twice = plan_splice(once, tweak(PadPos(1, 2), TweakField.ASSIGNMENT, "note 53", page=2, layer=Layer.SHIFT),
                        "jam.yaml")
    assert changed_lines(once, twice) == ["+       pad r1c2: note 53"]


def test_an_entry_of_its_own_is_replaced_in_place_keeping_its_comment():
    text = JAM.replace("    track 1: cc 20 toggle", "    track 1: cc 20 toggle   # mute")
    new = plan_splice(text, tweak(TrackButton(1), TweakField.LABEL, "Mute all"), "jam.yaml")
    assert changed_lines(text, new) == ["-     track 1: cc 20 toggle   # mute",
                                        '+     track 1: cc 20 on mpc ch 1 toggle label "Mute all"  # mute']


def test_mode_and_assignment_tweaks_keep_the_other_options():
    toggled = plan_splice(JAM, tweak(PadPos(1, 2), TweakField.MODE, "toggle"), "jam.yaml")
    assert binding(toggled, PadPos(1, 2)).toggle and binding(toggled, PadPos(1, 2)).colour == parse_colour("blue")
    learned = plan_splice(JAM, tweak(PadPos(2, 1), TweakField.ASSIGNMENT, "cc 74 on mpc ch 1"), "jam.yaml")
    assert changed_lines(JAM, learned) == ["+     pad r2c1: cc 74 on mpc ch 1"]
    assert binding(learned, PadPos(2, 1)).actions[0].kind is MessageKind.CC


def test_a_strip_tweak_lands_in_its_bank():
    new = plan_splice(JAM, tweak(Strip(2), TweakField.COLOUR, "red", bank=1), "jam.yaml")
    assert changed_lines(JAM, new) == ["+     strip 2: cc 21 on mpc ch 1 colour red"]


def test_none_unbinds_one_control_of_a_range():
    new = plan_splice(JAM, tweak(PadPos(1, 5), TweakField.ASSIGNMENT, "none"), "jam.yaml")
    assert changed_lines(JAM, new) == ["+     pad r1c5: none"]
    assert binding(new, PadPos(1, 5)) is None and binding(new, PadPos(1, 6)) is not None


def test_an_invalid_tweak_is_refused_with_the_validation_issue_and_no_text():   # A136
    with pytest.raises(SpliceRefused) as refused:
        plan_splice(JAM, tweak(PadPos(1, 1), TweakField.ASSIGNMENT, "note 36 ch 17"), "jam.yaml")
    assert [i.problem for i in refused.value.issues] == ["channel must be 1–16"]
    with pytest.raises(SpliceRefused):
        plan_splice(JAM, tweak(Strip(1), TweakField.MODE, "toggle", bank=1), "jam.yaml")
    with pytest.raises(SpliceRefused) as refused:
        plan_splice(JAM, tweak(PadPos(1, 1), TweakField.COLOUR, "chartreuse"), "jam.yaml")
    assert refused.value.issues[0].problem == "unknown colour 'chartreuse'"


def test_flow_style_pages_and_missing_pages_are_refused_with_a_fix():
    flow = JAM.replace("  2 Keys:\n    pad r1c1: note 60\n", "  2 Keys: {pad r1c1: note 60}\n")
    with pytest.raises(SpliceRefused) as refused:
        plan_splice(flow, tweak(PadPos(1, 2), TweakField.ASSIGNMENT, "note 61", page=2), "jam.yaml")
    assert "one line" in refused.value.issues[0].problem
    with pytest.raises(SpliceRefused):
        plan_splice(JAM, tweak(PadPos(1, 1), TweakField.ASSIGNMENT, "note 1", page=5), "jam.yaml")


def test_a_tweak_that_changes_nothing_leaves_the_text_alone():
    assert plan_splice(JAM, tweak(PadPos(1, 3), TweakField.COLOUR, "blue"), "jam.yaml") == JAM


def test_spec_of_writes_bindings_back_in_phrase_form():
    text = """name: K
devices: {mpc: MPC, bitwig: Bitwig}
pages:
  1:
    pad r1c1: note 36 on mpc ch 10 velocity 100 colour red label "Kick drum"
    track 1: cc 20 value 64 on bitwig toggle feedback off dimwhite
    track 2: cc 21 on bitwig + program 5 on mpc
banks:
  1:
    strip 3: pitchbend on bitwig ch 2 touch note 60 bipolar colour blue feedback cc 3 from bitwig
"""
    layout = compile_text(text, "k.yaml").layout
    for control in (PadPos(1, 1), TrackButton(1), TrackButton(2)):
        original = layout.page(1).binding(Layer.BASE, control)
        written = render_phrase(spec_of(original))
        again = compile_text(text.replace(_line_of(text, control), f"    {control}: {written}"), "k.yaml")
        assert again.layout.page(1).binding(Layer.BASE, control) == original, written
    strip = layout.bank(1).binding(Layer.BASE, Strip(3))
    assert parse_phrase(render_phrase(spec_of(strip))).touch.first == "60"


def _line_of(text, control):
    return next(line for line in text.splitlines() if line.strip().startswith(f"{control}:"))
