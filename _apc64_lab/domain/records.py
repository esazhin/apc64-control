"""The unit's memory records (PROTOCOL-SPEC §8.1/§8.2; contract §7.1: value objects with invariant-preserving
mutators, inv3).

A project is 880 raw bytes: 64 pad records × 12 (r1c1 first), then 8 strip records × 14. The global block is
56 raw bytes. Every mutator here sets only the fields it names and carries every other byte through
unchanged: pad byte 11, strip bytes 3 and 5 and global bytes 0–19 are never interpreted (inv3).
"""
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Mapping

from _apc64_host.domain.controls import PadPos, Strip
from _apc64_host.domain.issues import DomainInvariantError

from .pads import PAD_COUNT, PadAssignment, PadGrid, Rgb

PAD_SIZE, STRIP_SIZE, STRIP_COUNT = 12, 14, 8
PROJECT_SIZE = PAD_COUNT * PAD_SIZE + STRIP_COUNT * STRIP_SIZE   # 880
GLOBAL_SIZE = 56
ALL_OUTPUTS = 0x07


class RecordLengthError(ValueError):
    """Raw bytes of the wrong length for a record (contract d66, A47, A51)."""

    def __init__(self, what: str, received: int, expected: int):
        self.what, self.received, self.expected = what, received, expected
        super().__init__(f"{what} holds {received} bytes, expected {expected}")


def _rgb(raw: bytes, at: int) -> Rgb:
    return Rgb(raw[at], raw[at + 1], raw[at + 2])


# --- pads ------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PadRecord:
    """b0 note-in-octave, b1 poly aftertouch, b2 channel (1-based), b3 octave, b4–6 rest RGB, b7–9 pressed RGB,
    b10 output bitmask (07 all, 00 silent), b11 unknown (kept)."""
    raw: bytes

    def __post_init__(self):
        object.__setattr__(self, "raw", bytes(self.raw))
        if len(self.raw) != PAD_SIZE:
            raise RecordLengthError("a pad record", len(self.raw), PAD_SIZE)

    note_in_octave = property(lambda self: self.raw[0])
    aftertouch = property(lambda self: self.raw[1] == 1)
    channel = property(lambda self: self.raw[2])
    octave = property(lambda self: self.raw[3])
    note = property(lambda self: self.raw[3] * 12 + self.raw[0])
    rest = property(lambda self: _rgb(self.raw, 4))
    pressed = property(lambda self: _rgb(self.raw, 7))
    outputs = property(lambda self: self.raw[10])
    unknown = property(lambda self: self.raw[11])

    @property
    def silent(self) -> bool:
        return self.outputs == 0

    def with_fields(self, **values) -> "PadRecord":
        """Set named fields (note, aftertouch, channel, rest, pressed, outputs); every other byte is kept."""
        raw = bytearray(self.raw)
        for name, value in values.items():
            if name == "note":
                raw[0], raw[3] = value % 12, value // 12
            elif name == "aftertouch":
                raw[1] = 1 if value else 0
            elif name == "channel":
                raw[2] = value
            elif name in ("rest", "pressed"):
                at = 4 if name == "rest" else 7
                raw[at:at + 3] = Rgb.of(value).bytes
            elif name == "outputs":
                raw[10] = value
            else:
                raise KeyError(name)
        return PadRecord(bytes(raw))

    def with_assignment(self, pad: PadAssignment) -> "PadRecord":
        """A generated pad (d43): note, aftertouch flag, channel, colours and all outputs. A silent pad is
        unlit and sends nothing (rest/pressed black, outputs 00) with its note bytes kept, as the prototype."""
        if pad.silent:
            return self.with_fields(rest=Rgb(0, 0, 0), pressed=Rgb(0, 0, 0), outputs=0)
        return self.with_fields(note=pad.note, aftertouch=pad.aftertouch, channel=int(pad.channel),
                                rest=pad.rest, pressed=pad.pressed, outputs=ALL_OUTPUTS)

    def describe(self) -> dict:
        return {"note": self.note, "aftertouch": self.aftertouch, "channel": self.channel,
                "rest": self.rest.to_hex(), "pressed": self.pressed.to_hex(), "outputs": self.outputs,
                "unknown": self.unknown}


# --- strips ----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class StripAssignment:
    """A generated strip (§2.7 q6): a 7-bit CC, or a 14-bit MSB/LSB pair, its channel, bar and indicator
    colours, bipolar display and outputs."""
    cc: int
    channel: int = 1
    lsb: int | None = None          # set: 14-bit (resolution 2) with this LSB controller
    bar: Rgb = Rgb(255, 0, 0)       # factory: red bar …
    indicator: Rgb = Rgb(255, 255, 255)   # … white tip
    bipolar: bool = False
    outputs: int = ALL_OUTPUTS

    def __post_init__(self):
        for name, value, low, high, fix in (("cc", self.cc, 0, 127, "controllers are 0–127"),
                                            ("channel", self.channel, 1, 16, "channels are 1–16"),
                                            ("outputs", self.outputs, 0, 7, "outputs are a 0–7 bitmask")):
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise DomainInvariantError(name, f"{name} {value}", fix, joiner=": ")
        if self.lsb is not None and (isinstance(self.lsb, bool) or not isinstance(self.lsb, int)
                                     or not 0 <= self.lsb <= 127):
            raise DomainInvariantError("lsb", f"lsb {self.lsb}", "controllers are 0–127", joiner=": ")
        object.__setattr__(self, "bar", Rgb.of(self.bar))
        object.__setattr__(self, "indicator", Rgb.of(self.indicator))


@dataclass(frozen=True)
class StripRecord:
    """b0 resolution (1 = 7-bit CC, 2 = 14-bit MSB+LSB), b1 CC (MSB), b2 LSB CC, b3 unknown (kept), b4 channel,
    b5 unknown (kept), b6–8 bar RGB, b9–11 indicator RGB, b12 output bitmask, b13 bipolar display."""
    raw: bytes

    def __post_init__(self):
        object.__setattr__(self, "raw", bytes(self.raw))
        if len(self.raw) != STRIP_SIZE:
            raise RecordLengthError("a strip record", len(self.raw), STRIP_SIZE)

    resolution = property(lambda self: self.raw[0])
    cc = property(lambda self: self.raw[1])
    lsb = property(lambda self: self.raw[2])
    unknown3 = property(lambda self: self.raw[3])
    channel = property(lambda self: self.raw[4])
    unknown5 = property(lambda self: self.raw[5])
    bar = property(lambda self: _rgb(self.raw, 6))
    indicator = property(lambda self: _rgb(self.raw, 9))
    outputs = property(lambda self: self.raw[12])
    bipolar = property(lambda self: self.raw[13] == 1)

    def with_fields(self, **values) -> "StripRecord":
        raw = bytearray(self.raw)
        offsets = {"resolution": 0, "cc": 1, "lsb": 2, "channel": 4, "outputs": 12}
        for name, value in values.items():
            if name in offsets:
                raw[offsets[name]] = value
            elif name in ("bar", "indicator"):
                at = 6 if name == "bar" else 9
                raw[at:at + 3] = Rgb.of(value).bytes
            elif name == "bipolar":
                raw[13] = 1 if value else 0
            else:
                raise KeyError(name)
        return StripRecord(bytes(raw))

    def with_assignment(self, strip: StripAssignment) -> "StripRecord":
        """Writes every field the strip section names; bytes 3 and 5 are kept (§2.7 q6, inv3). In 7-bit mode
        the LSB byte is kept as read too."""
        values: dict[str, Any] = {"resolution": 2 if strip.lsb is not None else 1, "cc": strip.cc,
                                  "channel": strip.channel, "bar": strip.bar, "indicator": strip.indicator,
                                  "outputs": strip.outputs, "bipolar": strip.bipolar}
        if strip.lsb is not None:
            values["lsb"] = strip.lsb
        return self.with_fields(**values)

    def describe(self) -> dict:
        return {"resolution": self.resolution, "cc": self.cc, "lsb": self.lsb, "channel": self.channel,
                "bar": self.bar.to_hex(), "indicator": self.indicator.to_hex(), "outputs": self.outputs,
                "bipolar": self.bipolar, "unknown": [self.unknown3, self.unknown5]}


# --- the project -----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ProjectRecord:
    """One project slot: 880 bytes. Equality is byte equality (d68: an identical push writes nothing)."""
    raw: bytes

    def __post_init__(self):
        object.__setattr__(self, "raw", bytes(self.raw))
        if len(self.raw) != PROJECT_SIZE:
            raise RecordLengthError("a project record", len(self.raw), PROJECT_SIZE)

    @classmethod
    def from_raw(cls, raw: bytes) -> "ProjectRecord":
        return cls(bytes(raw))

    def to_raw(self) -> bytes:
        return self.raw

    @classmethod
    def from_parts(cls, pads, strips) -> "ProjectRecord":
        pads, strips = tuple(pads), tuple(strips)
        if len(pads) != PAD_COUNT or len(strips) != STRIP_COUNT:
            raise RecordLengthError("a project", len(pads) * PAD_SIZE + len(strips) * STRIP_SIZE, PROJECT_SIZE)
        return cls(b"".join(p.raw for p in pads) + b"".join(s.raw for s in strips))

    @property
    def pads(self) -> tuple[PadRecord, ...]:
        return tuple(PadRecord(self.raw[i * PAD_SIZE:(i + 1) * PAD_SIZE]) for i in range(PAD_COUNT))

    @property
    def strips(self) -> tuple[StripRecord, ...]:
        start = PAD_COUNT * PAD_SIZE
        return tuple(StripRecord(self.raw[start + i * STRIP_SIZE:start + (i + 1) * STRIP_SIZE])
                     for i in range(STRIP_COUNT))

    def pad(self, pad: PadPos) -> PadRecord:
        return self.pads[pad.index]

    def strip(self, strip: Strip | int) -> StripRecord:
        number = strip.n if isinstance(strip, Strip) else int(strip)
        return self.strips[number - 1]

    def with_pad_records(self, changes: Mapping[int, PadRecord]) -> "ProjectRecord":
        pads = list(self.pads)
        for index, record in changes.items():
            pads[index] = record
        return ProjectRecord.from_parts(pads, self.strips)

    def with_strip_records(self, changes: Mapping[int, StripRecord]) -> "ProjectRecord":
        strips = list(self.strips)
        for number, record in changes.items():
            strips[number - 1] = record
        return ProjectRecord.from_parts(self.pads, strips)

    def with_pads(self, grid: PadGrid) -> "ProjectRecord":
        """The generated pads merged onto this record; strips and every unknown byte unchanged (A2)."""
        return ProjectRecord.from_parts([record.with_assignment(pad) for record, pad in zip(self.pads, grid.pads)],
                                        self.strips)

    def with_strips(self, strips: Mapping[int, StripAssignment]) -> "ProjectRecord":
        """The optional strip section (§2.7 q6), strip number 1–8 → assignment; other strips as read."""
        for number in strips:
            Strip(number)
        return self.with_strip_records({n: self.strips[n - 1].with_assignment(a) for n, a in strips.items()})

    def with_known_from(self, source: "ProjectRecord") -> "ProjectRecord":
        """`source`'s interpreted bytes onto this record, keeping this record's unknown bytes (pad byte 11, strip
        bytes 3 and 5): a captured or imported project pushed to a slot (inv3)."""
        pads = [PadRecord(theirs.raw[:11] + ours.raw[11:]) for ours, theirs in zip(self.pads, source.pads)]
        strips = [StripRecord(theirs.raw[:3] + ours.raw[3:4] + theirs.raw[4:5] + ours.raw[5:6] + theirs.raw[6:])
                  for ours, theirs in zip(self.strips, source.strips)]
        return ProjectRecord.from_parts(pads, strips)

    def differences(self, other: "ProjectRecord") -> list[str]:
        """Which pads and strips differ ('pad r3c4', 'strip 3'), for read-back warnings (inv4)."""
        found = [str(PadPos.from_index(i)) for i, (a, b) in enumerate(zip(self.pads, other.pads)) if a != b]
        found += [f"strip {i + 1}" for i, (a, b) in enumerate(zip(self.strips, other.strips)) if a != b]
        return found


# --- global settings -------------------------------------------------------------------------------------
class DeviceMode(IntEnum):
    ABLETON_LIVE = 0
    STANDALONE = 1


class StandaloneSync(IntEnum):
    INTERNAL = 0
    USB = 1
    DIN = 2


DEVICE_MODE_TEXT = {DeviceMode.ABLETON_LIVE: "Ableton Live", DeviceMode.STANDALONE: "Standalone"}
SYNC_TEXT = {StandaloneSync.INTERNAL: "Internal", StandaloneSync.USB: "USB", StandaloneSync.DIN: "MIDI DIN"}
LED_LEVELS = (25, 50, 75, 100)        # b55 0–3
CV_COUNT, DRUM_COUNT = 8, 16
CV_SOURCE_MAX = 15                     # [TBD] the manual §5.6 list length; bounded until known
# d90: the manual §5.6 names, [TBD] until a live read confirms them. Only these three were seen in
# NOTES-daw-mode.md (2026-10-22); others show as their number.
CV_SOURCE_NAMES = {0: "Pitch-Last", 1: "Pitch-Low", 3: "Gate-Last"}


def cv_source_text(number: int) -> str:
    name = CV_SOURCE_NAMES.get(number)
    return f"{number} {name} [TBD]" if name else f"{number} [TBD]"


def sync_out_text(mask: int) -> str:
    names = [name for bit, name in ((1, "USB"), (2, "MIDI")) if mask & bit]
    return " + ".join(names) if names else "off"


@dataclass(frozen=True)
class GlobalSettings:
    """b0–19 unknown (kept), b20 device mode, b21 standalone sync, b22 sync out (bit0 USB, bit1 MIDI),
    b23–30 CV1–8 source, b31–38 CV1–8 channel, b39–54 drum 1–16 note, b55 LED level (0–3 = 25–100 %)."""
    raw: bytes

    def __post_init__(self):
        object.__setattr__(self, "raw", bytes(self.raw))
        if len(self.raw) != GLOBAL_SIZE:
            raise RecordLengthError("the global block", len(self.raw), GLOBAL_SIZE)

    @classmethod
    def from_raw(cls, raw: bytes) -> "GlobalSettings":
        return cls(bytes(raw))

    def to_raw(self) -> bytes:
        return self.raw

    unknown = property(lambda self: self.raw[0:20])
    device_mode = property(lambda self: DeviceMode(self.raw[20]) if self.raw[20] in (0, 1) else self.raw[20])
    standalone_sync = property(lambda self: StandaloneSync(self.raw[21]) if self.raw[21] in (0, 1, 2)
                               else self.raw[21])
    sync_out = property(lambda self: self.raw[22])
    led_percent = property(lambda self: LED_LEVELS[self.raw[55]] if self.raw[55] < 4 else None)

    def cv_source(self, n: int) -> int:
        return self.raw[22 + n]

    def cv_channel(self, n: int) -> int:
        return self.raw[30 + n]

    def drum_note(self, n: int) -> int:
        return self.raw[38 + n]

    def value(self, key: str) -> int:
        return self.raw[FIELDS[key].offset]

    def with_change(self, change: "GlobalChange") -> "GlobalSettings":
        """Only the changed fields' bytes differ (A63, inv3). Hazard checks are GlobalChange.check's job."""
        raw = bytearray(self.raw)
        for key, value in change.values:
            raw[FIELDS[key].offset] = value
        return GlobalSettings(bytes(raw))

    def changed_by(self, change: "GlobalChange") -> "GlobalChange":
        """The part of `change` that differs from these settings (d94: the rest is 'unchanged')."""
        return GlobalChange(tuple((k, v) for k, v in change.values if self.value(k) != v))

    def fields(self) -> list[dict]:
        """Every named field in panel order with its label and shown value (A62: 'LED level' '75%')."""
        return [spec.describe_json(self.value(key)) for key, spec in FIELDS.items()]

    def describe(self, key: str) -> str:
        spec = FIELDS[key]
        return f"{spec.label} {spec.text(self.value(key))}"


# --- the named fields and a change -----------------------------------------------------------------------
class Hazard(IntEnum):
    DEVICE_MODE = 1
    SYNC = 2


HAZARD_TEXT = {
    "device_mode": "device mode change needs confirmation: it changes how the unit starts",
    "standalone_sync": "standalone sync change needs confirmation: it changes where the unit takes its clock",
    "sync_out": "sync out change needs confirmation: it changes which ports send clock",
}
CONFIRM_FIX = "repeat the command with confirm"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    offset: int
    parse: Any            # (text or number) → raw byte, or DomainInvariantError
    text: Any             # raw byte → shown text
    hazard: Hazard | None = None
    options: tuple = ()   # (value to send, shown text) for a choice field (the panel's select)
    bounds: tuple | None = None   # (lowest, highest) for a numbered field

    def describe_json(self, raw: int) -> dict:
        found = {"field": self.key, "label": self.label, "value": raw, "text": self.text(raw),
                 "hazard": self.hazard is not None}
        if self.options:
            found["options"] = [list(option) for option in self.options]
        if self.bounds is not None:
            found["min"], found["max"] = self.bounds
        return found


def _refuse(key: str, label: str, value, fix: str):
    raise DomainInvariantError(key, f"{label} {value}", fix, joiner=": ")


def _number(value) -> int | None:
    text = str(value).strip().rstrip("%")
    return int(text) if not isinstance(value, bool) and text.lstrip("-").isdigit() else None


def _ranged(key, label, low, high, fix):
    def parse(value):
        number = _number(value)
        if number is None or not low <= number <= high:
            _refuse(key, label, value, fix)
        return number
    return parse


def _choice(key, label, table: dict[str, int], fix):
    def parse(value):
        number = _number(value)
        if number is not None and number in table.values():
            return number
        word = " ".join(str(value).lower().replace("-", " ").replace("_", " ").split())
        if word in table:
            return table[word]
        _refuse(key, label, value, fix)
    return parse


def _led(value):
    number = _number(value)
    if number in LED_LEVELS:
        return LED_LEVELS.index(number)
    _refuse("led_level", "LED level", f"{value}%" if number is not None else value, "levels are 25, 50, 75 or 100%")


def _build_fields() -> dict[str, FieldSpec]:
    fields = {
        "device_mode": FieldSpec("device_mode", "Device mode", 20, _choice(
            "device_mode", "device mode", {"ableton live": 0, "ableton": 0, "live": 0, "standalone": 1},
            "device modes are 'Ableton Live' or 'Standalone'"), lambda v: DEVICE_MODE_TEXT.get(v, str(v)),
            Hazard.DEVICE_MODE, ((0, "Ableton Live"), (1, "Standalone"))),
        "standalone_sync": FieldSpec("standalone_sync", "Standalone sync", 21, _choice(
            "standalone_sync", "standalone sync", {"internal": 0, "int": 0, "usb": 1, "din": 2, "midi": 2,
                                                   "midi din": 2},
            "standalone sync is internal, usb or din"), lambda v: SYNC_TEXT.get(v, str(v)), Hazard.SYNC,
            ((0, "Internal"), (1, "USB"), (2, "MIDI DIN"))),
        "sync_out": FieldSpec("sync_out", "Sync out", 22, _choice(
            "sync_out", "sync out", {"off": 0, "none": 0, "usb": 1, "midi": 2, "usb midi": 3, "usb+midi": 3,
                                     "both": 3}, "sync out is off, usb, midi or usb+midi"), sync_out_text,
            Hazard.SYNC, ((0, "off"), (1, "USB"), (2, "MIDI"), (3, "USB + MIDI"))),
    }
    for n in range(1, CV_COUNT + 1):
        fields[f"cv{n}_source"] = FieldSpec(f"cv{n}_source", f"CV{n} source", 22 + n, _ranged(
            f"cv{n}_source", f"CV{n} source", 0, CV_SOURCE_MAX, f"sources are 0–{CV_SOURCE_MAX} (manual §5.6 order)"),
            cv_source_text, bounds=(0, CV_SOURCE_MAX))
    for n in range(1, CV_COUNT + 1):
        fields[f"cv{n}_channel"] = FieldSpec(f"cv{n}_channel", f"CV{n} channel", 30 + n, _ranged(
            f"cv{n}_channel", f"CV{n} channel", 1, 16, "channels are 1–16"), str, bounds=(1, 16))
    for n in range(1, DRUM_COUNT + 1):
        fields[f"drum{n}_note"] = FieldSpec(f"drum{n}_note", f"Drum {n} note", 38 + n, _ranged(
            f"drum{n}_note", f"Drum {n} note", 0, 127, "notes are 0–127"), str, bounds=(0, 127))
    fields["led_level"] = FieldSpec("led_level", "LED level", 55, _led,
                                    lambda v: f"{LED_LEVELS[v]}%" if v < 4 else f"level {v}",
                                    options=tuple((level, f"{level}%") for level in LED_LEVELS))
    return fields


FIELDS: dict[str, FieldSpec] = _build_fields()


class Confirmation:
    """An explicit yes to a hazardous change (inv8). Its absence means refusal; there is no default instance."""

    def __repr__(self) -> str:
        return "Confirmation()"


@dataclass(frozen=True)
class GlobalChange:
    """Validated field → raw byte pairs, in the order given (d92: several fields, one write)."""
    values: tuple[tuple[str, int], ...] = field(default_factory=tuple)

    @classmethod
    def parse(cls, changes: Mapping[str, Any]) -> "GlobalChange":
        """From {field: value}; refuses an unknown field or an out-of-range value naming it (d93)."""
        values = []
        for key, value in changes.items():
            name = str(key).strip().lower()
            spec = FIELDS.get(name)
            if spec is None:
                raise DomainInvariantError(str(key), f"no setting '{key}'",
                                           "settings are device_mode, standalone_sync, sync_out, cv1_source–"
                                           "cv8_source, cv1_channel–cv8_channel, drum1_note–drum16_note, led_level")
            values.append((name, spec.parse(value)))
        return cls(tuple(values))

    def __bool__(self) -> bool:
        return bool(self.values)

    @property
    def fields(self) -> tuple[str, ...]:
        return tuple(k for k, _ in self.values)

    def hazards(self) -> tuple[str, ...]:
        """The hazardous fields this change touches (device mode, sync)."""
        return tuple(k for k, _ in self.values if FIELDS[k].hazard is not None)

    def check(self, confirmation: Confirmation | None) -> None:
        """Refuses a hazardous change without an explicit Confirmation (A64, d91)."""
        if confirmation is not None and not isinstance(confirmation, Confirmation):
            raise TypeError("confirmation must be a Confirmation")
        hazards = self.hazards()
        if hazards and confirmation is None:
            problem, _, reason = HAZARD_TEXT[hazards[0]].partition(": ")
            raise DomainInvariantError(hazards[0], problem, f"{reason}; {CONFIRM_FIX}", joiner=": ")

    def labels(self) -> str:
        """'LED level' or 'LED level and CV2 channel' (d94's 'unchanged' message)."""
        labels = [FIELDS[k].label for k in self.fields]
        return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


def refusal_text(error: DomainInvariantError) -> str:
    """The one-line message of a memory or settings refusal: problem, joiner, fix ('slot 25: slots are 1–24')."""
    return f"{error.problem}{error.joiner}{error.fix}"
