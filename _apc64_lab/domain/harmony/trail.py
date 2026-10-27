"""ChordTrail (d57): completed triads in the order played; the same chord again adds nothing; last 8 kept."""
from dataclasses import dataclass, field

from .tonnetz import Triad

TRAIL_LENGTH = 8


@dataclass
class ChordTrail:
    entries: list = field(default_factory=list)   # [(Triad, label)]
    length: int = TRAIL_LENGTH

    def add(self, triad: Triad, label: str | None = None) -> bool:
        """Adds a triad unless it is the newest entry already; returns whether it was added."""
        if self.entries and self.entries[-1][0] == triad:
            return False
        self.entries.append((triad, label or triad.label))
        del self.entries[:-self.length]
        return True

    @property
    def triads(self) -> list[Triad]:
        return [t for t, _ in self.entries]

    @property
    def labels(self) -> list[str]:
        return [label for _, label in self.entries]

    def clear(self) -> None:
        self.entries.clear()
