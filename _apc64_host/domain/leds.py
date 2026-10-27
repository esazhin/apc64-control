"""LED looks and the full desired surface frame (contract q9: bound controls 25 % when idle, full when on)."""
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

from .controls import SURFACE, ControlId, LedKind, Strip
from .midi import Value14
from .palette import OFF, WHITE, Colour


class LedBehaviour(IntEnum):
    """The unit's LED behaviour codes (PROTOCOL-SPEC §6, [CODE] LedBehavior): the note-on channel."""
    BRIGHT_10 = 0
    BRIGHT_25 = 1
    BRIGHT_50 = 2
    BRIGHT_60 = 3
    BRIGHT_75 = 4
    BRIGHT_90 = 5
    FULL = 6
    PULSE_1_16 = 7
    PULSE_1_8 = 8
    PULSE_1_4 = 9
    PULSE_1_2 = 10
    BLINK_1_24 = 11
    BLINK_1_16 = 12
    BLINK_1_8 = 13
    BLINK_1_4 = 14
    BLINK_1_2 = 15


IDLE = LedBehaviour.BRIGHT_25
ON = LedBehaviour.FULL


@dataclass(frozen=True)
class LedState:
    colour: Colour
    behaviour: LedBehaviour = LedBehaviour.FULL

    @property
    def is_off(self) -> bool:
        return self.colour.is_off


LED_OFF = LedState(OFF, LedBehaviour.FULL)


def look(colour: Colour | None, on: bool) -> LedState:
    """An unbound control (colour None) is unlit; a bound one shows its colour at 25 %, or full while on."""
    if colour is None or colour.is_off:
        return LED_OFF
    return LedState(colour, ON if on else IDLE)


def nav_look(current: bool, defined: bool) -> LedState:
    """Scene and strip-mode LEDs: full = current, dim = defined, off = empty."""
    if current:
        return LedState(WHITE, ON)
    return LedState(WHITE, IDLE) if defined else LED_OFF


class StripBarStyle(StrEnum):
    BAR = "bar"
    BIPOLAR = "bipolar"


@dataclass(frozen=True)
class StripBarState:
    value: Value14 = Value14(0)
    colour: Colour = WHITE
    style: StripBarStyle = StripBarStyle.BAR
    lit: bool = True

    def __post_init__(self):
        object.__setattr__(self, "value", Value14(self.value))


BAR_OFF = StripBarState(Value14(0), OFF, StripBarStyle.BAR, lit=False)

LED_CONTROLS = tuple(e.id for e in SURFACE if e.led in (LedKind.RGB, LedKind.SINGLE))
BAR_STRIPS = tuple(e.id for e in SURFACE if e.led is LedKind.BAR)


@dataclass(frozen=True)
class LedFrame:
    """Every host-owned LED and strip bar of the surface; what the unit and the replica should show."""
    leds: dict[ControlId, LedState] = field(default_factory=dict)
    bars: dict[Strip, StripBarState] = field(default_factory=dict)

    @classmethod
    def for_state(cls, looks: dict[ControlId, LedState], bars: dict[Strip, StripBarState]) -> "LedFrame":
        """The full frame: every LED-bearing control and every strip, unlit where nothing says otherwise."""
        return cls({c: looks.get(c, LED_OFF) for c in LED_CONTROLS}, {s: bars.get(s, BAR_OFF) for s in BAR_STRIPS})

    @classmethod
    def blank(cls) -> "LedFrame":
        return cls.for_state({}, {})

    def led_changes(self, previous: "LedFrame | None") -> list[tuple[ControlId, LedState]]:
        old = previous.leds if previous else {}
        return [(c, s) for c, s in self.leds.items() if old.get(c) != s]

    def bar_changes(self, previous: "LedFrame | None") -> list[tuple[Strip, StripBarState]]:
        old = previous.bars if previous else {}
        return [(s, b) for s, b in self.bars.items() if old.get(s) != b]
