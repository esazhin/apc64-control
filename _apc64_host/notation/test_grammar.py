import pytest

from _apc64_host.domain.layout import MessageKind
from _apc64_host.notation.grammar import (
    CONTROL_KEY, PhraseError, loose_control_line, parse_phrase, parse_routing, render_phrase, tokens, yaml_scalar,
)


def test_phrases_tokenise_with_quotes_ranges_and_signed_numbers():
    assert tokens('note 36 - 51 label "Kick drum" + program 5 transpose +12') == [
        "note", "36-51", "label", '"Kick drum"', "+", "program", "5", "transpose", "+12"]


def test_a_message_with_target_and_options_parses():
    spec = parse_phrase('notes from 36 on MPC ch 10 toggle 100/0 colour red velocity 90 label "Kick"')
    message = spec.messages[0]
    assert (message.kind, message.first, message.ascending, message.device, message.channel) == (
        MessageKind.NOTE, "36", True, "mpc", 10)
    assert (spec.toggle, spec.toggle_values, spec.colour, spec.velocity, spec.label) == (
        True, (100, 0), "red", 90, "Kick")


def test_several_messages_need_a_plus_between_them():
    spec = parse_phrase("cc 20 value 127 + program 5")
    assert [(m.kind, m.first, m.value) for m in spec.messages] == [(MessageKind.CC, "20", 127),
                                                                   (MessageKind.PROGRAM, "5", None)]
    with pytest.raises(PhraseError) as raised:
        parse_phrase("cc 20 program 5")
    assert "'+'" in raised.value.problem


def test_strip_phrases_take_touch_style_and_feedback():
    spec = parse_phrase("pitchbend on bitwig ch 2 touch note 60 bipolar feedback cc 3 from bitwig colours 0:off 127:green")
    assert spec.messages[0].kind is MessageKind.PITCHBEND and spec.touch.first == "60"
    assert spec.style == "bipolar" and spec.feedback.kind is MessageKind.CC and spec.feedback.device == "bitwig"
    assert spec.feedback.colours == [(0, "off"), (127, "green")]
    assert parse_phrase("cc14 20/52").messages[0].lsb == 52


@pytest.mark.parametrize("text, problem", [
    ("", "the binding is empty"),
    ("knob 3", "'knob' is not a message"),
    ("note", "'note' needs a number"),
    ("note 36 sparkle", "unexpected 'sparkle'"),
    ("note 36 ch", "expected a channel 1–16"),
    ('note 36 label "Kick', "the label's quotes are not closed"),
])
def test_bad_phrases_name_the_problem_and_a_fix(text, problem):
    with pytest.raises(PhraseError) as raised:
        parse_phrase(text)
    assert raised.value.problem.startswith(problem) and raised.value.fix


def test_rendering_is_the_inverse_of_parsing():
    for text in ("note 36 on mpc ch 10", "cc 20 value 64 on mpc ch 1 + program 5 on mpc ch 1 toggle",
                 'notes from 36 on mpc ch 10 velocity 100 colour red label "Kick drum"',
                 "pitchbend on bitwig ch 2 touch note 60 on bitwig ch 2 bipolar colour blue feedback cc 3 from bitwig",
                 "cc 20 on bitwig ch 1 toggle feedback off dimwhite"):
        assert parse_phrase(render_phrase(parse_phrase(text))) == parse_phrase(text)
        assert render_phrase(parse_phrase(text)) == text


def test_routing_phrases():
    spec = parse_routing("to mpc ch 2 aftertouch pressure transpose -12 remap 36>38 C1>D1")
    assert (spec.device, spec.channel, spec.aftertouch, spec.transpose) == ("mpc", 2, "pressure", -12)
    assert spec.remap == [("36", "38"), ("C1", "D1")]
    with pytest.raises(PhraseError):
        parse_routing("mpc aftertouch squeeze")


def test_a_line_naming_a_control_without_its_colon_is_spotted():
    assert loose_control_line("    pads r1c1-r1c8 notes 36   # bass") == ("pads r1c1-r1c8", "notes 36")
    assert loose_control_line("  play cc 118") == ("play", "cc 118")
    for fine in ("    pads r1c1-r1c8: notes 36", "  # play cc 118", "name: Jam", "  - cc 20", "  shift:"):
        assert loose_control_line(fine) is None


def test_control_keys_and_yaml_scalars():
    assert CONTROL_KEY.match("pads r1c1-r2c8") and CONTROL_KEY.match("encoder press") and CONTROL_KEY.match("track 3")
    assert not CONTROL_KEY.match("scene 1")
    assert yaml_scalar("note 36 colour red") == "note 36 colour red"
    assert yaml_scalar('note 36 label "K #1"') == "'note 36 label \"K #1\"'"
    assert yaml_scalar("note 36 label \"it's: here\"") == "'note 36 label \"it''s: here\"'"
