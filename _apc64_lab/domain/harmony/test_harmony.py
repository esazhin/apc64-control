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
    # spelled above the lowest held note since 2026-10-27 (a minor second is a D♭ above C): the contract's own
    # 'C Db D', with Unicode ♭; chord_label keeps MusicCat's fixed table
    assert analyse([C3, Db3, D3]).chord == "C D♭ D"
    assert chord_label([C3, Db3, D3]) == "C C♯ D"


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
                         "trail_triads", "chord_root", "chord_tones", "played", "names"}   # §3.5's eight, plus the trail's
    assert json["triads"] == [{"root": 0, "quality": "major", "label": "C", "display": "C"}]   # triads, the chord's root and tones
    assert json["played"] == []   # the tracker adds the voices (source, channel, note); the core leaves it empty


def test_the_chord_root_and_tones_are_the_named_chords():
    assert (analyse([E3, G3, C4]).chord_root, analyse([E3, G3, C4]).chord_tones) == (0, (0, 4, 7))   # C/E
    g7 = analyse([55, 59, 62, 65])
    assert g7.chord == "G7" and g7.chord_root == 7 and set(g7.chord_tones) == {7, 11, 2, 5}
    assert analyse([C3]).chord_root is None and analyse([C3, Db3, D3]).chord_tones == ()


# --- the trail takes every named chord (d57 as amended 2026-10-27) ------------------------------------------------
def play(harmony, *chords):
    """Each chord pressed note by note, then released note by note."""
    for chord in chords:
        for note in chord:
            harmony.note_on(note)
        for note in chord:
            harmony.note_off(note)
    return harmony.state()


def test_the_trail_takes_any_named_chord_not_only_triads():
    state = play(Harmony(), [59, 65, 68], [52, 56, 59], [62, 67, 69], [55, 59, 62, 65])
    assert state.trail == ("F°/B", "E", "Dsus4", "G7")
    assert [t.label for t in state.trail_triads] == ["E", "G"]   # sus4 and ° have no triad: text only


def test_single_notes_intervals_and_unnamed_sets_are_not_chords():
    assert play(Harmony(), [60], [60, 67], [60, 61, 62]).trail == ()


def test_an_inversion_of_the_newest_chord_adds_nothing():
    assert play(Harmony(), [C3, E3, G3], [E3, G3, C4], [55, 60, 64]).trail == ("C",)


def test_a_chord_that_grows_replaces_its_own_entry():
    harmony = Harmony()
    for note in (C3, E3, G3, 59):        # C, then + B with nothing released
        harmony.note_on(note)
    assert harmony.state().trail == ("Cmaj7",)
    harmony.note_off(59)                 # a release: the next chord is a new entry
    harmony.note_on(58)
    assert harmony.state().trail == ("Cmaj7", "C7")


def test_a_grown_chord_equal_to_the_entry_before_collapses_into_it():
    harmony = Harmony()
    play(harmony, [C3, E3, G3, 59])
    for note in (C3, E3, G3):
        harmony.note_on(note)
    assert harmony.state().trail == ("Cmaj7", "C")
    harmony.note_on(59)
    assert harmony.state().trail == ("Cmaj7",)


def test_the_trail_keeps_the_last_8_and_clears():
    harmony = Harmony()
    play(harmony, *([[r, r + 4, r + 7] for r in range(48, 58)]))
    assert len(harmony.state().trail) == 8 and harmony.state().trail[-1] == "A"
    assert harmony.clear_trail().trail == () and harmony.state().trail_triads == ()


# --- spelling from context (2026-10-27) -----------------------------------------------------------------------------
def test_held_notes_are_spelled_in_their_chord():
    e_major = analyse([52, 56, 59]).to_json()
    assert [n["name"] for n in e_major["held"]] == ["E2", "G♯2", "B2"] and e_major["names"]["8"] == "G♯"
    assert [n["name"] for n in analyse([58, 62, 65]).to_json()["held"]] == ["B♭2", "D3", "F3"]
    assert analyse([56, 59, 63]).chord == "G♯m"            # fewer accidentals than A♭ C♭ E♭
    assert analyse([61, 65, 68]).chord == "D♭"             # fewer than C♯ E♯ G♯
    assert analyse([59, 62, 65, 68]).to_json()["names"]["8"] == "A♭"   # B°7's diminished seventh
    assert analyse([60, 64, 68]).to_json()["names"]["8"] == "G♯"       # C+'s augmented fifth


def test_without_a_chord_notes_are_spelled_above_the_lowest():
    assert [n["name"] for n in analyse([52, 56]).to_json()["held"]] == ["E2", "G♯2"]   # E + a major third
    assert analyse([52, 60]).to_json()["names"]["0"] == "C"                            # E + a minor sixth


def test_a_key_spells_what_is_not_a_chord_and_the_root_of_a_chord():
    a_flat = {8: "A♭", 10: "B♭", 0: "C", 1: "D♭", 3: "E♭", 5: "F", 7: "G"}
    assert analyse([49, 56], key=a_flat).chord == "D♭ A♭"
    assert analyse([56, 59, 63], key=a_flat).chord == "A♭m"   # the key's A♭, not G♯
    harmony = Harmony()
    assert harmony.set_key(a_flat) and not harmony.set_key(dict(a_flat))
    assert play(harmony, [56, 59, 63]).trail == ("A♭m",)


def test_spelled_octaves_follow_the_letter():
    from _apc64_lab.domain.harmony.spelling import note_label_spelled, spell_above
    assert note_label_spelled(59, "C♭") == "C♭3" and note_label_spelled(60, "B♯") == "B♯2"
    assert spell_above("E", 8) == "G♯" and spell_above("B", 8, 6) == "A♭" and spell_above("E", 3) == "D♯"


# --- readable spelling and display labels (coordinator follow-up, 2026-10-27) ---------------------------------
def test_rare_enharmonics_fall_back_to_the_plain_name_unless_the_key_needs_them():
    f_dim = analyse([59, 65, 68])
    assert f_dim.chord == "F°/B" and f_dim.to_json()["names"]["11"] == "B"           # not C♭
    assert analyse([52, 56, 59]).to_json()["names"]["8"] == "G♯"                     # letter-wise otherwise
    assert [n["name"] for n in analyse([58, 62, 65]).to_json()["held"]] == ["B♭2", "D3", "F3"]
    assert analyse([61, 65, 68]).chord == "D♭"                                       # never C♯ E♯ G♯
    assert analyse([60, 64, 68]).to_json()["names"]["8"] == "G♯"                     # C+ keeps its G♯ (not rare)
    c_dim7 = analyse([48, 51, 54, 57])                                               # C°7's B𝄫 reads A
    assert c_dim7.chord == "Cdim7" and c_dim7.to_json()["names"]["9"] == "A"
    g_flat = {6: "G♭", 8: "A♭", 10: "B♭", 11: "C♭", 1: "D♭", 3: "E♭", 5: "F"}       # G♭ major needs its C♭
    assert analyse([59, 65, 68], key=g_flat).to_json()["names"]["11"] == "C♭"
    assert analyse([47, 54], key=g_flat).to_json()["held"][0]["name"] == "C♭2"       # 47 spelled C♭: octave 2


def test_triads_display_in_context_and_keep_their_fixed_label_for_lookup():
    e_major = analyse([52, 56, 59]).to_json()
    assert [t["display"] for t in e_major["neighbours"]] == ["Em", "C♯m", "G♯m"]
    assert [t["label"] for t in e_major["neighbours"]] == ["Em", "C♯m", "A♭m"]       # the lookup key stays
    assert e_major["circle"] == ["E", "B", "A♭"]                                     # lookup names stay fixed
