"""Note spelling, consistent with the author's MusicCat Explorer (contract §2.7 a25).

Without key context (chord detection, single notes, lattice labels) a pitch class is spelled from the fixed
table NOTE_DISPLAY (C C♯ D E♭ E F F♯ G A♭ A B♭ B, Unicode ♯/♭). With key context (scales, diatonic chords)
notes are spelled letter-correctly, each letter once, double ♯/♭ allowed (D major = D E F♯ G A B C♯).
Key names are PARENT_KEYS. The tables are ported from theory.js unchanged.

Spelling from context (2026-10-27, after the guitar live test): a note can also be spelled as an interval above a
spelled reference, letter-correctly (E + a major third → G♯, not A♭): `spell_above`. The chord's and the key's
spelling of held notes is built on it (chords.spell_chord, state.spell_held).
"""
NOTE_DISPLAY = ("C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B")
NOTE_LETTERS = ("C", "D", "E", "F", "G", "A", "B")
# theory.js PITCH_CLASS_NAMES, in its key order (normal, then the alternatives as listed)
PITCH_CLASS_NAMES = {
    0: (("normal", "C"), ("sharp", "B♯"), ("flat", "D♭♭")),
    1: (("normal", "C♯"), ("flat", "D♭")),
    2: (("normal", "D"), ("sharp", "C♯♯"), ("flat", "E♭♭")),
    3: (("normal", "E♭"), ("sharp", "D♯")),
    4: (("normal", "E"), ("flat", "F♭"), ("sharp", "D♯♯")),
    5: (("normal", "F"), ("sharp", "E♯"), ("flat", "G♭♭")),
    6: (("normal", "F♯"), ("flat", "G♭")),
    7: (("normal", "G"), ("sharp", "F♯♯"), ("flat", "A♭♭")),
    8: (("normal", "A♭"), ("sharp", "G♯")),
    9: (("normal", "A"), ("sharp", "G♯♯"), ("flat", "B♭♭")),
    10: (("normal", "B♭"), ("sharp", "A♯")),
    11: (("normal", "B"), ("flat", "C♭"), ("sharp", "A♯♯")),
}
PARENT_KEY_INDICES = (0, 7, 2, 9, 4, 11, 5, 10, 3, 8, 1, 6)
PARENT_KEYS = {0: "C", 1: "D♭", 2: "D", 3: "E♭", 4: "E", 5: "F", 6: "G♭", 7: "G", 8: "A♭", 9: "A", 10: "B♭",
               11: "B"}
MAJOR_PATTERN = (2, 2, 1, 2, 2, 2)
ROMAN_NUMERALS = ("I", "II", "III", "IV", "V", "VI", "VII")
CHORD_QUALITY_SYMBOLS = {"Major": "", "Minor": "m", "Diminished": "°", "Augmented": "+"}
# Interval labels from a single held note (the prototype's degrees, with Unicode ♭ as the spelling above)
DEGREES = ("1", "♭2", "2", "♭3", "3", "4", "♭5", "5", "♭6", "6", "♭7", "7")
MIDDLE_C_OCTAVE = 3   # C3 = 60, as the host and the APC64 count octaves

_LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_ACCIDENTAL = {"♯": 1, "#": 1, "♭": -1, "b": -1, "𝄪": 2, "𝄫": -2}


# The letter steps of each DEGREES label (its number less one): '♭3' is two letters up, '♭5' four.
DEGREE_LETTERS = tuple(int(label.lstrip("♭♯")) - 1 for label in DEGREES)
_ACCIDENTAL_TEXT = {-2: "♭♭", -1: "♭", 0: "", 1: "♯", 2: "♯♯"}   # theory.js writes doubles as ♯♯ / ♭♭


def pc_name(pc: int) -> str:
    """theory.js pcName: the fixed spelling of a pitch class without key context."""
    return NOTE_DISPLAY[pc % 12]


def note_label(note: int) -> str:
    """A MIDI note as its fixed spelling and octave, C3 = 60: 'E3' for 64, 'C♯4' for 73."""
    return f"{pc_name(note)}{note // 12 - 5 + MIDDLE_C_OCTAVE}"


def note_label_spelled(note: int, name: str) -> str:
    """A MIDI note as a given spelling and its octave, counted from the letter (C3 = 60): 'C♭3' for 59 spelled
    C♭, 'B♯2' for 60 spelled B♯."""
    natural = note - sum(_ACCIDENTAL.get(ch, 0) for ch in name[1:])
    return f"{name}{natural // 12 - 5 + MIDDLE_C_OCTAVE}"


def spell_letter(pc: int, letter: str) -> str | None:
    """The pitch class written on this letter ('G' for 8 → 'G♯'), or None when it would need more than two
    accidentals."""
    diff = (pc - _LETTER_PC[letter] + 6) % 12 - 6   # -6 … 5
    return f"{letter}{_ACCIDENTAL_TEXT[diff]}" if diff in _ACCIDENTAL_TEXT else None


def spell_above(reference: str, pc: int, letters: int | None = None) -> str:
    """`pc` spelled as an interval above the spelled `reference`: `letters` letter steps up (by default the
    DEGREES label's: a major third is two letters, so E → G♯; a minor sixth five, E → C). Falls back to the fixed
    table when the letter would need more than two accidentals."""
    ref_pc = parse_pitch_class(reference)
    if ref_pc is None:
        return pc_name(pc)
    if letters is None:
        letters = DEGREE_LETTERS[(pc - ref_pc) % 12]
    letter = NOTE_LETTERS[(NOTE_LETTERS.index(reference[0].upper()) + letters) % 7]
    return spell_letter(pc % 12, letter) or pc_name(pc)


def accidentals(name: str) -> int:
    """How many ♯/♭ a spelling carries (a double counts two)."""
    return sum(name.count(ch) for ch in "♯♭")


RARE_NAMES = frozenset({"C♭", "F♭", "E♯", "B♯"})   # letter-correct, but a player would read the plain name


def is_rare(name: str) -> bool:
    """C♭, F♭, E♯, B♯ or any double sharp/flat: spellings a player would never read outside a key that needs them."""
    return name in RARE_NAMES or "♯♯" in name or "♭♭" in name


def readable(name: str, pc: int, key=None) -> str:
    """`name`, unless it is rare (is_rare) and the key (pitch class → name) does not itself spell it so: then the
    fixed table's name for that note only (F°'s C♭ reads B; in G♭ major its C♭ stays)."""
    if is_rare(name) and name not in set((key or {}).values()):
        return pc_name(pc)
    return name


def degree_of(pc: int, reference: int) -> str:
    """The interval label of `pc` above `reference`: '♭3' for G above E."""
    return DEGREES[(pc - reference) % 12]


def parse_pitch_class(text: str) -> int | None:
    """'C', 'C♯', 'C#', 'Db', 'D♭', 'B♯', 'Ebb' … → 0–11, or None when it is not a note name."""
    text = str(text).strip()
    if not text or text[0].upper() not in _LETTER_PC:
        return None
    pc = _LETTER_PC[text[0].upper()]
    for ch in text[1:]:
        if ch not in _ACCIDENTAL:
            return None
        pc += _ACCIDENTAL[ch]
    return pc % 12


def _spellings(pc: int) -> tuple[str, ...]:
    return tuple(name for _, name in PITCH_CLASS_NAMES[pc % 12])


def pc_of_name(name: str) -> int:
    """theory.js _getPCForNoteName: the pitch class of a spelled name, or -1."""
    for pc, names in PITCH_CLASS_NAMES.items():
        if name in (n for _, n in names):
            return pc
    return -1


def diatonic_scale(root_pc: int, root_name: str, pattern=MAJOR_PATTERN) -> list[str]:
    """theory.js _generateDiatonicScale: letter-correct spelling, each letter once ('?' when no spelling)."""
    notes, pitch = [root_name], root_pc
    root_letter = NOTE_LETTERS.index(root_name[0])
    for i, step in enumerate(pattern):
        pitch = (pitch + step) % 12
        letter = NOTE_LETTERS[(root_letter + i + 1) % 7]
        notes.append(next((n for n in _spellings(pitch) if n[0] == letter), "?"))
    return notes


def diatonic_chords(scale_notes) -> list[dict]:
    """theory.js getDiatonicChords: the triads of a 7-note scale with degree, roman numeral and symbol."""
    if len(scale_notes) < 7:
        return []
    size = len(scale_notes)
    pitches = [pc_of_name(n) for n in scale_notes]
    chords = []
    for i in range(size):
        root, third, fifth = pitches[i], pitches[(i + 2) % size], pitches[(i + 4) % size]
        third_iv, fifth_iv = (third - root) % 12, (fifth - root) % 12
        roman = ROMAN_NUMERALS[i]
        quality = ""
        if third_iv == 4 and fifth_iv == 7:
            quality = "Major"
        elif third_iv == 3 and fifth_iv == 7:
            quality, roman = "Minor", roman.lower()
        elif third_iv == 3 and fifth_iv == 6:
            quality, roman = "Diminished", roman.lower() + "°"
        elif third_iv == 4 and fifth_iv == 8:
            quality, roman = "Augmented", roman + "+"
        if quality:
            name = scale_notes[i]
            chords.append({"degree": i + 1, "roman": roman, "name": f"{name} {quality}",
                           "symbol": f"{name.split('/')[0]}{CHORD_QUALITY_SYMBOLS[quality]}",
                           "rootPitch": root, "quality": quality})
    return chords


def key_name(pc: int) -> str:
    return PARENT_KEYS[pc % 12]
