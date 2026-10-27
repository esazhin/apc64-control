"""The circle of fifths (d60): the 12 pitch classes ordered by perfect fifths, C at the top."""


def fifths_index(pc: int) -> int:
    """C 0, G 1, D 2, … F 11."""
    return (pc * 7) % 12


def circle_order(pcs) -> list[int]:
    """The held pitch classes in circle order, the order they are joined in (C-G-E for a C major triad)."""
    return sorted(set(p % 12 for p in pcs), key=fifths_index)
