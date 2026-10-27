"""The circle of fifths (d60): the 12 pitch classes ordered by perfect fifths, C at the top; and its keys, the
major keys outside and their relative minors inside (C/Am, G/Em … F/Dm).

Key names follow MusicCat's parent keys (PARENT_KEYS: D♭, E♭, G♭, A♭, B♭), with F♯ beside G♭ at the bottom.
A relative minor is the sixth degree of its major key, spelled letter-correctly in that key (B major's is G♯,
G♭ major's E♭), and named as the chord names minor triads: 'G♯m'.
"""
from dataclasses import dataclass

from .spelling import PARENT_KEYS, diatonic_scale


def fifths_index(pc: int) -> int:
    """C 0, G 1, D 2, … F 11."""
    return (pc * 7) % 12


def circle_order(pcs) -> list[int]:
    """The held pitch classes in circle order, the order they are joined in (C-G-E for a C major triad)."""
    return sorted(set(p % 12 for p in pcs), key=fifths_index)


@dataclass(frozen=True)
class CircleKey:
    """One position of the circle: its major key and the relative minor, each with every spelling shown."""
    pc: int                       # the major key's pitch class
    major: tuple[str, ...]        # ('C',), or ('F♯', 'G♭') at the enharmonic bottom
    minor_pc: int
    minor: tuple[str, ...]        # ('Am',), or ('D♯m', 'E♭m')


# the enharmonic position at the bottom shows both spellings, the sharp one first
_BOTH = {6: ("F♯", "G♭")}


def circle_keys() -> tuple[CircleKey, ...]:
    """The 12 positions clockwise from C at the top."""
    keys = []
    for k in range(12):
        pc = (k * 7) % 12
        majors = _BOTH.get(pc, (PARENT_KEYS[pc],))
        minors = tuple(diatonic_scale(pc, name)[5] + "m" for name in majors)
        keys.append(CircleKey(pc, majors, (pc + 9) % 12, minors))
    return tuple(keys)
