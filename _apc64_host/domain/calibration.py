"""Calibration of Note-view pad positions: an assumption, never a fact (contract inv9, d147–d149).

The unit's Note/Chord settings cannot be read (PROTOCOL-SPEC §8.3). A calibration records the notes
played by the bottom-left and top-right pads and assumes an isomorphic grid: one semitone per column
and (top_right - bottom_left - 7) / 7 semitones per row. Every position it gives is labelled assumed.
"""
from dataclasses import dataclass, field
from datetime import datetime

from .controls import PadPos
from .issues import DomainInvariantError
from .midi import Note


@dataclass(frozen=True)
class PadPosition:
    pad: PadPos
    assumed: bool = True


@dataclass(frozen=True)
class Calibration:
    at: datetime
    bottom_left: Note
    top_right: Note
    pads: dict[int, PadPos] = field(init=False, compare=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "bottom_left", Note(self.bottom_left))
        object.__setattr__(self, "top_right", Note(self.top_right))
        if self.top_right <= self.bottom_left:
            raise DomainInvariantError("calibration", "the top-right pad played a note no higher than the bottom-left",
                                       "press the bottom-left pad first, then the top-right pad")
        object.__setattr__(self, "pads", self._map())

    @property
    def row_step(self) -> int | None:
        span = self.top_right - self.bottom_left - 7
        return span // 7 if span > 0 and span % 7 == 0 else None

    def _map(self) -> dict[int, PadPos]:
        step = self.row_step
        if step is None:   # not isomorphic as assumed: only the two corners are known
            return {int(self.bottom_left): PadPos(1, 1), int(self.top_right): PadPos(8, 8)}
        mapping: dict[int, PadPos] = {}
        for row in range(1, 9):
            for col in range(1, 9):
                note = self.bottom_left + (row - 1) * step + (col - 1)
                if note <= 127:
                    mapping.setdefault(note, PadPos(row, col))   # lowest pad wins where notes repeat
        return mapping

    def position_of(self, note: int) -> PadPosition | None:
        pad = self.pads.get(int(note))
        return PadPosition(pad) if pad else None

    @property
    def label(self) -> str:
        return f"calibrated {self.at:%H:%M} (assumed)"


UNKNOWN_POSITION = "pad position unknown"
