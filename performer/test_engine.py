"""The engine's rules (docs/performer-format.md, "The engine"), driven by explicit times only."""
import pytest

from performer import Event, Performer, parse_pattern

STEP = 0.25                                   # one 1/8 step at 120 BPM
E_STANDARD = {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}


def pattern(**overrides):
    data = {"name": "Arp", "meter": "4/4", "step": "1/8", "length": 8,
            "lanes": {1: ". . . x . . . x", 2: ". x . . . x . .", 3: "x . x . x . x ."}, "manual": [4, 5, 6]}
    data.update(overrides)
    return parse_pattern(data)


def notes(events, kind="on"):
    return [(round(e.time, 4), e.lane, e.note) for e in events if e.kind == kind]


def run(performer, until):
    return performer.advance_to(until)


def test_the_pattern_starts_at_the_first_press_with_step_one_at_once():
    p = Performer(pattern(), bpm=120)
    p.press(3, 55, 127, 10.0)
    assert notes(p.advance_to(10.0)) == [(10.0, 3, 55)]
    assert notes(run(p, 10.3)) == [] and p.state(10.3).step == 1 and p.state(10.3).running
    assert notes(run(p, 10.0 + 2 * STEP)) == [(10.5, 3, 55)]           # lane 3 again on step 3; off first


def test_steps_follow_the_tempo_and_a_tempo_change_keeps_the_phase():
    p = Performer(pattern(lanes={1: "x x x x x x x x"}), bpm=120)
    p.press(1, 64, 127, 0.0)
    assert [t for t, _, _ in notes(run(p, 0.6))] == [0.0, 0.25, 0.5]
    p.set_tempo(60, 0.6)                       # from 0.6 a step is 0.5 s: step 3 is 0.6 of a step away
    assert [t for t, _, _ in notes(run(p, 2.0))] == [0.9, 1.4, 1.9]
    with pytest.raises(ValueError):
        p.set_tempo(400, 2.0)


def test_a_manual_lane_passes_through_and_never_starts_or_stops_the_pattern():
    p = Performer(pattern(), bpm=120)
    p.press(5, 48, 90, 0.0)
    assert p.advance_to(0.0) == [Event(0.0, "on", 5, 48, 90, "manual")] and not p.running
    p.aftertouch(5, 48, 70, 0.05)
    p.release(5, 48, 0.1)
    assert [(e.kind, e.value) for e in p.advance_to(0.1)] == [("aftertouch", 70), ("off", 0)]
    assert p.next_time() is None


def test_the_users_alternating_bass_under_a_held_triad():
    """Strings 4, 5, 6 by hand (5+123, 6+123 …), the 1-2-3 pattern going on over the held high strings."""
    p = Performer(pattern(), bpm=120)
    for lane, note in ((1, 64), (2, 60), (3, 55)):              # A minor high strings: E C G… held
        p.press(lane, note, 127, 0.0)
    p.press(5, 45, 100, 0.0)                                     # bass on string 5
    p.release(5, 45, 0.4)
    p.press(6, 40, 100, 0.5)                                     # bass on string 6
    events = run(p, 1.0)
    assert [(e.lane, e.note, e.source) for e in events if e.kind == "on" and e.source == "manual"] == [(5, 45, "manual"), (6, 40, "manual")]
    assert notes([e for e in events if e.source == "pattern"]) == [(0.0, 3, 55), (0.25, 2, 60), (0.5, 3, 55), (0.75, 1, 64), (1.0, 3, 55)]
    # Am → C on the high strings, the bass now on string 4: the pattern is not restarted, its next hits play C
    p.press(2, 60, 127, 1.1)
    p.press(1, 64, 127, 1.1)
    p.press(3, 52, 127, 1.1)                                     # the chord changed on string 3: its G ends now
    events = run(p, 1.6)
    assert (1.1, 3, 55) in notes(events, "off") and notes(events) == [(1.25, 2, 60), (1.5, 3, 52)]


def test_one_note_per_lane_and_a_release_never_cuts_a_note():
    p = Performer(pattern(lanes={1: "x . . . x . . ."}), bpm=120)
    p.press(1, 64, 127, 0.0)
    p.release(1, 64, 0.1)                                        # rings on; the pattern stops a step later
    events = run(p, 1.0)
    assert notes(events, "off") == [(0.35, 1, 64)] and not p.running


def test_a_quick_chord_change_with_a_gap_goes_on_and_a_later_press_restarts():
    p = Performer(pattern(lanes={1: "x x x x x x x x"}), bpm=120)
    p.press(1, 64, 127, 0.0)
    p.release(1, 64, 0.3)
    p.press(1, 65, 127, 0.45)                                    # within the grace: no restart
    assert notes(run(p, 0.8)) == [(0.0, 1, 64), (0.25, 1, 64), (0.5, 1, 65), (0.75, 1, 65)]
    p.release(1, 65, 0.8)
    run(p, 3.0)
    assert not p.running
    p.press(1, 67, 127, 3.1)
    assert notes(p.advance_to(3.1)) == [(3.1, 1, 67)] and p.state(3.1).step == 0


def test_catch_plays_a_chord_pressed_just_after_the_first_finger_whole():
    p = Performer(pattern(lanes={1: "x . . . . . . .", 2: "x . . . . . . .", 3: "x . . . . . . ."}), bpm=120)
    p.press(3, 55, 127, 0.0)
    p.press(2, 60, 127, 0.012)
    p.press(1, 64, 127, 0.02)
    p.press(1, 65, 127, 0.2)                                     # too late to catch: it waits for the next hit
    assert notes(run(p, 0.3)) == [(0.0, 3, 55), (0.012, 2, 60), (0.02, 1, 64)]
    assert notes(run(p, 0.3), "off") == []


def test_latch_keeps_the_last_notes_until_a_new_press_or_stop():
    p = Performer(pattern(lanes={1: "x x x x x x x x", 2: "x x x x x x x x"}), bpm=120, latch=True)
    p.press(1, 64, 127, 0.0)
    p.press(2, 60, 127, 0.0)
    p.release(1, 64, 0.1)
    p.release(2, 60, 0.1)
    assert notes(run(p, 0.6)) == [(0.0, 1, 64), (0.0, 2, 60), (0.25, 1, 64), (0.25, 2, 60), (0.5, 1, 64), (0.5, 2, 60)]
    p.press(1, 65, 127, 0.6)                                     # a new press after release: a new set (lane 2 empty)
    assert notes(run(p, 0.8)) == [(0.75, 1, 65)] and p.state(0.8).latched == ((1, 65),)
    p.stop(0.8)
    assert notes(p.advance_to(0.8), "off") == [(0.8, 1, 65)] and not p.running and p.next_time() is None


def test_latch_off_with_nothing_held_stops_a_step_later():
    p = Performer(pattern(lanes={1: "x x x x x x x x"}), bpm=120, latch=True)
    p.press(1, 64, 127, 0.0)
    p.release(1, 64, 0.1)
    p.set_latch(False, 0.6)
    run(p, 0.84)
    assert p.running
    run(p, 0.86)
    assert not p.running


def test_velocity_is_the_cell_scaled_by_the_press_and_open_strings_take_the_latest_press():
    p = Performer(pattern(lanes={1: "X . . . . . . .", 2: "x . . . . . . ."}, manual=[]), bpm=120, opens=E_STANDARD)
    p.press(1, 64, 64, 0.0)
    events = p.advance_to(0.0)
    assert [(e.lane, e.note, e.value) for e in events if e.kind == "on"] == [(1, 64, 64), (2, 59, 50)]


def test_play_all_rings_an_unpressed_string_open_as_on_a_guitar():
    """An open-position Am (x02210) presses only strings 4, 3 and 2; a 5-3-2-1 pattern still plays four notes, the
    A string and the high E ringing open."""
    arp = pattern(lanes={5: "x . . . . . . .", 3: ". x . . . . . .", 2: ". . x . . . . .", 1: ". . . x . . . ."},
                  manual=[])
    p = Performer(arp, bpm=120, opens=E_STANDARD)
    for lane, note in ((4, 52), (3, 57), (2, 60)):                # E, A, C fretted
        p.press(lane, note, 127, 0.0)
    assert notes(run(p, 0.8)) == [(0.0, 5, 45), (0.25, 3, 57), (0.5, 2, 60), (0.75, 1, 64)]


def test_play_pressed_plays_only_the_pressed_lanes_and_the_grid_never_moves():
    arp = pattern(lanes={5: "x . . . . . . .", 3: ". x . . . . . .", 2: ". . x . . . . .", 1: ". . . x . . . ."},
                  manual=[], play="pressed")
    p = Performer(arp, bpm=120, opens=E_STANDARD)
    for lane, note in ((4, 52), (3, 57), (2, 60)):
        p.press(lane, note, 127, 0.0)
    # strings 5 and 1 are not pressed: their steps stay silent, and steps 2 and 3 keep their times
    assert notes(run(p, 2.3)) == [(0.25, 3, 57), (0.5, 2, 60), (2.25, 3, 57)]
    q = Performer(arp, bpm=120, opens=E_STANDARD, play="all")      # the caller's override wins
    q.press(3, 57, 127, 0.0)
    assert [lane for _, lane, _ in notes(run(q, 0.8))] == [5, 3, 2, 1]
    q.set_play("pressed", 0.8)
    assert [lane for _, lane, _ in notes(run(q, 2.3))] == [3] and q.play_mode == "pressed"
    with pytest.raises(ValueError):
        q.set_play("some", 2.0)


def test_play_pressed_keeps_every_later_step_on_its_time():
    p = Performer(pattern(lanes={1: "x x x x . . . .", 2: ". x . . . . . ."}, play="pressed"), bpm=120)
    p.press(2, 60, 127, 0.0)                                      # string 1 not pressed: steps 1, 3, 4 silent
    assert notes(run(p, 1.0)) == [(0.25, 2, 60)]
    p.press(1, 64, 127, 2.1)                                      # pressed late: its next hits keep the grid
    assert [t for t, lane, _ in notes(run(p, 3.0)) if lane == 1] == [2.25, 2.5, 2.75]


def test_an_open_string_is_not_a_press_it_neither_starts_nor_keeps_the_pattern():
    p = Performer(pattern(lanes={1: "x x x x x x x x"}), bpm=120, opens=E_STANDARD)
    assert p.next_time() is None and not p.running                # nothing pressed: nothing plays, open or not
    p.press(2, 60, 127, 0.0)                                      # a fretted note starts it; string 1 rings open
    p.release(2, 60, 0.1)
    assert notes(run(p, 1.0)) == [(0.0, 1, 64)] and not p.running     # the grace step (0.25) sounds nothing


def test_voices_have_no_open_string_an_unheld_voice_rests():
    p = Performer(pattern(lanes={1: "x . . . . . . .", 2: ". x . . . . . .", 3: ". . x . . . . ."}, manual=[]),
                  addressing="voices", bpm=120, opens=E_STANDARD)
    p.press(1, 60, 127, 0.0)
    assert notes(run(p, 0.6)) == [(0.0, 1, 60)]


def test_strum_spreads_down_low_to_high_and_up_high_to_low():
    p = Performer(pattern(lanes={k: "x x . . . . . ." for k in (1, 2, 3)}, manual=[], strum="d u . . . . . .",
                          spread=10), bpm=120)
    for lane, note in ((1, 64), (2, 60), (3, 55)):
        p.press(lane, note, 127, 0.0)
    events = notes(run(p, 0.4))
    assert events[:3] == [(0.0, 3, 55), (0.01, 2, 60), (0.02, 1, 64)]
    assert events[3:] == [(0.25, 1, 64), (0.26, 2, 60), (0.27, 3, 55)]


def test_swing_delays_every_second_step_and_gate_shortens_notes():
    p = Performer(pattern(lanes={1: "x x x x . . . ."}, swing=75, gate=0.5), bpm=120)
    p.press(1, 64, 127, 0.0)
    events = run(p, 1.0)
    assert [t for t, _, _ in notes(events)] == [0.0, 0.375, 0.5, 0.875]
    assert [t for t, _, _ in notes(events, "off")] == [0.125, 0.5, 0.625, 1.0]


def test_humanize_stays_in_range_and_is_deterministic_for_a_seed():
    def played(seed):
        p = Performer(pattern(lanes={1: "x x x x x x x x"}, humanize={"timing": 5, "velocity": 10}), bpm=120, seed=seed)
        p.press(1, 64, 127, 0.0)
        return [(e.time, e.value) for e in run(p, 1.9) if e.kind == "on"]
    first = played(1)
    assert first == played(1) and first != played(2)
    assert all(abs(t - k * STEP) <= 0.005 + 1e-9 and 90 <= v <= 110 for k, (t, v) in enumerate(first))
    assert first[0][0] == 0.0                                    # never before the press


def test_voices_addressing_counts_held_notes_from_the_top():
    p = Performer(pattern(lanes={1: "x . . . . . . .", 2: ". x . . . . . .", 3: ". . x . . . . ."}, manual=[]),
                  addressing="voices", bpm=120)
    for note in (48, 52, 55):                                    # C E G on one keyboard channel, one at a time
        p.press(1, note, 127, 0.0)
    played = notes(run(p, 0.6))                                  # lane 1 is caught up as the higher notes come
    assert played == [(0.0, 1, 48), (0.0, 1, 52), (0.0, 1, 55), (0.25, 2, 52), (0.5, 3, 48)]


def test_set_pattern_goes_on_at_the_same_step_count():
    p = Performer(pattern(lanes={1: "x x x x x x x x"}), bpm=120)
    p.press(1, 64, 127, 0.0)
    run(p, 0.3)
    p.set_pattern(pattern(lanes={1: "x . x . x . x ."}, step="1/16"), 0.3)
    assert [t for t, _, _ in notes(run(p, 0.8))] == [0.5, 0.75]    # 0.6 beats in: 1/16 step 2.4; steps 4 and 6 hit


def test_end_held_releases_and_silence_ends_everything():
    p = Performer(pattern(), bpm=120)
    p.press(3, 55, 127, 0.0)
    p.press(5, 45, 100, 0.0)
    p.end_held([55, 45], 0.1)
    events = p.advance_to(0.1)
    assert notes(events, "off") == [(0.1, 5, 45)] and p.state(0.1).held == ()
    run(p, 1.0)
    assert not p.running
    p.press(5, 45, 100, 2.0)
    p.silence(2.1)
    assert notes(p.advance_to(2.1), "off") == [(2.1, 5, 45)]


def test_the_same_inputs_give_the_same_events():
    def once():
        p = Performer(pattern(swing=60, humanize={"timing": 3}), bpm=97, seed=7)
        p.press(3, 55, 120, 1.0)
        p.press(2, 60, 100, 1.01)
        p.press(5, 45, 90, 1.2)
        p.release(3, 55, 2.0)
        return run(p, 5.0)
    assert once() == once()


def test_holding_and_pressed_report_every_held_note():
    p = Performer(pattern(), bpm=120)
    p.press(2, 60, 100, 0.0)
    p.press(2, 62, 100, 0.1)                                     # a second fret on string 2: it plays, both held
    assert p.pressed() == ((2, 60), (2, 62)) and p.holding(2, 60) and not p.holding(3, 60)
    assert p.state(0.1).held == ((2, 62),)


def test_every_hit_plays_after_a_change_to_a_coarser_step_and_back():
    """1/8 → 1/4 halves the step numbers: a new step may carry the number a lane last played at in the old pattern,
    and must play all the same (a hit's identity is the pattern change it belongs to and its step)."""
    eighths = pattern(lanes={1: "x . . . . . . .", 2: "x x x x x x x x"})
    quarters = pattern(step="1/4", lanes={1: "x . . . . . . .", 2: "x x x x x x x x"})
    p = Performer(eighths, bpm=120)
    p.press_chord([(1, 64, 127), (2, 60, 127)], 0.0)
    run(p, 20.5 * STEP)                                     # 1/8 steps 0 … 20: lane 1 last played at step 16
    p.set_pattern(quarters, 20.5 * STEP)                    # 10.25 quarter steps in: from step 11
    hits = notes(run(p, 20.5 * STEP + 14 * 2 * STEP))
    lane1 = [t for t, lane, _ in hits if lane == 1]
    assert lane1 == [round(16 * 2 * STEP, 4), round(24 * 2 * STEP, 4)]    # steps 16 and 24 of the 1/4 pattern
    assert len([t for t, lane, _ in hits if lane == 2]) == 14
    back = 20.5 * STEP + 14 * 2 * STEP
    p.set_pattern(eighths, back)
    again = notes(run(p, back + 16 * STEP))
    assert len([t for t, lane, _ in again if lane == 2]) == 16 and len([1 for _, lane, _ in again if lane == 1]) == 2


# --- letting go: no open strings, no wrong bass at the end -----------------------------------------------------
STRUM = {"name": "Strum", "meter": "4/4", "step": "1/8", "length": 8,
         "lanes": {k: "X . x x . x x x" for k in range(1, 7)}, "strum": "d . d u . u d u", "spread": 12,
         "humanize": {"timing": 3, "velocity": 6}}
TRAVIS = {"name": "Travis", "meter": "4/4", "step": "1/8", "length": 8, "swing": 54,
          "lanes": {1: "x . . . . . . x", 2: ". . . x . . . .", 3: ". x . . . x . .", "R": "X . . . x . . .",
                    "A": ". . x . . . x ."}}
CHORDS = {"C": {5: 48, 4: 52, 2: 60}, "Am": {4: 52, 3: 57, 2: 60}, "G": {6: 43, 5: 47, 1: 67}, "D": {3: 57, 2: 62, 1: 66}}


def sounding_chord(performer, t):
    """(lane, note) the held chord sounds at its hits: what is pressed, and the open strings that ring with it."""
    chord = {lane: note for lane, note in performer.state(t).held}
    root = performer.state(t).root
    rings = {(lane, note) for lane, note in E_STANDARD.items() if lane not in chord and lane <= root}
    return {*chord.items(), *rings}


@pytest.mark.parametrize("seed", range(40))
def test_letting_go_of_a_chord_at_any_moment_rings_no_open_string_and_no_wrong_bass(seed):
    import random
    rng = random.Random(seed)
    data = STRUM if seed % 2 else TRAVIS
    name, shape = rng.choice(sorted(CHORDS.items()))
    p = Performer(parse_pattern(data), opens=E_STANDARD, bpm=rng.choice((80, 100, 140)), seed=seed)
    p.press_chord([(lane, note, 100) for lane, note in shape.items()], 0.0)
    start = rng.uniform(1.0, 3.0)                     # anywhere against the steps, mid-strum too
    run(p, start)
    allowed = sounding_chord(p, start)
    order = list(shape.items())
    rng.shuffle(order)
    t = start
    events = []
    for lane, note in order:
        p.release(lane, note, t)
        events += [(t, e) for e in p.advance_to(t)]
        last = t
        t += rng.uniform(0.0, 0.1)                     # staggered: 0–100 ms apart
        events += [(e.time, e) for e in p.advance_to(t)]
    events += [(e.time, e) for e in p.advance_to(last + 2.0)]
    ons = [e for _, e in events if e.kind == "on"]
    wrong = [(round(e.time - start, 3), e.lane, e.note) for e in ons if (e.lane, e.note) not in allowed]
    late = [(round(e.time - last, 3), e.lane, e.note) for e in ons if e.time > last]
    assert wrong == [] and late == [], (name, wrong, late)
    assert not p.running


def test_with_nothing_held_the_grace_step_plays_nothing_and_a_quick_press_goes_on_in_phase():
    p = Performer(parse_pattern(STRUM), opens=E_STANDARD, bpm=120)
    p.press_chord([(lane, note, 100) for lane, note in CHORDS["C"].items()], 0.0)
    run(p, 0.6)
    for lane, note in CHORDS["C"].items():
        p.release(lane, note, 0.6)
    assert notes(run(p, 0.76)) == []                  # the grace: step 3 (0.75 s) sounds nothing
    p.press_chord([(lane, note, 100) for lane, note in CHORDS["Am"].items()], 0.76)   # within the catch
    caught = notes(p.advance_to(0.85))                # the strum's hits already due, caught, and the rest
    assert sorted((lane, note) for _, lane, note in caught) == [(1, 64), (2, 60), (3, 57), (4, 52), (5, 45)]
    assert p.state(0.8).step == 3                      # in phase: no restart


def test_a_finger_lifted_from_a_held_chord_rings_open_after_the_settle_time():
    p = Performer(parse_pattern({"name": "Two", "lanes": {2: "x x x x x x x x"}}), opens=E_STANDARD, bpm=120)
    p.press_chord([(lane, note, 100) for lane, note in CHORDS["C"].items()], 0.0)
    run(p, 0.42)
    p.release(2, 60, 0.42)                             # C → Cmaj7: the finger on string 2 lifted
    assert notes(run(p, 0.6)) == []                    # step 3 (0.5 s) is within the settle time: silent
    assert notes(run(p, 0.8)) == [(0.75, 2, 59)]       # the lift was meant: the open B rings from the next hit


def test_a_voicings_muted_strings_stay_muted_through_the_release_of_its_root_with_the_latch():
    p = Performer(parse_pattern(STRUM), opens=E_STANDARD, bpm=120, latch=True)
    p.set_muted([3, 6], 0.0)                           # a voicing with string 3 muted inside it
    p.press_chord([(lane, note, 100) for lane, note in CHORDS["C"].items()], 0.0)
    run(p, 0.1)
    for lane, note in CHORDS["C"].items():
        p.release(lane, note, 0.1)
    p.set_muted([], 0.1)                               # the service: no voicing now
    played = [lane for _, lane, _ in notes(run(p, 2.0))]
    assert 5 in played and 3 not in played             # latched: it plays on, the muted string stays muted
    p.press_chord([(lane, note, 100) for lane, note in CHORDS["C"].items()], 2.0)   # the next press: fretted
    assert 3 in [lane for _, lane, _ in notes(run(p, 2.5))]
