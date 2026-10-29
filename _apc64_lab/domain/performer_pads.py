"""The performer's control pads on a guitar layout (contract 2 §2.10, Phase 2): chord types and pattern slots.

The guitar puts 6 strings or fewer on rows 2–7, so rows 1 and 8 (the bottom and the top row) are free: with a
performer block, the top row holds the chord types (column c the block's chords[c]) and the bottom row the pattern
slots (column c the block's slots[c]; an empty slot is silent and unlit). 7 strings use rows 1–7: the top row holds
the slots, and the chord types are Shift + a pad in their column. 8 strings fill every row: Shift + a pad in column
c chooses chord type c, Shift + a pad on the top row pattern slot c (the performer service takes those notes).

The control pads send on the reserved channel 16 (CONTROL_CHANNEL), the type pads notes 0–7 and the slot pads 8–15
by column, with outputs on and no aftertouch, so the unit sends them in Custom view; the host gives them to the lab
(take_played) and never forwards them to a target. A layout whose playing pads use channel 16 would clash: it is
refused (lab_section). Colours: the types amber, the slots blue, the one selected bright; pressed white.
"""
from .pads import WHITE, PadAssignment, PadGrid, Rgb

CONTROL_CHANNEL = 16
TYPE_NOTES, SLOT_NOTES = range(0, 8), range(8, 16)
TYPES, SLOTS = "types", "slots"
TOP, BOTTOM = 7, 0                                  # rows, 0-based from the bottom
TYPE_REST, TYPE_ON = Rgb(110, 60, 0), Rgb(255, 170, 0)
SLOT_REST, SLOT_ON = Rgb(0, 50, 130), Rgb(90, 170, 255)


def control_rows(strings: int) -> dict[str, int]:
    """{'types': row, 'slots': row} of the control rows a guitar of that many strings leaves free."""
    if strings <= 6:
        return {TYPES: TOP, SLOTS: BOTTOM}
    if strings == 7:
        return {SLOTS: TOP}
    return {}


def control_pads(strings: int, chords, slots, chord: str | None = None, slot: int | None = None
                 ) -> dict[int, PadAssignment]:
    """{pad index (r1c1 = 0): its PadAssignment} of the control rows: one pad per chord type and per filled slot."""
    rows = control_rows(strings)
    pads: dict[int, PadAssignment] = {}
    if TYPES in rows:
        for column, name in enumerate(tuple(chords)[:8]):
            pads[rows[TYPES] * 8 + column] = PadAssignment(TYPE_NOTES[column], TYPE_ON if name == chord else TYPE_REST,
                                                           WHITE, False, CONTROL_CHANNEL)
    if SLOTS in rows:
        for column, name in enumerate(tuple(slots)[:8]):
            if name:
                pads[rows[SLOTS] * 8 + column] = PadAssignment(SLOT_NOTES[column], SLOT_ON if column == slot else SLOT_REST,
                                                               WHITE, False, CONTROL_CHANNEL)
    return pads


def control_of(note: int) -> tuple[str, int] | None:
    """('types' | 'slots', column 0–7) for a control pad's note on CONTROL_CHANNEL, else None."""
    if note in TYPE_NOTES:
        return TYPES, note - TYPE_NOTES.start
    if note in SLOT_NOTES:
        return SLOTS, note - SLOT_NOTES.start
    return None


def with_controls(grid, pads: dict[int, PadAssignment]):
    """The grid with the control pads in place of its (silent) pads there."""
    if not pads:
        return grid
    return PadGrid(tuple(pads.get(index, pad) for index, pad in enumerate(grid.pads)))
