"""LearnService: touch-select and MIDI-learn (contract d164–d168, pi12).

While learn is on (TOUCH or MIDI), a touch on the unit or in the replica only selects that control: the
engine runs no binding for it (d168). Navigation (scene and strip-mode buttons) and Shift still work, so
any page, bank and layer can be reached; a strip touch selects the strip. In MIDI mode the service
listens on the chosen input port; the first note-on, CC, program change or pitch bend that arrives becomes
the selected control's binding on the current page (or bank) and layer, sent to the device that owns that
port, saved as one assignment tweak (d167). Leaving MIDI-learn before a message arrives changes nothing.
"""
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from ..domain.controls import ControlId, DeviceLocal, SceneButton, Shift, Strip, StripModeButton, StripTouch
from ..domain.layout import Layout, NavState, TweakField, TweakRequest
from ..domain.midi import ControlChange, MidiMessage, NoteOn, PitchBend, ProgramChange
from .ports import Cancellable, FeedbackInputs
from .tweaks import Invalid, Saved, Stale

CAPTURED = "captured"
PASS = "pass"


class LearnKind(StrEnum):
    OFF = "off"
    TOUCH = "touch"
    MIDI = "midi"


@dataclass(frozen=True)
class LearnMode:
    kind: LearnKind
    port: str | None = None

    @classmethod
    def off(cls) -> "LearnMode":
        return cls(LearnKind.OFF)

    @classmethod
    def touch(cls) -> "LearnMode":
        return cls(LearnKind.TOUCH)

    @classmethod
    def midi(cls, port: str) -> "LearnMode":
        return cls(LearnKind.MIDI, port)


@dataclass(frozen=True)
class LearnStatus:
    mode: LearnKind = LearnKind.OFF
    selected: ControlId | None = None
    port: str | None = None       # the port listened on (MIDI mode)
    device: str | None = None     # the device that owns it
    last: str | None = None       # what the last capture did


@dataclass(frozen=True)
class LearnOk:
    status: LearnStatus


@dataclass(frozen=True)
class UnknownPort:
    port: str
    allowed: tuple[str, ...]


def phrase_of(message: MidiMessage, device: str) -> str | None:
    """The binding phrase for a captured message, or None for messages that cannot be a binding."""
    match message:
        case NoteOn() if message.velocity > 0:
            return f"note {message.note} on {device} ch {message.channel}"
        case ControlChange():
            return f"cc {message.control} on {device} ch {message.channel}"
        case ProgramChange():
            return f"program {message.program} on {device} ch {message.channel}"
        case PitchBend():
            return f"pitchbend on {device} ch {message.channel}"
    return None


class LearnService:
    def __init__(self, tweaks, feedback: FeedbackInputs,
                 context: Callable[[], tuple[Layout | None, NavState]]):
        self._tweaks = tweaks
        self._feedback = feedback
        self._context = context
        self._status = LearnStatus()
        self._listening: Cancellable | None = None
        self._subscribers: list[Callable[[LearnStatus], None]] = []

    def status(self) -> LearnStatus:
        return self._status

    def subscribe(self, callback: Callable[[LearnStatus], None]) -> None:
        self._subscribers.append(callback)

    def set_mode(self, mode: LearnMode) -> LearnOk | UnknownPort:
        if mode.kind is LearnKind.MIDI:
            layout, _ = self._context()
            device = self._device_for(layout, mode.port or "")
            if device is None:
                return UnknownPort(mode.port or "", tuple(layout.devices) if layout else ())
            self._stop_listening()
            self._listening = self._feedback.listen(device.pattern, self._heard)
            self._set(LearnStatus(LearnKind.MIDI, self._status.selected, str(device.pattern), str(device.name),
                                  self._status.last))
        elif mode.kind is LearnKind.TOUCH:
            self._stop_listening()
            self._set(LearnStatus(LearnKind.TOUCH, self._status.selected, last=self._status.last))
        else:
            self._stop_listening()
            self._set(LearnStatus(last=self._status.last))
        return LearnOk(self._status)

    def select(self, control: ControlId) -> None:
        if isinstance(control, StripTouch):
            control = Strip(control.n)
        self._set(LearnStatus(self._status.mode, control, self._status.port, self._status.device, self._status.last))

    def intercept(self, control: ControlId) -> str:
        """CAPTURED: the engine runs no binding for this touch. PASS: handle it as usual."""
        if self._status.mode is LearnKind.OFF:
            return PASS
        if isinstance(control, (SceneButton, StripModeButton, Shift, DeviceLocal)):
            return PASS
        self.select(control)
        return CAPTURED

    # --- MIDI-learn ---------------------------------------------------------------------------------------
    @staticmethod
    def _device_for(layout: Layout | None, port: str):
        if layout is None or not port:
            return None
        if port in layout.devices:
            return layout.devices[port]
        return next((d for d in layout.devices.values() if d.pattern.matches(port)), None)

    def _heard(self, message: MidiMessage) -> None:
        status = self._status
        if status.mode is not LearnKind.MIDI or status.selected is None:
            return
        phrase = phrase_of(message, status.device)
        if phrase is None:
            return
        self._stop_listening()
        layout, nav = self._context()
        control = status.selected
        strip = isinstance(control, Strip)
        answer = None
        if layout is not None:
            base = self._tweaks.current_hash(layout.id)
            request = TweakRequest(layout.id, nav.layer, control, TweakField.ASSIGNMENT, phrase, base,
                                   page=None if strip else nav.page, bank=nav.bank if strip else None)
            answer = self._tweaks.apply(request) if base is not None else Stale()
        self._set(LearnStatus(LearnKind.TOUCH, control, last=f"{control}: {phrase} {_verdict(answer)}"))

    def _stop_listening(self) -> None:
        if self._listening is not None:
            self._listening.cancel()
            self._listening = None

    def _set(self, status: LearnStatus) -> None:
        self._status = status
        for callback in list(self._subscribers):
            callback(status)


def _verdict(answer) -> str:
    match answer:
        case Saved():
            return "saved"
        case Stale(message=message):
            return f"not saved: {message}"
        case Invalid(issues=issues):
            return "not saved: " + "; ".join(i.message() for i in issues)
    return "not saved: no layout"
