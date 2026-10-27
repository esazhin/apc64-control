"""The harmony core on the contract §4.2 values (T6). Spelling follows §2.7 a25 (MusicCat Explorer's),
which replaces the contract's flats-only names: A72's 'Dbm' is 'C♯m', A75's 'C Db D' is 'C C♯ D', degrees use '♭'."""
from _apc64_lab.domain.harmony import (
    MAJOR, MINOR, ChordTrail, Harmony, HeldNotes, Triad, analyse, chord_label, circle_order, complete_triads,
    note_label, parse_pitch_class, triads_containing,
)

# The contract's §4.2 rows name 48 'C3' (C4 = 60); the host counts C3 = 60 (contract 1 q1), so the numbers
# are what is checked and labels follow the host: 48 is shown as 'C2' (a build decision).
C3, D3, Db3, E3, F3, G3, A3, C4 = 48, 50, 49, 52, 53, 55, 57, 60


def labels(triads):
    return [t.label for t in triads]


def test_c_major_triad_lights_its_triangle_and_names_the_chord():   # A68
    state = analyse([C3, E3, G3])
    assert state.chord == "C" and state.triads == (Triad(0, MAJOR),)
    assert state.held == (48, 52, 55) and [note_label(n) for n in state.held] == ["C2", "E2", "G2"]
    assert note_label(60) == "C3" and note_label(73) == "C♯4"
    assert circle_order({0, 4, 7}) == [0, 7, 4]   # C-G-E
    assert state.to_json()["circle"] == ["C", "G", "E"]


def test_nothing_held_shows_a_dash_and_no_triangle():   # A71, d51
    state = analyse([])
    assert state.chord == "—" and state.triads == () and state.to_json()["held"] == []


def test_e_alone_gives_degrees_and_the_six_triads_containing_it():   # A72, d52
    state = analyse([E3])
    degrees = state.to_json()["degrees"]
    assert degrees["G"] == "♭3" and degrees["B"] == "5" and degrees["E"] == "1"
    assert set(labels(state.hints)) == {"C", "Em", "Am", "E", "A", "C♯m"}
    assert labels(triads_containing(4)) == ["C", "Em", "E", "C♯m", "A", "Am"]   # around the node
    assert all(4 in t.pitch_classes for t in state.hints)


def test_c_major_neighbours_are_parallel_relative_and_leading_tone():   # A73, d61
    assert labels(analyse([C3, E3, G3]).neighbours) == ["Cm", "Am", "Em"]
    assert labels(Triad(9, MINOR).neighbours()) == ["A", "C", "F"]
    for triad in (Triad(0, MAJOR), Triad(9, MINOR)):
        assert all(len(triad.pitch_classes & n.pitch_classes) == 2 for n in triad.neighbours())


def test_first_inversion_is_a_slash_chord():   # A74, d54
    assert analyse([E3, G3, C4]).chord == "C/E"


def test_an_unrecognised_set_shows_its_pitch_names():   # A75, d55
    assert analyse([C3, Db3, D3]).chord == "C C♯ D"


def test_octave_doubling_counts_once():   # A76, d56
    state = analyse([C3, E3, G3, C4])
    assert state.chord == "C" and state.triads == (Triad(0, MAJOR),)


def test_the_trail_keeps_8_drops_the_oldest_and_ignores_a_repeat():   # A77, d57
    trail = ChordTrail()
    for triad in (Triad(0, MAJOR), Triad(9, MINOR), Triad(5, MAJOR), Triad(2, MINOR), Triad(7, MAJOR),
                  Triad(4, MINOR), Triad(9, MINOR), Triad(0, MAJOR)):
        trail.add(triad)
    harmony = Harmony(trail=trail)
    for note in (F3, A3, C4):          # F major
        harmony.note_on(note)
    for note in (F3, A3, C4):
        harmony.note_off(note)
    for note in (F3, A3, C4):          # F major again
        harmony.note_on(note)
    assert harmony.state().trail == ("Am", "F", "Dm", "G", "Em", "Am", "C", "F")


def test_two_pads_on_one_note_hold_it_until_the_last_lets_go():   # A80, d46
    held = HeldNotes()
    held.on(41)
    held.on(41)
    held.off(41)
    assert held.notes == [41] and held.count(41) == 1
    held.off(41)
    assert held.notes == [] and not held


def test_a_window_shift_ends_every_hold_of_a_note_at_once():   # d47
    harmony = Harmony()
    harmony.note_on(48)
    harmony.note_on(48)
    assert harmony.end([48]).held == ()


def test_complete_triads_and_chords_agree_with_the_held_set():   # inv16
    for notes in ([C3, E3, G3], [A3, C4, 64], [E3, G3, 59], [48, 52, 55, 57]):
        state = analyse(notes)
        pcs = {n % 12 for n in notes}
        assert all(t.pitch_classes <= pcs for t in state.triads)
    assert labels(complete_triads({0, 4, 7, 9})) == ["C", "Am"]
    assert chord_label([60]) == "C" and chord_label([60, 67]) == "C G"


def test_pitch_class_names_parse_in_either_spelling():
    assert [parse_pitch_class(t) for t in ("C", "C#", "C♯", "Db", "D♭", "B♯", "Ebb", "x", "")] == [
        0, 1, 1, 1, 1, 0, 2, None, None]


def test_the_state_is_json_for_the_views():   # §3.5 GET /api/lab/harmony
    json = analyse([C3, E3, G3]).to_json()
    assert set(json) == {"held", "chord", "triads", "degrees", "hints", "neighbours", "trail", "circle",
                         "trail_triads"}   # §3.5's eight, plus the trail's triads for the lattice
    assert json["triads"] == [{"root": 0, "quality": "major", "label": "C"}]
