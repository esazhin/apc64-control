from _apc64_host.domain.controls import PadPos, SceneButton, Strip, StripTouch, Encoder
from _apc64_host.domain.leds import (
    BAR_OFF, LED_OFF, LedBehaviour, LedFrame, LedState, StripBarState, look, nav_look,
)
from _apc64_host.domain.palette import parse_colour

RED = parse_colour("red")


def test_bound_controls_are_dim_when_idle_and_full_when_on_and_unbound_ones_are_dark():
    assert look(RED, False) == LedState(RED, LedBehaviour.BRIGHT_25)
    assert look(RED, True) == LedState(RED, LedBehaviour.FULL)
    assert look(None, True) == LED_OFF and LED_OFF.is_off


def test_navigation_leds_show_current_defined_and_empty():
    assert nav_look(True, True).behaviour is LedBehaviour.FULL
    assert nav_look(False, True).behaviour is LedBehaviour.BRIGHT_25
    assert nav_look(False, False) == LED_OFF


def test_the_frame_covers_every_led_control_and_strip_and_diffs():
    frame = LedFrame.for_state({PadPos(1, 1): look(RED, False)}, {Strip(1): StripBarState(100)})
    assert frame.leds[PadPos(1, 1)] == look(RED, False) and frame.leds[SceneButton(8)] == LED_OFF
    assert StripTouch(1) not in frame.leds and Encoder() not in frame.leds
    assert len(frame.bars) == 8 and frame.bars[Strip(2)] == BAR_OFF
    blank = LedFrame.blank()
    assert blank.led_changes(frame) == [(PadPos(1, 1), LED_OFF)]
    assert blank.bar_changes(frame) == [(Strip(1), BAR_OFF)]
    assert len(frame.led_changes(None)) == len(frame.leds)
