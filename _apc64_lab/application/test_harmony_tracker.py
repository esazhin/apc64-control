"""T28: HarmonyTracker over the host's play stream and input doubles (s19, s23 collaboration; inv15, inv16;
A41's views, A69, A70, A78, A80; §2.7 q7)."""
import asyncio

import pytest

from _apc64_host.application.conftest import ManualClock, RecordingFeedback
from _apc64_host.application.play_stream import PlayStream
from _apc64_host.application.ports import HostPorts
from _apc64_host.domain.effects import ENDED_BY_WINDOW_SHIFT, NOTE_ENDED, PlayEvent, PlaySource, PlaySourceKind
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.midi import ControlChange, NoteOff, NoteOn
from _apc64_lab.application.conftest import RecordingPublisher
from _apc64_lab.application.harmony_tracker import INPUTS_KEY, HarmonyTracker
from _apc64_lab.application.ports import HostLink, MemorySettings

CUSTOM = PlaySource(PlaySourceKind.CUSTOM)
NOTES = PlaySource(PlaySourceKind.NOTES)
SESSION = PlaySource(PlaySourceKind.SESSION_BINDING)


def on(note, port=CUSTOM, velocity=90):
    return PlayEvent("note_on", note=note, velocity=velocity, port=port)


def off(note, port=CUSTOM):
    return PlayEvent("note_off", note=note, port=port)


class Rig:
    def __init__(self, settings=None, max_lag=5.0):
        self.clock = ManualClock()
        self.stream = PlayStream(self.clock, max_lag=max_lag)
        self.feedback = RecordingFeedback()
        self.publisher = RecordingPublisher()
        self.settings = settings or MemorySettings()
        self.tracker = HarmonyTracker(self.publisher, self.settings,
                                      HostLink(HostPorts(stream=self.stream, inputs=self.feedback)))
        self.tracker.start()

    def play(self, *events):
        for event in events:
            self.stream.publish(event)
        self.tracker.pump()

    def chords(self):
        return [s.chord for s in self.publisher.published]


def held_names(state):
    return [h["name"] for h in state.to_json()["held"]]


def test_notes_port_notes_are_held():   # A69, d49
    rig = Rig()
    rig.play(on(57, NOTES))
    assert rig.tracker.state().to_json()["held"][0]["pc"] == 9 and rig.tracker.state().chord == "A"


def test_session_view_triggers_do_not_feed_the_views():   # A70, d50
    rig = Rig()
    rig.play(on(36, SESSION))
    assert rig.publisher.published == [] and rig.tracker.state().held == ()


def test_snapshots_follow_the_played_order_one_per_event():   # A78, d58, s23.c1
    rig = Rig()
    rig.stream.publish(on(48))
    rig.clock.advance(0.02)
    rig.stream.publish(on(52))
    rig.tracker.pump()
    assert [s.held for s in rig.publisher.published] == [(48,), (48, 52)]


def test_a_chord_and_its_triad():   # A68's harmony half, inv16
    rig = Rig()
    rig.play(on(48), on(52), on(55))
    state = rig.tracker.state()
    assert state.chord == "C" and [t.label for t in state.triads] == ["C"]


def test_two_pads_on_one_note_hold_it_until_the_last_lets_go():   # A80, d46
    rig = Rig()
    rig.play(on(41), on(41), off(41))
    assert rig.tracker.state().held == (41,)
    rig.play(off(41))
    assert rig.tracker.state().held == ()


def test_a_note_ended_by_a_shift_clears_it_and_its_release_adds_nothing():   # A41 (views), d47
    rig = Rig()
    rig.play(on(48))
    rig.play(PlayEvent(NOTE_ENDED, note=48, reason=ENDED_BY_WINDOW_SHIFT, port=CUSTOM))
    assert rig.tracker.state().held == ()
    published = len(rig.publisher.published)
    rig.play(off(48))
    assert len(rig.publisher.published) == published


def test_aftertouch_and_other_kinds_change_nothing():
    rig = Rig()
    rig.play(on(48), PlayEvent("aftertouch", note=48, aftertouch=60, port=CUSTOM), PlayEvent("press", port=SESSION))
    assert len(rig.publisher.published) == 1


def test_a_closed_subscription_is_renewed():   # s19: StreamClosed resubscribes
    rig = Rig(max_lag=1.0)
    rig.stream.publish(on(48))
    rig.clock.advance(2.0)
    rig.stream.publish(on(52))                       # the tracker fell behind: its subscription closes
    rig.tracker.pump()
    rig.play(on(55))
    assert 55 in rig.tracker.state().held and rig.stream.watchers == 1


def test_the_held_custom_notes_for_a_shift():   # d47 (SessionService's end_notes)
    rig = Rig()
    rig.stream.publish(on(48))
    rig.stream.publish(on(57, NOTES))
    assert rig.tracker.held_notes(PlaySourceKind.CUSTOM) == (48,)


def test_a_selected_input_feeds_the_views_and_is_remembered():   # §2.7 q7
    settings = MemorySettings()
    rig = Rig(settings)
    answer = rig.tracker.select_inputs(["Keystation 49 MIDI 1"])
    assert answer["message"] == "harmony follows the APC64 and Keystation 49 MIDI 1"
    assert settings.get(INPUTS_KEY) == ["Keystation 49 MIDI 1"]
    rig.feedback.deliver("Keystation 49 MIDI 1", NoteOn(1, 60, 80))
    rig.feedback.deliver("Keystation 49 MIDI 1", ControlChange(1, 1, 3))
    assert rig.tracker.state().held == (60,)
    again = Rig(settings)                              # a restart: the choice is remembered
    again.feedback.deliver("Keystation 49 MIDI 1", NoteOn(1, 64, 80))
    assert again.tracker.state().held == (64,)
    again.tracker.select_inputs([])                    # dropped: its notes end, its listener goes
    assert again.tracker.state().held == () and again.feedback.active() == []
    again.feedback.deliver("Keystation 49 MIDI 1", NoteOff(1, 64))
    assert again.tracker.state().held == ()


def test_the_apc64s_own_ports_are_not_a_selectable_input():
    with pytest.raises(DomainInvariantError):
        Rig().tracker.select_inputs(["APC64 Notes"])


def test_run_reads_the_stream_on_the_loop():   # s19.c1
    rig = Rig()

    async def scenario():
        task = asyncio.ensure_future(rig.tracker.run())
        await asyncio.sleep(0)
        rig.stream.publish(on(48))
        rig.stream.publish(on(52))
        for _ in range(5):
            await asyncio.sleep(0)
        rig.tracker.stop()
        task.cancel()
        return rig.tracker.state().held

    assert asyncio.run(scenario()) == (48, 52)


# --- the guitar amendment (2026-10-27): voices with the channel they arrived on ----------------------------
def on_string(note, channel, port=CUSTOM):
    return PlayEvent("note_on", note=note, velocity=90, port=port, channel=channel)


def off_string(note, channel, port=CUSTOM):
    return PlayEvent("note_off", note=note, port=port, channel=channel)


def played(rig):
    return [(p["source"], p["channel"], p["note"]) for p in rig.tracker.state().to_json()["played"]]


def test_one_pitch_on_two_strings_is_held_twice_and_each_string_is_named():
    rig = Rig()
    rig.play(on_string(45, 6), on_string(45, 5), on_string(64, 1))     # low E fret 5, the open A, the high E
    assert rig.tracker.state().held == (45, 64) and rig.tracker.state().chord != "—"
    assert played(rig) == [("custom", 5, 45), ("custom", 6, 45), ("custom", 1, 64)]
    rig.play(off_string(45, 5))
    assert rig.tracker.state().held == (45, 64) and played(rig) == [("custom", 6, 45), ("custom", 1, 64)]
    assert rig.publisher.published[-1].played == (("custom", 6, 45), ("custom", 1, 64))


def test_a_shift_ending_a_pitch_on_two_strings_ends_both_voices():   # d47 with several channels
    rig = Rig()
    rig.play(on_string(45, 6), on_string(45, 5))
    rig.play(*[PlayEvent(NOTE_ENDED, note=45, reason=ENDED_BY_WINDOW_SHIFT, port=CUSTOM, channel=c) for c in (5, 6)])
    assert rig.tracker.state().held == () and played(rig) == []
    rig.play(off_string(45, 6), off_string(45, 5))                      # the unit's later releases add nothing
    assert rig.tracker.state().held == () and played(rig) == []
    assert rig.tracker.held_notes() == ()


def test_sources_without_string_identity_carry_no_channel():
    rig = Rig()
    rig.play(on_string(60, 3, NOTES))
    rig.tracker.select_inputs(["Keys"])
    rig.feedback.deliver("Keys", NoteOn(4, 62, 80))
    assert played(rig) == [("notes", None, 60), ("input", None, 62)]
    rig.feedback.deliver("Keys", NoteOff(4, 62))
    rig.play(off_string(60, 3, NOTES))
    assert played(rig) == []


# --- after the guitar live test (2026-10-27) --------------------------------------------------------------------
def test_the_trail_clears_and_the_page_hears_it():
    rig = Rig()
    rig.play(on(48), on(52), on(55))
    assert rig.tracker.state().trail == ("C",)
    assert rig.tracker.clear_trail()["trail"] == [] and rig.tracker.state().trail == ()
    assert rig.publisher.published[-1].trail == ()


def test_the_layouts_key_spells_the_held_notes():
    rig = Rig()
    rig.play(on(49), on(56))
    assert held_names(rig.tracker.state()) == ["C♯2", "G♯2"]          # no key: a fifth above the lowest
    rig.tracker.set_key({8: "A♭", 10: "B♭", 0: "C", 1: "D♭", 3: "E♭", 5: "F", 7: "G"})
    assert held_names(rig.publisher.published[-1]) == ["D♭2", "A♭2"]  # A♭ major's names, published at once
    count = len(rig.publisher.published)
    rig.tracker.set_key({8: "A♭", 10: "B♭", 0: "C", 1: "D♭", 3: "E♭", 5: "F", 7: "G"})
    assert len(rig.publisher.published) == count                      # unchanged: nothing published


def test_the_inputs_followed_are_published():
    rig = Rig()
    rig.tracker.select_inputs(["Keys"])
    assert rig.publisher.published[-1] == {"kind": "inputs", "apc64": ["APC64 Custom", "APC64 Notes"],
                                           "inputs": ["Keys"]}


def test_the_performers_voicing_is_shown_on_its_strings_and_a_voiced_root_or_control_is_not_counted():   # Phase 2
    from _apc64_lab.application.ports import TAKEN_CONTROL, TAKEN_VOICED
    tracker = HarmonyTracker(RecordingPublisher())
    assert not tracker.apply(PlayEvent("note_on", note=45, velocity=90, port=CUSTOM, reason=TAKEN_VOICED, channel=5))
    assert not tracker.apply(PlayEvent("note_on", note=0, velocity=90, port=CUSTOM, reason=TAKEN_CONTROL, channel=16))
    tracker.show_voicing([(5, 45), (4, 52), (3, 57), (2, 60), (1, 64)])                  # Am x02210
    state = tracker.state()
    assert state.chord == "Am" and [(v[0], v[1], v[2]) for v in state.played][:2] == [("custom", 5, 45), ("custom", 4, 52)]
    tracker.show_voicing([(5, 45), (4, 52), (3, 55), (2, 60), (1, 64)])                  # Am7: one string changed
    assert tracker.state().chord == "Am7" and tracker.held_notes() == ()                 # never ended at a shift
    tracker.show_voicing(())
    assert tracker.state().chord == "—" and tracker.state().played == ()
