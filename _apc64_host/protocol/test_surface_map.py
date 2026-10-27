import pytest

from _apc64_host.domain.controls import (
    Encoder, EncoderPress, PadPos, SceneButton, Shift, Strip, StripModeButton, StripTouch, TrackButton,
    TrackControl, Transport, TransportName,
)
from _apc64_host.domain.effects import EncoderTurn, Press, Release, StripMove, UnitView, ViewReport
from _apc64_host.domain.leds import BAR_OFF, LED_OFF, LedBehaviour, LedState, StripBarState, StripBarStyle
from _apc64_host.domain.outbound import SysexCommand
from _apc64_host.domain.palette import parse_colour
from _apc64_host.protocol.conftest import capture
from _apc64_host.protocol.surface_map import (
    NOTE_OF, bindable_or_navigable, clear_frames, decode, encode_bar, encode_input, encode_led, encoder_steps,
    wired_controls,
)
from _apc64_host.protocol.sysex import command_of
from _apc64_host.protocol.stream import MidiStreamSplitter

DAW_CAPTURES = ["daw-mode-surface-capture-2026-10-22.log", "daw-mode-shift-and-strips-2026-10-22.log",
                "daw-mode-session-velocity-2026-10-23.log", "daw-mode-buttons-in-note-and-custom-view-2026-10-23.log",
                "daw-mode-views-velocity-aftertouch-2026-10-23.log"]


def test_pad_0_on_channel_7_is_pad_r1c1_at_full_velocity():   # A69
    assert decode(bytes.fromhex("96007F")) == Press(PadPos(1, 1), 127)
    assert decode(bytes.fromhex("860000")) == Release(PadPos(1, 1))
    assert decode(bytes.fromhex("963F7F")) == Press(PadPos(8, 8), 127)


def test_the_encoder_turn_decodes_multi_step_values():   # A63, d48
    assert decode(bytes.fromhex("B05A03")) == EncoderTurn(3)
    assert decode(bytes.fromhex("B05A01")) == EncoderTurn(1)
    assert decode(bytes.fromhex("B05A7F")) == EncoderTurn(-1)
    assert decode(bytes.fromhex("B05A41")) == EncoderTurn(-63)
    assert decode(bytes.fromhex("B05A00")) is None and encoder_steps(64) == 0
    assert decode(bytes.fromhex("905A7F")) == Press(EncoderPress(), 127)


def test_buttons_strips_and_views_decode_from_the_captures():
    assert decode(bytes.fromhex("90787F")) == Press(Shift(), 127)
    assert decode(bytes.fromhex("90407F")) == Press(TrackControl(1), 127)
    assert decode(bytes.fromhex("90647F")) == Press(TrackButton(1), 127)
    assert decode(bytes.fromhex("90707F")) == Press(SceneButton(1), 127)
    assert decode(bytes.fromhex("907E7F")) == Press(StripModeButton(6), 127)
    assert decode(bytes.fromhex("905B7F")) == Press(Transport(TransportName.PLAY), 127)
    assert decode(bytes.fromhex("90527F")) == Press(StripTouch(1), 127)
    assert decode(bytes.fromhex("E2007F")) == StripMove(Strip(3), 127 << 7)
    assert decode(bytes.fromhex("F047005319000102F7")) == ViewReport(UnitView.NOTE)


def test_every_surface_message_in_every_daw_capture_decodes():
    seen = set()
    for name in DAW_CAPTURES:
        splitter = MidiStreamSplitter()
        for port, raw in capture(name):
            if port != "DAW":
                continue
            for message in splitter.feed(raw):
                if message[0] == 0xF0 and message[1] == 0x7E:
                    continue   # the identity reply goes to the session
                event = decode(message)
                assert event is not None, (name, message.hex(" "))
                seen.add(type(event))
    assert seen >= {Press, Release, StripMove, ViewReport}


def test_the_wire_table_covers_every_surface_control_but_the_units_own():   # s75
    assert set(bindable_or_navigable()) <= wired_controls()
    assert Encoder() in wired_controls() and len(set(NOTE_OF.values())) == len(NOTE_OF)


@pytest.mark.parametrize("event", [Press(PadPos(3, 5), 100), Release(PadPos(8, 1)), Press(TrackButton(8), 127),
                                   Release(StripModeButton(2)), StripMove(Strip(8), 16383), EncoderTurn(-5),
                                   EncoderTurn(7), ViewReport(UnitView.CUSTOM)])
def test_input_encoding_is_the_inverse_of_decoding(event):
    assert decode(encode_input(event)) == event


def test_rgb_leds_carry_behaviour_and_colour_and_single_leds_carry_state():
    red = parse_colour("red")
    assert encode_led(PadPos(1, 1), LedState(red, LedBehaviour.FULL)) == bytes.fromhex("960005")
    assert encode_led(PadPos(1, 1), LedState(red, LedBehaviour.BRIGHT_25)) == bytes.fromhex("910005")
    assert encode_led(TrackButton(1), LedState(red, LedBehaviour.FULL)) == bytes.fromhex("966405")
    assert encode_led(SceneButton(1), LedState(parse_colour("white"), LedBehaviour.FULL)) == bytes.fromhex("967001")
    assert encode_led(SceneButton(1), LED_OFF) == bytes.fromhex("907000")


def test_strip_bars_set_colour_mode_and_position():
    state = StripBarState(8192, parse_colour("red"), StripBarStyle.BIPOLAR)
    assert encode_bar(Strip(2), state) == (bytes.fromhex("B07105"), bytes.fromhex("B06903"), bytes.fromhex("E10040"))
    assert encode_bar(Strip(1), BAR_OFF) == (bytes.fromhex("B06800"),)


def test_the_clear_frames_are_all_led_and_oled_messages_the_gate_allows():
    frames = clear_frames()
    kinds = {command_of(f) for f in frames}
    assert kinds == {SysexCommand.CHANNEL_MESSAGE, SysexCommand.OLED_TEXT}
    assert bytes.fromhex("900000") in frames and bytes.fromhex("B06800") in frames
