"""HeldNotes: the notes sounding now, as a multiset (d46: two pads on one note hold it until the last lets go)."""
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class HeldNotes:
    _counts: Counter = field(default_factory=Counter)

    def on(self, note: int) -> None:
        self._counts[note] += 1

    def off(self, note: int) -> None:
        if self._counts[note] > 1:
            self._counts[note] -= 1
        else:
            self._counts.pop(note, None)

    def end(self, notes) -> None:
        """Every hold of these notes ends at once (a window shift or layout switch, d47)."""
        for note in notes:
            self._counts.pop(note, None)

    def clear(self) -> None:
        self._counts.clear()

    @property
    def notes(self) -> list[int]:
        """Distinct held notes, lowest first."""
        return sorted(self._counts)

    @property
    def pitch_classes(self) -> set[int]:
        return {n % 12 for n in self._counts}

    def count(self, note: int) -> int:
        return self._counts.get(note, 0)

    def __bool__(self) -> bool:
        return bool(self._counts)
