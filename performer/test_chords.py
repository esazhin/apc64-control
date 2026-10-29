"""Chord-aware lanes (docs/performer-format.md, "Chord-aware lanes"): the root of what is held, the strings below it
silent in play all, R and A following the chord, and the chord types."""
import pytest

from performer import Performer, parse_pattern
from performer.chords import CHORD_TYPES, DEFAULT_TYPES, chord_root, chord_type, diatonic_chord

STEP = 0.25                                   # one 1/8 step at 120 BPM
E_STANDARD = {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# the usual open chords in E standard, low string first (x: not pressed; 0: open, not pressed)
OPEN_CHORDS = {"E": ("022100", "E"), "Am": ("x02210", "A"), "C": ("x32010", "C"), "D": ("xx0232", "D"),
               "G": ("320003", "G"), "A": ("x02220", "A"), "Em": ("022000", "E"), "Dm": ("xx0231", "D"),
               "F": ("133211", "F")}


def strum(**overrides):
    data = {"name": "Strum", "length": 1, "lanes": {k: "x" for k in range(1, 7)}, **overrides}
    return parse_pattern(data)


def press_shape(player, shape, t=0.0):
    """The shape's fretted notes pressed (frets above 0); open and x strings are left alone."""
    for k, fret in enumerate(shape):
        string = 6 - k
        if fret not in "x0":
            player.press(string, E_STANDARD[string] + int(fret), 100, t)


def played(events):
    return sorted((e.lane, e.note) for e in events if e.kind == "on")


def sounding(events, now=None):
    """(lane, note) sounding after the events (a chord pressed finger by finger is caught up note by note)."""
    found = dict(now or {})
    for e in events:
        if e.kind == "on":
            found[e.lane] = e.note
        elif e.kind == "off" and found.get(e.lane) == e.note:
            del found[e.lane]
    return sorted(found.items())


def test_chord_root_recognises_the_usual_chords_and_prefers_root_position():
    assert chord_root([]) is None and chord_root([60]) is None and chord_root([60, 64]) is None
    assert chord_root([60, 64, 67]) == 0 and chord_root([57, 60, 64]) == 9            # C, Am
    assert chord_root([45, 57, 59, 64]) == 9                                          # A B E: Asus2 (A in the bass)
    assert chord_root([40, 45, 59, 64]) == 4                                          # E A B: Esus4 (E in the bass)
    assert chord_root([45, 55, 60, 64]) == 9                                          # Am7, not C6
    assert chord_type("min7") is CHORD_TYPES["m7"] and chord_type("Maj7").name == "maj7" and chord_type("x") is None
    assert DEFAULT_TYPES == ("maj", "min", "7", "maj7", "m7", "sus2", "sus4", "dim")


@pytest.mark.parametrize("name", OPEN_CHORDS)
def test_play_all_never_rings_a_wrong_bass_on_the_usual_open_chords(name):
    shape, root = OPEN_CHORDS[name]
    p = Performer(strum(), bpm=120, opens=E_STANDARD)
    press_shape(p, shape)
    notes = sounding(p.advance_to(0.0))
    assert NAMES[min(n for _, n in notes) % 12] == root, notes
    lowest = 6 - next(k for k, fret in enumerate(shape) if fret != "x")
    assert [lane for lane, _ in notes] == list(range(1, lowest + 1))                   # nothing below the root
    assert p.state(0.0).root == lowest


def test_a_pressed_string_below_the_root_still_plays_and_pressed_mode_is_unchanged():
    p = Performer(strum(), bpm=120, opens=E_STANDARD)
    for string, note in ((5, 48), (4, 52), (2, 60)):                # C (x32010), the root on string 5
        p.press(string, note, 100, 0.0)
    p.press(6, 43, 100, 0.0)                                       # and G on the low E: C/G, played on purpose
    assert (6, 43) in sounding(p.advance_to(0.0))
    q = Performer(strum(play="pressed"), bpm=120, opens=E_STANDARD)
    press_shape(q, "x32010")
    assert sounding(q.advance_to(0.0)) == [(2, 60), (4, 52), (5, 48)]


def test_the_root_follows_the_callers_chord_recognition():
    p = Performer(strum(), bpm=120, opens=E_STANDARD, chord_root=lambda notes: 7)     # G, whatever is held
    press_shape(p, "x32010")
    assert [lane for lane, _ in sounding(p.advance_to(0.0))] == [1, 2, 3, 4, 5]     # the open low E is below it
    assert p.state(0.0).root == 3                                                    # the open G: the root string
    q = Performer(strum(), bpm=120, opens=E_STANDARD, chord_root=lambda notes: None)  # no chord: the lowest pressed
    q.press(3, 57, 100, 0.0)
    assert max(lane for lane, _ in sounding(q.advance_to(0.0))) == 3


def test_relative_lanes_follow_the_root_string_and_its_alternate_bass():
    travis = parse_pattern({"name": "T", "lanes": {"R": "X . x .", "A": ". x . x", 1: "x . . ."}})
    expected = {"022100": [(6, 40), (4, 52), (6, 40), (4, 52)],     # E: root on 6, alternate 4
                "x32010": [(5, 48), (4, 52), (5, 48), (4, 52)],     # C: root on 5, alternate 4
                "xx0232": [(4, 50), (3, 57), (4, 50), (3, 57)],     # D: root on 4, alternate 3
                "320003": [(6, 43), (4, 50), (6, 43), (4, 50)]}     # G: root on 6, alternate 4 (open D)
    for shape, bass in expected.items():
        p = Performer(travis, bpm=120, opens=E_STANDARD)
        press_shape(p, shape)
        p.advance_to(0.0)                                          # step 1 as the fingers land (caught up)
        events = [e for e in p.advance_to(0.9) if e.kind == "on" and e.lane != 1]
        assert [(e.lane, e.note) for e in events] == bass[1:], shape
    p = Performer(travis, bpm=120, opens=E_STANDARD)
    p.set_muted([3, 4, 5, 6], 0.0)
    p.press(2, 60, 100, 0.0)                                       # a root on string 2: the alternate is string 1
    p.press(1, 64, 100, 0.0)
    p.advance_to(0.0)
    assert p.state(0.0).root == 2 and played(p.advance_to(STEP)) == [(1, 64)]


def test_a_string_covered_by_r_or_a_at_a_step_plays_once_at_the_louder_level():
    both = parse_pattern({"name": "B", "lanes": {"R": "x .", 5: "X .", "A": ". x", 4: ". x"}, "manual": []})
    p = Performer(both, bpm=120, opens=E_STANDARD)
    press_shape(p, "x32010")
    first = [(e.lane, e.note, e.value) for e in p.advance_to(0.0) if e.kind == "on" and e.lane == 5]
    assert first[-1] == (5, 48, 100)                                         # R and 5 at step 1: once, accented
    events = [e for e in p.advance_to(STEP + 0.01) if e.kind == "on"]
    assert [(e.lane, e.note, e.value) for e in events] == [(4, 52, 79)]       # A and 4: once


def test_relative_lanes_rest_with_nothing_to_follow_and_never_play_a_manual_string():
    p = Performer(parse_pattern({"name": "R", "lanes": {"R": "x x", 1: "x x"}, "manual": [5, 6]}), bpm=120,
                  opens=E_STANDARD)
    p.press(5, 48, 100, 0.0)                                       # a manual bass: through at once, not the pattern's
    p.press(2, 60, 100, 0.0)
    p.press(4, 52, 100, 0.0)
    events = p.advance_to(0.0)
    assert [(e.lane, e.source) for e in events if e.kind == "on"] == [(5, "manual"), (1, "pattern")]


def test_muted_strings_never_ring_open_but_a_pressed_one_plays():
    p = Performer(strum(), bpm=120, opens=E_STANDARD)
    p.set_muted([1, 6], 0.0)
    press_shape(p, "x02210")                                       # Am, the high E marked muted
    assert [lane for lane, _ in sounding(p.advance_to(0.0))] == [2, 3, 4, 5]
    p.set_muted([], 0.1)
    assert [lane for lane, _ in played(p.advance_to(STEP))] == [1, 2, 3, 4, 5]


def test_voices_r_is_the_lowest_held_voice_and_a_the_second_lowest():
    p = Performer(parse_pattern({"name": "V", "lanes": {"R": "x . .", "A": ". x .", 1: ". . x"}}), bpm=120,
                  addressing="voices")
    for note in (48, 52, 55):
        p.press(1, note, 100, 0.0)
    p.advance_to(0.0)                                              # R caught up as the higher notes came
    assert [e.note for e in p.advance_to(0.6) if e.kind == "on"] == [52, 55]


def test_catch_moves_an_r_hit_and_ends_an_open_string_the_new_root_mutes():
    p = Performer(parse_pattern({"name": "C", "lanes": {"R": "x .", 1: "x ."}}), bpm=120, opens=E_STANDARD)
    p.press(4, 52, 100, 0.0)                                       # E on string 4 first: Em with the open strings
    first = p.advance_to(0.0)
    p.press(5, 48, 100, 0.01)                                      # the A string's C within 30 ms: Cmaj7, root on 5
    events = p.advance_to(0.02)
    assert (6, 40) in played(first)                                # R rang the low E at first
    assert [(e.time, e.lane) for e in events if e.kind == "off" and e.lane == 6] == [(0.01, 6)]   # muted: it ends
    assert (5, 48) in played(events)                               # R played again on string 5
    assert p.state(0.02).root == 5


def test_press_chord_holds_every_note_before_the_first_hit():
    p = Performer(strum(), bpm=120, opens=E_STANDARD)
    p.set_muted([6], 0.0)
    p.press_chord([(5, 48, 100), (4, 52, 100), (3, 55, 100), (2, 60, 100), (1, 64, 100)], 0.0)   # C x32010
    events = p.advance_to(0.0)
    assert [e.kind for e in events] == ["on"] * 5 and sounding(events) == [(1, 64), (2, 60), (3, 55), (4, 52), (5, 48)]


# --- chords in key: a triad or a seventh stacked in thirds from the scale -------------------------------------
MAJOR = (0, 2, 4, 5, 7, 9, 11)
HARMONIC_MINOR = (0, 2, 3, 5, 7, 8, 11)
MELODIC_MINOR = (0, 2, 3, 5, 7, 9, 11)


def in_key(scale, tonic, root, seventh=False):
    found = diatonic_chord([(tonic + i) % 12 for i in scale], root, seventh)
    return None if found is None else found.name


def test_key_chords_are_the_scales_triads_and_sevenths_named_from_their_intervals():
    assert [in_key(MAJOR, 0, r) for r in (0, 2, 4, 5, 7, 9, 11)] == ["maj", "min", "min", "maj", "maj", "min", "dim"]
    assert [in_key(MAJOR, 0, r, True) for r in (0, 2, 4, 5, 7, 9, 11)] == [
        "maj7", "m7", "m7", "maj7", "7", "m7", "m7b5"]
    assert [in_key(HARMONIC_MINOR, 9, r, True) for r in (9, 11, 0, 2, 4, 5, 8)] == [   # A harmonic minor
        "mM7", "m7b5", "maj7#5", "m7", "7", "maj7", "dim7"]
    assert [in_key(MELODIC_MINOR, 0, r) for r in (0, 3, 7, 11)] == ["min", "aug", "maj", "dim"]
    assert in_key(MAJOR, 7, 66, True) == "m7b5"                     # G major: F# is its 7th degree (any octave)


def test_an_off_key_root_or_a_scale_that_is_not_seven_notes_has_no_key_chord():
    assert in_key(MAJOR, 0, 1) is None                              # C# in C major: nothing (strict)
    assert diatonic_chord([0, 2, 4, 7, 9], 0) is None              # a pentatonic: no thirds to stack
    odd = diatonic_chord([0, 2, 3, 6, 7, 8, 11], 3, True)           # Hungarian minor from its 3rd: unnamed, by its
    assert odd.intervals == (0, 4, 8, 11) and odd.name == "maj7#5"  # intervals; and one without a name of its own:
    rare = diatonic_chord([0, 2, 3, 6, 7, 8, 11], 2)                # D in C Hungarian minor: D F# Ab (1 3 b5)
    assert rare.intervals == (0, 4, 6) and rare.symbol("D") == "D(b5)"
    strange = diatonic_chord([0, 2, 3, 6, 7, 8, 11], 6)             # from F#: F# Ab C (0 2 6), named by its degrees
    assert strange.intervals == (0, 2, 6) and strange.symbol("F#") == "F#(2,b5)"


def test_every_new_type_voices_on_the_strings():
    from performer import build_voicing
    assert build_voicing(E_STANDARD, 47, 5, "m7b5").shape() == "x20201"     # Bm7b5 on the A string: B D A F
    for name in ("mM7", "maj7#5", "7b5", "7#5", "mM7b5"):
        voicing = build_voicing(E_STANDARD, 45, 5, name)
        assert {n % 12 for n in voicing.sounding.values()} <= {(9 + i) % 12 for i in CHORD_TYPES[name].intervals}
