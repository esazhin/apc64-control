"""Voicings (docs/performer-format.md, "Voicings"): a root on its string and a chord type → one note per string."""
import pytest

from performer.chords import CHORD_TYPES, DEFAULT_TYPES
from performer.voicing import VoicingError, build_voicing

E_STANDARD = {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}
DROP_D = {6: 38, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}
SEVEN = {7: 35, **E_STANDARD}                                  # B standard 7-string
EIGHT = {8: 30, **SEVEN}                                       # F♯ standard 8-string
# (root note, string, type) → the shape, low string first: the usual chords in E standard
USUAL = {
    (40, 6, "maj"): "022100", (45, 5, "min"): "x02210", (48, 5, "maj"): "x32010", (50, 4, "maj"): "xx0232",
    (43, 6, "maj"): "320003", (45, 5, "maj"): "x02220", (40, 6, "min"): "022000", (50, 4, "min"): "xx0231",
    (41, 6, "maj"): "133211", (40, 6, "7"): "020100", (45, 5, "7"): "x02020", (50, 4, "7"): "xx0212",
    (43, 6, "7"): "320001", (48, 5, "7"): "x32310", (47, 5, "7"): "x21202", (48, 5, "maj7"): "x32000",
    (45, 5, "maj7"): "x02120", (50, 4, "maj7"): "xx0222", (45, 5, "m7"): "x02010", (40, 6, "m7"): "020000",
    (50, 4, "m7"): "xx0211", (45, 5, "sus2"): "x02200", (45, 5, "sus4"): "x02230", (50, 4, "sus2"): "xx0230",
    (50, 4, "sus4"): "xx0233", (40, 6, "sus4"): "022200",
    # barre shapes up the neck: root on 6 an E shape, on 5 an A shape, on 4 a D shape
    (45, 6, "maj"): "577655", (47, 5, "min"): "x24432", (42, 6, "min"): "244222", (48, 5, "min"): "x35543",
    (46, 5, "maj"): "x13331", (44, 6, "maj"): "466544", (55, 4, "maj"): "xx5787",
}


@pytest.mark.parametrize("key", USUAL)
def test_the_usual_chords_in_e_standard(key):
    root, string, kind = key
    assert build_voicing(E_STANDARD, root, string, kind).shape() == USUAL[key]


def test_a_voicing_has_its_root_in_the_bass_every_chord_tone_and_a_playable_span():
    for kind in CHORD_TYPES:
        for string in (6, 5, 4):
            for fret in range(0, 13):
                root = E_STANDARD[string] + fret
                v = build_voicing(E_STANDARD, root, string, kind)
                sounding = v.sounding
                assert v.note(string) == root and min(sounding.values()) == root
                assert all(s < string for s in sounding if s != string) and set(range(string + 1, 7)) <= v.muted
                fretted = [f for _, f in v.frets if f]
                assert not fretted or max(fretted) - min(fretted) <= 3, (kind, string, fret, v.shape())
                tones = {(root + i) % 12 for i in CHORD_TYPES[kind].intervals}
                assert {n % 12 for n in sounding.values()} <= tones


def test_the_voicing_lists_its_notes_and_muted_strings():
    v = build_voicing(E_STANDARD, 48, 5, "maj")
    assert v.sounding == {5: 48, 4: 52, 3: 55, 2: 60, 1: 64} and v.muted == {6}
    assert (v.root, v.root_string, v.chord) == (48, 5, "maj")


def test_short_strings_take_what_fits_the_root_first():
    assert build_voicing(E_STANDARD, 55, 3, "maj").shape() == "xxx003"
    assert build_voicing(E_STANDARD, 64, 1, "m7").shape() == "xxxxx0"
    assert build_voicing(E_STANDARD, 59, 2, "7").sounding == {2: 59, 1: 66}        # the root, then the third


def test_drop_d_and_seven_and_eight_strings_give_sensible_shapes():
    assert build_voicing(DROP_D, 38, 6, "maj").shape() == "000232"
    assert build_voicing(DROP_D, 38, 6, "min").shape() == "000231"
    assert build_voicing(DROP_D, 40, 6, "maj").shape() == "222100"
    for opens in (SEVEN, EIGHT):
        low = max(opens)
        for kind in DEFAULT_TYPES:
            for fret in range(0, 8, 2):
                v = build_voicing(opens, opens[low] + fret, low, kind)
                assert min(v.sounding.values()) == opens[low] + fret and len(v.sounding) >= 3


def test_a_root_off_the_string_is_refused():
    with pytest.raises(VoicingError):
        build_voicing(E_STANDARD, 39, 6, "maj")                 # below the open E
    with pytest.raises(VoicingError):
        build_voicing(E_STANDARD, 50, 9, "maj")
    with pytest.raises(ValueError):
        build_voicing(E_STANDARD, 40, 6, "polka")
