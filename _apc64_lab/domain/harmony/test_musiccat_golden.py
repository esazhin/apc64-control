"""MusicCat Explorer's own cases (the author's music-theory app), ported as golden tests so the two agree
(contract §2.7 a25).

Source: its chord-logic tests (the 14 chord-detection cases) and its theory tables (diatonic spelling).
"""
import pytest

from _apc64_lab.domain.harmony.chords import find_chord_matches
from _apc64_lab.domain.harmony.spelling import (
    NOTE_DISPLAY, PARENT_KEY_INDICES, PARENT_KEYS, diatonic_chords, diatonic_scale, pc_name,
)

# chord_logic.test.js TEST_CASES, verbatim
CHORD_CASES = [
    ("C Major Triad (Root Position)", [60, 64, 67], "C"),
    ("C Major Triad (1st Inversion)", [64, 67, 72], "C/E"),
    ("C Major Triad (2nd Inversion)", [67, 72, 76], "C/G"),
    ("G Major Triad (Open Voicing)", [55, 62, 71], "G"),
    ("A Minor Triad (Root Position)", [57, 60, 64], "Am"),
    ("A Minor Triad (1st Inversion)", [60, 64, 69], "Am/C"),
    ("G Dominant 7th", [55, 59, 62, 65], "G7"),
    ("C Major 7th", [60, 64, 67, 71], "Cmaj7"),
    ("D Minor 7th", [62, 65, 69, 72], "Dm7"),
    ("B Diminished 7th", [59, 62, 65, 68], "Bdim7"),
    ("B Half-Diminished 7th", [71, 74, 77, 81], "Bm7♭5"),
    ("D sus 4", [62, 67, 69], "Dsus4"),
    ("G sus 2", [55, 57, 62], "Gsus2"),
    ("C Major with added D", [60, 62, 64, 67], "C"),
]


@pytest.mark.parametrize("name,notes,expected", CHORD_CASES, ids=[c[0] for c in CHORD_CASES])
def test_musiccat_chord_detection(name, notes, expected):
    matches = find_chord_matches(notes)
    assert matches and matches[0].symbol == expected


def test_the_fixed_spelling_table_without_key_context():
    assert NOTE_DISPLAY == ("C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B")
    assert [pc_name(pc) for pc in (1, 3, 6, 8, 10)] == ["C♯", "E♭", "F♯", "A♭", "B♭"]


def test_parent_keys():
    assert [PARENT_KEYS[pc] for pc in range(12)] == ["C", "D♭", "D", "E♭", "E", "F", "G♭", "G", "A♭", "A", "B♭",
                                                       "B"]
    assert PARENT_KEY_INDICES == (0, 7, 2, 9, 4, 11, 5, 10, 3, 8, 1, 6)


@pytest.mark.parametrize("root,expected", [
    (2, "D E F♯ G A B C♯"),                 # the example agreed for the lab
    (0, "C D E F G A B"),
    (6, "G♭ A♭ B♭ C♭ D♭ E♭ F"),             # each letter once: C♭, not B
    (1, "D♭ E♭ F G♭ A♭ B♭ C"),
    (11, "B C♯ D♯ E F♯ G♯ A♯"),
])
def test_scales_are_spelled_letter_correctly_from_the_parent_keys(root, expected):
    assert " ".join(diatonic_scale(root, PARENT_KEYS[root])) == expected


def test_double_accidentals_appear_where_the_letter_demands_them():
    # G♯ melodic-minor-style pattern forces F𝄪-like spellings: theory.js writes them as ♯♯
    assert diatonic_scale(8, "G♯", (2, 2, 1, 2, 2, 2))[-1] == "F♯♯"


def test_diatonic_chords_use_musiccats_quality_symbols():
    chords = diatonic_chords(diatonic_scale(0, "C"))
    assert [c["symbol"] for c in chords] == ["C", "Dm", "Em", "F", "G", "Am", "B°"]
    assert [c["roman"] for c in chords] == ["I", "ii", "iii", "IV", "V", "vi", "vii°"]
    d_major = diatonic_chords(diatonic_scale(2, "D"))
    assert [c["symbol"] for c in d_major] == ["D", "Em", "F♯m", "G", "A", "Bm", "C♯°"]
    assert diatonic_chords(["C", "D", "E"]) == []
