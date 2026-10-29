"""Switching patterns while notes are held (contract 2 §2.10): what the player holds is one record over every string,
partitioned again between the pattern strings and the manual ones at every pattern change, so no note sticks and
no pattern runs on after everything is let go, whatever the sequence of presses, switches and chord types."""
import random

import pytest

from _apc64_host.domain.midi import NoteOff, NoteOn, PolyAftertouch
from _apc64_lab.application.ports import TAKEN
from _apc64_lab.application.test_performer import STEP, Rig
from _apc64_lab.application.test_performer_chords import PICKER, ChordRig

OPENS = {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}
PATTERNS = ("arpeggio-manual-bass", "waltz", "travis", "strum", "arpeggio")


def edited_123(rig):
    """1-2-3 + bass as the user edited it: string 4 in the pattern, 16 steps."""
    data = rig.service.state()["pattern"]["data"] if rig.service.state()["pattern"]["id"] == "arpeggio-manual-bass" \
        else None
    assert data is not None
    return {**data, "length": 16, "manual": [5, 6],
            "lanes": {"1": "...x...x...x...x", "2": ".x...x...x...x..", "3": "..x...x...x...x.", "4": "x.......x......."}}


def play_edit(rig, data):
    return rig.service.change(pattern_data=data, edits="arpeggio-manual-bass")


def revert(rig, pattern_id):
    """The file of `pattern_id` plays again (its edit dropped)."""
    return rig.service.change(revert=pattern_id, pattern=pattern_id)


def ons(messages, lane=None):
    return [(m.channel, m.note) for m in messages if isinstance(m, NoteOn) and (lane is None or m.channel == lane)]


def test_a_manual_string_held_into_a_pattern_that_plays_it_is_released_by_its_release():
    rig = Rig()                                                 # 1-2-3 + bass: strings 4, 5, 6 manual
    assert rig.play(NoteOn(5, 48, 90)) == TAKEN                 # C on string 5, through as played
    rig.play(NoteOn(3, 57, 100))
    rig.until(STEP + 0.01)
    rig.sent()
    rig.service.change(pattern="waltz")                         # string 5 is the waltz's (its bass in bar 2)
    assert rig.sent() == [NoteOff(5, 48)]                       # the manual note ends at the switch
    rig.until(4 * 2 * STEP)                                     # waltz step 4 (bar 2, beat 1): string 5 plays C
    assert (5, 48) in ons(rig.sent())
    assert rig.play(NoteOff(5, 48)) == TAKEN                    # its release is the performer's, not the router's
    assert rig.play(NoteOff(3, 57)) == TAKEN
    rig.until(10.0)
    assert not rig.service.state()["running"] and rig.service._core.pressed() == ()


def test_a_pattern_string_held_into_a_pattern_that_leaves_it_manual_does_not_sound_again():
    rig = Rig()
    play_edit(rig, edited_123(rig))                             # string 4 in the pattern
    rig.play(NoteOn(4, 52, 100))                                # E on string 4: the pattern starts, 4 plays at once
    rig.play(NoteOn(3, 57, 100))
    rig.until(STEP + 0.01)
    assert (4, 52) in ons(rig.sent())
    rig.service.change(pattern="waltz")
    revert(rig, "arpeggio-manual-bass")                         # the file: string 4 manual again
    sent = rig.sent()
    assert NoteOff(4, 52) in sent and (4, 52) not in ons(sent)  # the pattern's note ends; the held one stays silent
    assert rig.play(NoteOff(4, 52)) == TAKEN and rig.sent() == []   # its release sends nothing more
    rig.service.select_type("maj")                              # the record is clean: one note held is a root
    rig.play(NoteOff(3, 57))
    rig.play(NoteOn(3, 55, 100))
    assert rig.service.state()["voicing"]["symbol"] == "G"
    rig.play(NoteOff(3, 55))
    rig.until(20.0)
    assert not rig.service.state()["running"] and rig.service._core.pressed() == ()


def balance(messages, sounding, problems):
    for m in messages:
        key = (m.channel, m.note)
        if isinstance(m, NoteOn):
            sounding[key] = sounding.get(key, 0) + 1
            if sounding[key] > 1:
                problems.append(f"{key} on twice")
        elif isinstance(m, NoteOff):
            if not sounding.get(key):
                problems.append(f"{key} off while not sounding")
            else:
                sounding[key] -= 1


@pytest.mark.parametrize("seed", range(60))
def test_any_sequence_of_presses_switches_and_chord_types_leaves_nothing_behind(seed):
    rng = random.Random(seed)
    rig = ChordRig()
    rig.service.change(pattern="arpeggio-manual-bass")
    edit = edited_123(rig)
    held, sounding, problems = [], {}, []
    for _ in range(80):
        roll = rng.random()
        if roll < 0.3:
            lane = rng.randint(1, 6)
            note = OPENS[lane] + rng.randint(0, 5)
            if (lane, note) not in held:
                held.append((lane, note))
                assert rig.play(NoteOn(lane, note, rng.randint(30, 127))) is not None
        elif roll < 0.5 and held:
            lane, note = held.pop(rng.randrange(len(held)))
            assert rig.play(NoteOff(lane, note)) is not None, (lane, note)
        elif roll < 0.55 and held:
            lane, note = rng.choice(held)
            assert rig.play(PolyAftertouch(lane, note, rng.randint(0, 127))) is not None
        elif roll < 0.7:
            choice = rng.randrange(4)
            if choice == 0:
                rig.service.change(pattern=rng.choice(PATTERNS))
            elif choice == 1:
                rig.service.select_slot(rng.choice((1, 2, 4)))
            elif choice == 2 and rig.service.state()["pattern"]["id"] == "arpeggio-manual-bass":
                play_edit(rig, {**edit, "step": rng.choice(("1/8", "1/4", "1/16"))})
            else:
                revert(rig, rig.service.state()["pattern"]["id"] or "travis")
        elif roll < 0.78:
            rig.service.select_type(rng.choice((None, "maj", "min", "m7", "7")))
        else:
            rig.timer.t += rng.uniform(0.0, 0.4)
            due = rig.timer.ticker(rig.timer.t)
            while due is not None and due <= rig.timer.t:
                due = rig.timer.ticker(due)
        balance(rig.sent(), sounding, problems)
    for lane, note in held:
        assert rig.play(NoteOff(lane, note)) is not None
    end = rig.timer.t + 3.0
    due = rig.timer.ticker(rig.timer.t)
    while due is not None and due <= end:
        rig.timer.t = due
        due = rig.timer.ticker(due)
    rig.timer.t = end
    rig.service.tick(end)
    balance(rig.sent(), sounding, problems)
    assert problems == []
    assert {key: n for key, n in sounding.items() if n} == {}       # every on has its off
    assert rig.service._core.pressed() == () and not rig.service.state()["running"]
    assert rig.service._physical == {} and rig.service._fed == {}
