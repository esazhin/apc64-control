"""The small state holders HostSurface is composed of (contract §7.1: SRP via composition).

Each part owns one kind of state and knows nothing about the others; HostSurface decides when to use which.
"""
from dataclasses import dataclass

from .controls import ControlId, Strip
from .layout import (
    Action, BankNo, Binding, Layer, Layout, LayoutCatalog, LayoutId, Location, MessageKind, NavState, PageLocation,
    PageNo, StripBinding, ToggleState, Fixed, PressVelocity,
)
from .midi import ControlChange, ControlChange14, MidiMessage, NoteOff, NoteOn, PitchBend, ProgramChange, Value14


class Navigator:
    """Layout, page, bank and Shift; Shift counts as held when held on the unit or in the page (d90)."""

    def __init__(self):
        self.layout: LayoutId | None = None
        self.page = PageNo(1)
        self.bank = BankNo(1)
        self.unit_shift = False
        self.page_shift = False

    @property
    def shift(self) -> bool:
        return self.unit_shift or self.page_shift

    @property
    def state(self) -> NavState:
        return NavState(self.layout, self.page, self.bank, self.shift)


class ToggleBook:
    """Latching toggle states keyed by (layout, page, layer, control): each page keeps its own (d83)."""

    def __init__(self):
        self._on: dict[tuple, bool] = {}

    def get(self, layout: LayoutId, location: PageLocation) -> bool:
        return self._on.get((layout, location), False)

    def set(self, layout: LayoutId, location: PageLocation, on: bool):
        self._on[(layout, location)] = on

    def carry(self, old: Layout, new: Layout):
        """Across a hot reload keep the state of toggles whose binding did not change, reset the rest (d96)."""
        for key in [k for k in self._on if k[0] == old.id]:
            location = key[1]
            before, after = (_page_binding(lay, location) for lay in (old, new))
            if before != after or after is None or not after.toggle:
                del self._on[key]


def _page_binding(layout: Layout, location: PageLocation) -> Binding | None:
    page = layout.page(location.page)
    return page.binding(location.layer, location.control) if page else None


class FeedbackBook:
    """The last value each feedback rule received, per layout and location, shown or not (d104)."""

    def __init__(self):
        self._values: dict[tuple, int] = {}

    def put(self, layout: LayoutId, location: Location, value: int):
        self._values[(layout, location)] = value

    def get(self, layout: LayoutId, location: Location) -> int | None:
        return self._values.get((layout, location))


@dataclass(frozen=True)
class PressToken:
    """The binding that received a press; its release goes there even if the meaning changed (d50)."""
    control: ControlId
    binding: Binding | StripBinding | None
    layout: LayoutId | None
    location: PageLocation | None
    touch: Action | None = None


class PressLedger:
    def __init__(self):
        self._held: dict[ControlId, PressToken] = {}

    def press(self, token: PressToken):
        self._held[token.control] = token

    def release(self, control: ControlId) -> PressToken | None:
        return self._held.pop(control, None)

    def holds(self, layout: LayoutId | None, location: PageLocation) -> bool:
        token = self._held.get(location.control)
        return token is not None and token.layout == layout and token.location == location


class EncoderDial:
    """The absolute value the host keeps for an encoder binding: starts at 64, clamped 0–127 (q2)."""
    START = 64

    def __init__(self):
        self._values: dict[tuple, int] = {}

    def turn(self, layout: LayoutId, page: PageNo, steps: int) -> tuple[int, bool]:
        """The new value and whether it changed."""
        key = (layout, page)
        old = self._values.get(key, self.START)
        new = max(0, min(127, old + steps))
        self._values[key] = new
        return new, new != old


class BrowseCursor:
    """Shift + encoder layout browsing: which name the OLED shows, if browsing (contract inv5)."""

    def __init__(self):
        self.cursor: LayoutId | None = None
        self.active = False

    def turn(self, catalog: LayoutCatalog, current: LayoutId | None, steps: int) -> LayoutId | None:
        start = self.cursor if self.active else current
        self.cursor = catalog.step(start, steps)
        self.active = self.cursor is not None
        return self.cursor

    def stop(self) -> LayoutId | None:
        chosen, self.cursor, self.active = self.cursor, None, False
        return chosen


class StripPositions:
    """The last touched position of each strip per (layout, bank, strip), and what was last sent (d55, d86)."""

    def __init__(self):
        self._touched: dict[tuple, Value14] = {}
        self._sent: dict[tuple, MidiMessage] = {}

    def touch(self, layout: LayoutId, bank: BankNo, strip: Strip, value: Value14):
        self._touched[(layout, bank, strip)] = value

    def last(self, layout: LayoutId, bank: BankNo, strip: Strip) -> Value14:
        return self._touched.get((layout, bank, strip), Value14(0))

    def changed(self, key: tuple, message: MidiMessage) -> bool:
        """True (and remembered) when the message differs from the last one sent for this key."""
        if self._sent.get(key) == message:
            return False
        self._sent[key] = message
        return True

    def positions(self) -> dict[tuple, Value14]:
        return dict(self._touched)


# --- message building -----------------------------------------------------------------------------------
def press_message(action: Action, velocity: int) -> MidiMessage | None:
    """The 'on' message of a momentary binding (q4: Session pads send what the unit reports, 127)."""
    value = action.value
    if action.kind is MessageKind.NOTE:
        level = value.value if isinstance(value, Fixed) else velocity
        return NoteOn(action.channel, action.number, max(1, int(level)))
    if action.kind is MessageKind.CC:
        level = value.value if isinstance(value, Fixed) else (velocity if isinstance(value, PressVelocity) else 127)
        return ControlChange(action.channel, action.number, level)
    if action.kind is MessageKind.PROGRAM:
        return ProgramChange(action.channel, action.number)
    return None


def release_message(action: Action) -> MidiMessage | None:
    """The 'off' message of a momentary binding: note-off, CC 0, nothing for a program change."""
    if action.kind is MessageKind.NOTE:
        return NoteOff(action.channel, action.number)
    if action.kind is MessageKind.CC:
        return ControlChange(action.channel, action.number, 0)
    return None


def toggle_message(action: Action, on: bool) -> MidiMessage | None:
    """A latching toggle sends its on value (127) when switched on and its off value (0) when off (d94)."""
    values = action.value.values if isinstance(action.value, ToggleState) else None
    if action.kind is MessageKind.NOTE:
        if on:
            return NoteOn(action.channel, action.number, max(1, values.on if values else 127))
        return NoteOff(action.channel, action.number)
    if action.kind is MessageKind.CC:
        if values:
            return ControlChange(action.channel, action.number, values.on if on else values.off)
        fixed = action.value.value if isinstance(action.value, Fixed) else 127
        return ControlChange(action.channel, action.number, fixed if on else 0)
    if action.kind is MessageKind.PROGRAM:
        return ProgramChange(action.channel, action.number) if on else None
    return None


def position_message(action: Action, value: Value14) -> MidiMessage:
    """A strip position for its target: full 14-bit pitch bend, 7-bit CC (÷128) or a CC pair (d54)."""
    if action.kind is MessageKind.PITCHBEND:
        return PitchBend(action.channel, value)
    if action.kind is MessageKind.CC14:
        return ControlChange14(action.channel, action.number, action.lsb, value)
    return ControlChange(action.channel, action.number, value.to7())


def layer_of(shift: bool) -> Layer:
    return Layer.SHIFT if shift else Layer.BASE
