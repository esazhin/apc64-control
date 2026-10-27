"""The one bidirectional wire table (contract §7.1): DAW-port bytes ↔ ControlId, for input decode and LED
encode alike (PROTOCOL-SPEC §5, §6).

Input: pads are notes 0–63 on channel 7 (pad 0 = r1c1, the bottom-left, contract d47 [TBD in DAW mode]);
buttons are notes 64–126; strip touches notes 82–89; strip positions 14-bit pitch bend with channel =
strip; the encoder turns as CC 0x5A (1–63 clockwise steps, 65–127 = 128 − v counter-clockwise steps, d48)
and presses as note 0x5A [CODE]. Output: RGB LEDs are note-on with channel = behaviour and velocity =
palette index; single LEDs note-on with channel = state − 1 and velocity 1 (off: channel 0, velocity 0);
strip bars CC 0x70+i colour, CC 0x68+i mode and pitch bend position.
"""
from ..domain.controls import (
    SURFACE, ControlId, ControlRole, Encoder, EncoderPress, FunctionButton, FunctionName, LedKind, ModeButton,
    ModeName, Nav, NavName, PadPos, SceneButton, Shift, Strip, StripModeButton, StripTouch, TrackButton,
    TrackControl, Transport, TransportName, entry,
)
from ..domain.effects import EncoderTurn, Press, Release, StripMove, SurfaceInput, ViewReport
from ..domain.leds import LedFrame, LedState, StripBarState, StripBarStyle
from ..domain.oled import OledText
from .sysex import encode_view_report, oled_frames, view_report

PAD_STATUS_CHANNEL = 6       # 0-based: channel 7 carries the grid pads
ENCODER = 0x5A
STRIP_COLOUR_CC, STRIP_MODE_CC = 0x70, 0x68
_BAR_MODE = {StripBarStyle.BAR: 1, StripBarStyle.BIPOLAR: 3}   # white bar / white bipolar (0 = off)


def _wire_notes() -> dict[ControlId, int]:
    notes: dict[ControlId, int] = {PadPos.from_index(i): i for i in range(64)}
    for n in range(1, 9):
        notes[TrackControl(n)] = 0x40 + n - 1
        notes[StripTouch(n)] = 0x52 + n - 1
        notes[TrackButton(n)] = 0x64 + n - 1
        notes[SceneButton(n)] = 0x70 + n - 1
    for i, name in enumerate(FunctionName):
        notes[FunctionButton(name)] = 0x48 + i
    for i, name in enumerate(TransportName):
        notes[Transport(name)] = 91 + i
    for i, name in enumerate(NavName):   # down, up, left, right
        notes[Nav(name)] = 94 + i
    for i, name in enumerate(ModeName):
        notes[ModeButton(name)] = 108 + i
    notes[Shift()] = 120
    for n in range(1, 7):
        notes[StripModeButton(n)] = 121 + n - 1
    notes[EncoderPress()] = ENCODER
    return notes


NOTE_OF: dict[ControlId, int] = _wire_notes()
CONTROL_OF: dict[int, ControlId] = {note: control for control, note in NOTE_OF.items()}
assert len(CONTROL_OF) == len(NOTE_OF), "two controls share a wire note"


def wired_controls() -> set[ControlId]:
    """Every control the table can decode: notes, strip pitch bends and the encoder CC."""
    return set(NOTE_OF) | {Strip(n) for n in range(1, 9)} | {Encoder()}


def encoder_steps(value: int) -> int:
    """CC 0x5A value → detents: 1–63 clockwise, 65–127 counter-clockwise (128 − v), 0 and 64 nothing."""
    if 1 <= value <= 63:
        return value
    if 65 <= value <= 127:
        return value - 128
    return 0


def decode(message: bytes) -> SurfaceInput | None:
    """One whole DAW-port message → SurfaceInput, or None for anything that is not surface input."""
    message = bytes(message)
    if not message:
        return None
    if message[0] == 0xF0:
        view = view_report(message)
        return ViewReport(view) if view is not None else None
    kind = message[0] & 0xF0
    if len(message) == 3 and kind in (0x80, 0x90):
        control = CONTROL_OF.get(message[1])
        if control is None:
            return None
        return Press(control, message[2]) if kind == 0x90 and message[2] else Release(control)
    if len(message) == 3 and kind == 0xE0 and message[0] & 0x0F < 8:
        return StripMove(Strip((message[0] & 0x0F) + 1), message[1] | (message[2] << 7))
    if len(message) == 3 and kind == 0xB0 and message[1] == ENCODER:
        steps = encoder_steps(message[2])
        return EncoderTurn(steps) if steps else None
    return None


def encode_input(event: SurfaceInput) -> bytes:
    """The bytes the unit sends for an input, exactly as the fixtures show them (for simulators and tests)."""
    match event:
        case Press(control=control, velocity=velocity):
            channel = PAD_STATUS_CHANNEL if isinstance(control, PadPos) else 0
            return bytes([0x90 | channel, NOTE_OF[control], velocity])
        case Release(control=control):
            channel = PAD_STATUS_CHANNEL if isinstance(control, PadPos) else 0
            return bytes([0x80 | channel, NOTE_OF[control], 0])
        case StripMove(strip=strip, value=value):
            return bytes([0xE0 | (strip.n - 1), value.lsb, value.msb])
        case EncoderTurn(steps=steps):
            return bytes([0xB0, ENCODER, steps if steps > 0 else 128 + steps])
        case ViewReport(view=view):
            return encode_view_report(view)
    raise TypeError(f"not a surface input: {event!r}")


# --- output ------------------------------------------------------------------------------------------------
def encode_led(control: ControlId, state: LedState) -> bytes:
    note = NOTE_OF[control]
    if state.is_off:
        return bytes([0x90, note, 0])
    if entry(control).led is LedKind.RGB:
        return bytes([0x90 | int(state.behaviour), note, state.colour.index])
    return bytes([0x90 | int(state.behaviour), note, 1])


def encode_bar(strip: Strip, state: StripBarState) -> tuple[bytes, ...]:
    i = strip.n - 1
    if not state.lit:
        return (bytes([0xB0, STRIP_MODE_CC + i, 0]),)
    return (bytes([0xB0, STRIP_COLOUR_CC + i, state.colour.index]),
            bytes([0xB0, STRIP_MODE_CC + i, _BAR_MODE[state.style]]),
            bytes([0xE0 | i, state.value.lsb, state.value.msb]))


def encode_frame(frame: LedFrame) -> list[bytes]:
    """Every LED and bar of a frame, one message per frame (so the gate can classify each)."""
    out = [encode_led(c, s) for c, s in frame.leds.items()]
    for strip, state in frame.bars.items():
        out += encode_bar(strip, state)
    return out


def clear_frames() -> list[bytes]:
    """Everything dark and the OLED blank: what release sends before DAW mode off (d35)."""
    return encode_frame(LedFrame.blank()) + list(oled_frames(OledText.blank()))


def bindable_or_navigable() -> list[ControlId]:
    """The SURFACE controls the wire table must cover: all but the unit's own view buttons."""
    return [e.id for e in SURFACE if e.role is not ControlRole.DEVICE_LOCAL]
