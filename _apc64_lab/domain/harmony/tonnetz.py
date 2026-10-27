"""Tonnetz geometry (p13): pitch classes on a triangular lattice whose axes are the perfect fifth, the major
third and the minor third. Its triangles are the major and minor triads; triads sharing an edge are the
neo-Riemannian neighbours P (parallel), R (relative) and L (leading-tone) (d61).
"""
from dataclasses import dataclass

from .spelling import pc_name

MAJOR, MINOR = "major", "minor"


def pc_at(i: int, j: int) -> int:
    """The lattice node i fifths and j major thirds from C (the prototype's layout)."""
    return (7 * i + 4 * j) % 12


@dataclass(frozen=True, order=True)
class Triad:
    root: int
    quality: str

    def __post_init__(self):
        if self.quality not in (MAJOR, MINOR):
            raise ValueError(f"a Tonnetz triad is major or minor, not {self.quality}")
        object.__setattr__(self, "root", self.root % 12)

    @property
    def pitch_classes(self) -> frozenset[int]:
        third = 4 if self.quality == MAJOR else 3
        return frozenset({self.root, (self.root + third) % 12, (self.root + 7) % 12})

    @property
    def label(self) -> str:
        return pc_name(self.root) + ("m" if self.quality == MINOR else "")

    def parallel(self) -> "Triad":
        return Triad(self.root, MINOR if self.quality == MAJOR else MAJOR)

    def relative(self) -> "Triad":
        return Triad(self.root + 9, MINOR) if self.quality == MAJOR else Triad(self.root + 3, MAJOR)

    def leading_tone(self) -> "Triad":
        return Triad(self.root + 4, MINOR) if self.quality == MAJOR else Triad(self.root + 8, MAJOR)

    def neighbours(self) -> tuple["Triad", "Triad", "Triad"]:
        """P, R, L: the three triads sharing an edge (two notes) with this one (C → Cm, Am, Em)."""
        return self.parallel(), self.relative(), self.leading_tone()


ALL_TRIADS = tuple(Triad(root, quality) for quality in (MAJOR, MINOR) for root in range(12))


def triads_containing(pc: int) -> tuple[Triad, ...]:
    """The six triangles around a lattice node, in order around it (d52): starting from the major triad the
    note is the third of (E: C, Em, E, C♯m, A, Am)."""
    pc %= 12
    return (Triad(pc - 4, MAJOR), Triad(pc, MINOR), Triad(pc, MAJOR), Triad(pc - 3, MINOR), Triad(pc - 7, MAJOR),
            Triad(pc - 7, MINOR))


def complete_triads(pcs) -> tuple[Triad, ...]:
    """The triads whose three pitch classes are all held (d53, inv16), majors first, by root."""
    held = set(p % 12 for p in pcs)
    return tuple(t for t in ALL_TRIADS if t.pitch_classes <= held)
