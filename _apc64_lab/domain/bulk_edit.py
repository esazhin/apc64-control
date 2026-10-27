"""Bulk edits of a stored project or library entry (contract §2.7 q1: in v1, agent-facing).

A BulkEdit names a selection of pads or strips, one field and one value. It is validated when it is made and
applied to a captured record, giving a new record that is then written through the guarded write path like
any push. Only the named field's bytes change; every other byte, unknown bytes included, is kept (inv3).

Written forms (CLI and API): '<selection> <field> <value>', e.g.
  'all pads channel 3'          'pads r1c1-r2c8 colour red'      'pad r3c4 pressed #00FF00'
  'all pads transpose -12'      'strips 1-8 channel 2'           'strip 3 bipolar on'
"""
from dataclasses import dataclass
from typing import Any

from _apc64_host.domain.controls import PadPos, Strip, format_controls, parse_controls
from _apc64_host.domain.issues import DomainInvariantError

from .pads import Rgb
from .records import ProjectRecord

NAMED_COLOURS = {
    "off": Rgb(0, 0, 0), "black": Rgb(0, 0, 0), "white": Rgb(255, 255, 255), "red": Rgb(255, 0, 0),
    "orange": Rgb(255, 128, 0), "yellow": Rgb(255, 255, 0), "green": Rgb(0, 255, 0), "cyan": Rgb(0, 255, 255),
    "blue": Rgb(0, 0, 255), "purple": Rgb(128, 0, 255), "magenta": Rgb(255, 0, 255), "pink": Rgb(255, 64, 160),
}
PAD_FIELDS = ("channel", "colour", "pressed", "aftertouch", "outputs", "transpose")
STRIP_FIELDS = ("channel", "bar", "indicator", "bipolar", "outputs")
_ALIASES = {"color": "colour", "rest": "colour", "ch": "channel", "at": "aftertouch", "tip": "indicator"}
_FIX = ("write '<pads or strips> <field> <value>', e.g. 'all pads channel 3' or 'pads r1c1-r2c8 colour red'")


def _colour(field: str, value: Any) -> Rgb:
    if isinstance(value, str) and value.strip().lower() in NAMED_COLOURS:
        return NAMED_COLOURS[value.strip().lower()]
    try:
        return Rgb.of(value)
    except DomainInvariantError as error:
        raise DomainInvariantError(field, f"{field} {value}: {error.problem}",
                                   f"{error.fix}, or a name ({', '.join(NAMED_COLOURS)})") from None


def _switch(field: str, value: Any) -> bool:
    word = str(value).strip().lower()
    if word in ("on", "yes", "true", "1"):
        return True
    if word in ("off", "no", "false", "0"):
        return False
    raise DomainInvariantError(field, f"{field} {value}", "write on or off", joiner=": ")


def _int(field: str, value: Any, low: int, high: int, fix: str) -> int:
    text = str(value).strip()
    if isinstance(value, bool) or not text.lstrip("+-").isdigit() or not low <= int(text) <= high:
        raise DomainInvariantError(field, f"{field} {value}", fix, joiner=": ")
    return int(text)


def _outputs(value: Any) -> int:
    word = str(value).strip().lower()
    if word in ("all", "on"):
        return 7
    if word in ("none", "off"):
        return 0
    return _int("outputs", value, 0, 7, "outputs are all, none or a 0–7 bitmask")


@dataclass(frozen=True)
class BulkEdit:
    """One validated edit: a selection (pads or strips), a field and its parsed value."""
    targets: tuple
    field: str
    value: Any
    text: str = ""

    @classmethod
    def make(cls, selection: str, field: str, value: Any) -> "BulkEdit":
        targets = _selection(selection)
        field = _ALIASES.get(str(field).strip().lower(), str(field).strip().lower())
        pads = isinstance(targets[0], PadPos)
        allowed = PAD_FIELDS if pads else STRIP_FIELDS
        if field not in allowed:
            raise DomainInvariantError(field, f"{'pads' if pads else 'strips'} have no field '{field}'",
                                       "fields are " + ", ".join(allowed))
        if field == "channel":
            parsed = _int("channel", value, 1, 16, "channels are 1–16")
        elif field in ("colour", "pressed", "bar", "indicator"):
            parsed = _colour(field, value)
        elif field in ("aftertouch", "bipolar"):
            parsed = _switch(field, value)
        elif field == "outputs":
            parsed = _outputs(value)
        else:   # transpose
            parsed = _int("transpose", value, -127, 127, "transpose by −127 to 127 semitones")
        return cls(targets, field, parsed, f"{format_controls(targets)} {field} {value}")

    @classmethod
    def parse(cls, text: str) -> "BulkEdit":
        """'all pads channel 3', 'pads r1c1-r2c8 colour red' (value last, field before it)."""
        words = str(text).split()
        if len(words) < 3:
            raise DomainInvariantError("edit", f"'{text}' is not an edit", _FIX)
        return cls.make(" ".join(words[:-2]), words[-2], words[-1])

    def apply(self, record: ProjectRecord) -> ProjectRecord:
        """The record with this edit; a transpose that leaves 0–127 is refused naming the pad."""
        if isinstance(self.targets[0], PadPos):
            changes = {}
            if self.field == "transpose":
                moved = [(pad, record.pad(pad).note + self.value) for pad in self.targets if not record.pad(pad).silent]
                outside = [(pad, note) for pad, note in moved if not 0 <= note <= 127]
                if outside:   # name the worst pad, as the generators do
                    pad, note = max(outside, key=lambda item: (abs(item[1] - 63.5), -item[0].index))
                    raise DomainInvariantError("transpose", f"transpose {self.value:+d} puts {pad} at note {note}",
                                               "notes are 0–127; transpose less", joiner=": ")
            for pad in self.targets:
                current = record.pad(pad)
                if self.field == "transpose":
                    if not current.silent:
                        changes[pad.index] = current.with_fields(note=current.note + self.value)
                else:
                    name = "rest" if self.field == "colour" else self.field
                    changes[pad.index] = current.with_fields(**{name: self.value})
            return record.with_pad_records(changes)
        return record.with_strip_records({s.n: record.strip(s).with_fields(**{self.field: self.value})
                                          for s in self.targets})


def _selection(text: str) -> tuple:
    words = " ".join(str(text).lower().split())
    if words in ("all pads", "pads all", "all", "pads"):
        return tuple(PadPos.from_index(i) for i in range(64))
    if words in ("all strips", "strips all", "strips"):
        return tuple(Strip(n) for n in range(1, 9))
    try:
        controls = parse_controls(words)
    except DomainInvariantError as error:
        raise DomainInvariantError("selection", error.problem,
                                   "select 'all pads', 'pads r1c1-r2c8', 'pad r3c4', 'all strips' or 'strips 1-8'")
    if all(isinstance(c, PadPos) for c in controls) or all(isinstance(c, Strip) for c in controls):
        return controls
    raise DomainInvariantError("selection", f"'{text}' is not pads or strips",
                               "select 'all pads', 'pads r1c1-r2c8', 'pad r3c4', 'all strips' or 'strips 1-8'")


def apply_all(record: ProjectRecord, edits) -> ProjectRecord:
    """Several edits in order, as one command (one backup, one write)."""
    for edit in edits:
        record = edit.apply(record)
    return record
