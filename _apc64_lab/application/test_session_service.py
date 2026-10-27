"""T25: SessionService and Slot0Writer with the real domain and fake ports (s2, s5, s38 collaboration; inv5–inv7,
inv11; A15, A16, A22, A23, A30, A42, A43, A44; §2.7 a2, a5/q9, q4; a8; d21, d22, d38, d47, d75, d80)."""
import threading
import time
from datetime import timedelta

from _apc64_host.application.conftest import ManualClock
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.layout import ControlEvent
from _apc64_host.domain.outbound import WriteCapability
from _apc64_host.domain.unit_status import ReleaseReason
from _apc64_host.notation.compiler import compile_text
from _apc64_lab.application.conftest import (
    LOOPS_TAG, EngineDouble, Events, FakeBackups, FakeMemory, RecordingPublisher, TweaksDouble, Wall, host_ports,
    named,
)
from _apc64_lab.application.guarded_writer import GuardedWriter
from _apc64_lab.application.ports import SET_SESSION, HostLink
from _apc64_lab.application.registry import DefinitionIndex, GeneratorRegistry
from _apc64_lab.application.section_compiler import LabSectionCompiler
from _apc64_lab.application.session_service import SessionService
from _apc64_lab.domain.lab_section import INTERVAL_CYCLE, WINDOW_SHIFT
from _apc64_lab.domain.memory import BackupId, OutcomeCode
from _apc64_lab.domain.note_target import NoteTarget
from _apc64_lab.domain.session import RESTORED_MESSAGE
from _apc64_lab.generators import guitar, modes, root_highlight, scale

TONNETZ_C = "name: Tonnetz C\nlab:\n  generator: tonnetz\n  base: 48\n"
TONNETZ_C_COPY = "name: Tonnetz C copy\nlab:\n  generator: tonnetz\n  base: 48\n"
JAM = "name: Jam\ndevices: {mpc: MPC Live III MIDI 1}\npages:\n  1:\n    pad r1c1: note 36\n"
BACKUP = "slot0-2026-10-24T20-15"


class Source:
    def discover(self):
        return [("_apc64_lab/generators/guitar.py", guitar.GENERATOR),
                ("_apc64_lab/generators/modes.py", modes.GENERATOR),
                ("_apc64_lab/generators/root_highlight.py", root_highlight.SCHEME),
                ("_apc64_lab/generators/scale.py", scale.SCHEME)]


class Rig:
    def __init__(self, target=None, backups=None, threaded=False, memory=None):
        self.events = Events()
        self.memory = memory or FakeMemory(self.events)
        self.memory.events = self.events
        self.backups = backups or FakeBackups(self.events)
        self.backups.events = self.events
        self.engine, self.tweaks, self.clock = EngineDouble(), TweaksDouble(), ManualClock()
        self.link = HostLink(host_ports(self.engine, self.tweaks, self.clock))
        self.wall = Wall()
        self.writer = GuardedWriter(self.memory, self.backups, WriteCapability("test"), self.link, self.wall)
        self.registry = GeneratorRegistry(Source()).load()
        self.index = DefinitionIndex()
        self.held = []
        self.publisher = RecordingPublisher()
        self.target = target
        self.service = SessionService(self.writer, self.backups, self.registry, self.link, self.publisher,
                                      control=self.memory, held_notes=lambda: tuple(self.held), index=self.index,
                                      target=target, wall=self.wall, threaded=threaded, settle=0.0 if threaded else 0.03)
        self.compiler = LabSectionCompiler(self.registry.generators, self.registry.schemes, target)

    def layout(self, text, file):
        result = compile_text(text, file, sections={"lab": self.compiler})
        assert result.valid, [i.message() for i in result.issues]
        return result.layout

    def load(self, text=TONNETZ_C, file="tonnetz-c.yaml"):
        layout = self.layout(text, file)
        self.service.on_layout_loaded(layout, layout.section("lab"))
        self.service.drain()
        return layout

    def running(self, view=UnitView.CUSTOM):
        self.service.on_held(object())
        self.service.on_view(view)
        self.load()
        self.events.clear()
        return self

    def turn(self, steps=1):
        self.service.on_action(WINDOW_SHIFT, ControlEvent(steps=steps))

    def tempo(self):
        self.service.on_action(INTERVAL_CYCLE, ControlEvent(press=True))

    @property
    def slot0(self):
        return self.memory.slots[0]

    def r1c1(self):
        return self.slot0.pad(PadPos(1, 1)).note

    @property
    def oled(self):
        return self.engine.oled.rows if self.engine.oled else None


def loops():
    return FakeMemory().slots[0]


# --- activation -----------------------------------------------------------------------------------------
def test_activation_takes_one_session_backup_then_writes_at_oct_0():   # A22, d75, d38
    rig = Rig()
    rig.service.on_held(object())
    rig.service.on_view(UnitView.CUSTOM)
    rig.load()
    assert rig.events[:4] == [("read", 0), ("backup", BACKUP), ("open_session", BACKUP), ("write", 0)]
    assert rig.backups.get(BackupId(BACKUP)).data == loops().raw
    assert rig.r1c1() == 48 and rig.oled == ("Tonnetz C", "Oct +0")
    assert [b.id for b in rig.backups.list()][0] == BACKUP
    assert len([e for e in rig.events if e == ("read", 0)]) == 2          # the backup read and one read-back


def test_the_full_backup_of_slots_1_to_24_follows_the_first_write():   # §2.7 a5/q9
    rig = Rig()
    rig.service.on_held(object())
    rig.load()
    first_write = rig.events.index(("write", 0))
    reads = [e[1] for e in rig.events[first_write:] if e[0] == "read" and e[1] != 0]
    assert reads == list(range(1, 25))
    (full,) = rig.backups.sets()
    assert full.kind == SET_SESSION and full.covers_stored_slots and len(full.members) == 24


def test_a_full_backup_younger_than_10_minutes_is_reused():   # §2.7 a5/q9
    rig = Rig()
    rig.service.on_held(object())
    rig.load()
    rig.service.end(ReleaseReason.RELEASE)
    rig.events.clear()
    rig.wall.advance(minutes=9)
    rig.service.on_held(object())
    rig.service.drain()
    assert not any(e[0] == "read" and e[1] not in (0,) for e in rig.events)   # no slot 1–24 reads
    rig.service.end(ReleaseReason.RELEASE)
    rig.wall.advance(minutes=2)
    rig.events.clear()
    rig.service.on_held(object())
    rig.service.drain()
    assert len(rig.backups.sets()) == 2


def test_the_full_backup_steps_aside_for_an_encoder_shift():   # §2.7 a5/q9: never delays a shift, inv7
    rig = Rig()
    rig.service.on_held(object())
    rig.service.on_view(UnitView.CUSTOM)
    rig.service.on_layout_loaded(*_with_section(rig.layout(TONNETZ_C, "tonnetz-c.yaml")))
    writer = rig.service.slot0
    for _ in range(3):        # the start job, the first write, the read-back
        writer._step(ignore_settle=True)
    writer._step(ignore_settle=True)          # one full-backup step: slot 1
    rig.turn(+1)
    writer._step(ignore_settle=True)
    assert rig.events[-1] == ("write", 0) and rig.r1c1() == 60
    rig.service.drain()
    assert rig.backups.sets()[0].covers_stored_slots


def test_outside_custom_view_slot_0_is_written_and_press_custom_shows_after_1_s():   # A23, d21 (as amended)
    rig = Rig()
    rig.service.on_held(object())
    # the request cannot be sent (the gate dropped it): only then 'Press Custom' (2026-10-27)
    rig.memory.request_view = lambda view=UnitView.CUSTOM: rig.memory.views.append(view) and False
    rig.load()
    assert rig.r1c1() == 48 and rig.memory.views == [UnitView.CUSTOM]
    rig.clock.advance(0.9)
    assert rig.oled == ("Tonnetz C", "Oct +0")
    rig.clock.advance(0.2)
    assert rig.oled == ("Tonnetz C", "Press Custom") and rig.service.message == "Press Custom"
    rig.service.on_view(UnitView.CUSTOM)
    assert rig.oled == ("Tonnetz C", "Oct +0") and rig.service.message is None


def test_a_sent_custom_request_shows_no_prompt():   # d21 as amended 2026-10-27: the unit obeys, never echoes
    rig = Rig()
    rig.service.on_held(object())
    rig.load()
    assert rig.memory.views == [UnitView.CUSTOM]
    rig.clock.advance(1.5)
    assert rig.oled == ("Tonnetz C", "Oct +0") and rig.service.message is None


def test_activation_in_a_running_session_asks_for_custom_while_the_unit_is_elsewhere():   # d21/d22, 2026-10-27
    rig = Rig().running()
    rig.service.on_view(UnitView.SESSION)              # the user pressed Session on the unit
    assert rig.service.message == "Custom view off"
    rig.memory.views.clear()
    rig.load("name: Fourths\nlab:\n  generator: isomorphic\n", "fourths.yaml")
    assert rig.memory.views == [UnitView.CUSTOM]       # a switch within the session asks too
    rig.load("name: Fourths\nlab:\n  generator: isomorphic\n", "fourths.yaml")
    rig.service.on_view(UnitView.CUSTOM)               # as the host reports it once the request was sent
    rig.memory.views.clear()
    rig.service.on_layout_loaded(*_with_section(rig.layout(TONNETZ_C, "tonnetz-c.yaml")))
    assert rig.memory.views == []                      # in Custom view already: no request


def test_custom_view_reported_in_time_shows_no_prompt():
    rig = Rig()
    rig.service.on_held(object())
    rig.load()
    rig.service.on_view(UnitView.CUSTOM)
    rig.clock.advance(1.5)
    assert rig.oled == ("Tonnetz C", "Oct +0")


def test_nothing_is_written_while_the_unit_is_not_held():   # d70
    rig = Rig()
    rig.load()
    assert rig.events == [] and rig.service.state().active is None
    rig.service.on_held(object())
    rig.service.drain()
    assert rig.events[:2] == [("read", 0), ("backup", BACKUP)]   # the take starts the session (a11)


def test_no_answer_to_the_session_backup_read_writes_nothing():   # d79
    rig = Rig()
    rig.memory.no_reply.add(0)
    rig.service.on_held(object())
    rig.load()
    assert rig.memory.writes() == [] and rig.engine.warnings == ["could not back up slot 0; nothing written"]
    assert not rig.service.running


# --- playing --------------------------------------------------------------------------------------------
def test_a_burst_of_six_detents_ends_in_one_write_at_the_final_offset():   # A30, d28, §2.7 a2
    rig = Rig().running()
    rig.tempo()
    for _ in range(6):
        rig.turn(+1)
    rig.service.drain()
    assert rig.memory.writes() == [("write", 0)] and rig.r1c1() == 90 and rig.oled == ("Tonnetz C", "5th +6")


def test_the_final_write_of_a_burst_is_issued_within_50_ms():   # A30, inv7 (threaded writer, real time)
    memory = FakeMemory()
    sent = []

    def transmit(slot, record):           # each write takes 5 ms to transmit
        time.sleep(0.005)
        sent.append((time.monotonic(), record.pad(PadPos(1, 1)).note))
    memory.on_write = transmit
    rig = Rig(memory=memory, threaded=True)
    try:
        rig.service.on_held(object())
        rig.service.on_view(UnitView.CUSTOM)
        layout = rig.layout(TONNETZ_C, "tonnetz-c.yaml")
        rig.service.on_layout_loaded(layout, layout.section("lab"))
        _wait(lambda: rig.service.session.active and sent)
        _wait(lambda: rig.service.slot0.idle, 3.0)
        rig.tempo()
        last = None
        for _ in range(6):
            rig.turn(+1)
            last = time.monotonic()
            time.sleep(0.02)                  # 6 detents within 150 ms
        _wait(lambda: sent[-1][1] == 90)
        final_at, previous_end = sent[-1][0], sent[-2][0]
        assert final_at - 0.005 - max(last, previous_end) <= 0.05
        assert len(sent) <= 1 + 6
    finally:
        rig.service.close()


def test_the_definition_changing_rewrites_the_pads_at_the_same_window():   # A15, d9
    rig = Rig().running()
    rig.tempo()
    rig.turn(+2)
    rig.service.drain()
    before = rig.slot0.pad(PadPos(1, 1))
    rig.load(TONNETZ_C + "  scheme: root-highlight\n")
    after = rig.slot0.pad(PadPos(1, 1))
    assert after.note == before.note == 62 and after.rest != before.rest
    assert rig.oled == ("Tonnetz C", "5th +2") and len(rig.backups.list(0)) == 1


def test_a_page_tweak_saves_the_field_back_to_the_definition():   # A16 (base D2 = 50, deviation 8)
    rig = Rig().running()
    assert rig.service.tweak("base", "D2") == "saved"
    assert rig.tweaks.calls == [("tonnetz-c", "lab.base", "D2")]
    rig.load(TONNETZ_C.replace("base: 48", "base: D2"))
    assert rig.r1c1() == 50


def test_a_tweak_may_name_the_generated_layout_it_changes():   # §3.5 POST /api/lab/tweak {layout, field, value}
    rig = Rig()
    rig.index.record("fourths", rig.layout("name: Fourths\nlab:\n  generator: isomorphic\n",
                                           "fourths.yaml").section("lab"))
    rig.index.named("fourths", "Fourths")
    assert rig.service.tweak("row", 4, layout="Fourths") == "saved"
    assert rig.tweaks.calls == [("fourths", "lab.row", 4)]
    refused = rig.service.tweak("row", 4, layout="Spiral")
    assert refused.code is OutcomeCode.NOT_FOUND and refused.message == "no generated layout Spiral"
    assert refused.fix == "generated layouts: Fourths"
    assert rig.service.tweak("base", "D2").code is OutcomeCode.SESSION   # none active and none named


def test_an_identical_layout_under_another_name_writes_nothing():   # A13, d7
    rig = Rig().running()
    rig.load(TONNETZ_C_COPY, "tonnetz-c-copy.yaml")
    assert rig.memory.writes() == [] and rig.oled == ("Tonnetz C copy", "Oct +0")


def test_held_notes_are_ended_at_a_shift():   # A41 (the lab's half), d47
    rig = Rig().running()
    rig.held = [48]
    rig.tempo()
    rig.turn(+1)
    assert rig.engine.ended == [(48,)]


def test_the_edge_and_other_views_write_nothing():   # A31, A38, d22, d29
    rig = Rig().running()
    for _ in range(4):
        rig.turn(+1)
    rig.service.drain()
    rig.events.clear()
    rig.turn(+1)
    rig.service.drain()
    assert rig.memory.writes() == [] and rig.oled == ("Tonnetz C", "Oct +4 edge")
    rig.service.on_view(UnitView.NOTE)
    rig.turn(-1)
    rig.service.drain()
    assert rig.memory.writes() == [] and rig.service.message == "Custom view off"
    rig.service.on_view(UnitView.CUSTOM)
    assert rig.oled == ("Tonnetz C", "Oct +4") and rig.service.message is None


# --- ending ---------------------------------------------------------------------------------------------
def test_release_restores_slot_0_over_the_labs_record():   # A42, inv6, d64
    rig = Rig().running()
    rig.service.end(ReleaseReason.RELEASE)
    assert rig.slot0 == loops() and rig.service.message == RESTORED_MESSAGE
    assert RESTORED_MESSAGE == "slot 0 restored; the unit shows the project as unsaved, nothing was saved"
    assert rig.backups.marker is None and ("close_session",) in rig.events


def test_stop_and_sigterm_restore_too():   # inv6 (SIGTERM is the lifespan's release('stop'))
    rig = Rig().running()
    rig.service.end(ReleaseReason.STOP)
    assert rig.slot0 == loops()


def test_an_unplug_names_the_backup_and_keeps_the_marker():   # A43, d80, a8
    rig = Rig().running()
    rig.memory.held = False
    rig.service.end(ReleaseReason.UNPLUG)
    assert rig.service.message == f"slot 0 could not be restored; restore {BACKUP} after reconnecting"
    assert rig.memory.writes() == [] and rig.backups.marker == BACKUP and rig.service.recovery == BACKUP


def test_loading_a_host_layout_restores_slot_0():   # A44
    rig = Rig().running()
    rig.load(JAM, "jam.yaml")
    assert rig.slot0 == loops() and rig.engine.oled is None and not rig.service.running


def test_the_user_loading_another_project_ends_the_session_quietly():   # §2.7 a5/q9 (Project view)
    rig = Rig().running()
    rig.memory.slots[0] = rig.memory.slots[12]
    rig.service.on_view(UnitView.PROJECT)
    rig.service.on_view(UnitView.CUSTOM)
    rig.turn(+1)
    rig.service.drain()
    assert rig.memory.writes() == [] and not rig.service.running
    assert rig.service.message == f"lab session ended quietly (project view); nothing restored; session backup {BACKUP} kept"
    assert rig.backups.get(BackupId(BACKUP)).data == loops().raw and rig.backups.marker is None
    rig.service.end(ReleaseReason.RELEASE)
    assert rig.memory.writes() == [] and rig.slot0 == rig.memory.slots[12]   # release after it: no restore


def test_a_slot_0_matching_nothing_the_lab_wrote_ends_the_session_quietly():   # §2.7 a5/q9 (read-back)
    rig = Rig().running()
    rig.turn(+1)
    rig.memory.on_write = lambda slot, record: rig.memory.slots.__setitem__(0, rig.memory.slots[5])
    rig.service.drain()
    assert not rig.service.running and "slot 0 changed on the unit" in rig.service.message
    rig.memory.on_write = None
    rig.events.clear()
    rig.service.end(ReleaseReason.RELEASE)
    assert rig.memory.writes() == []


def test_a_read_back_of_an_earlier_lab_record_is_not_a_change():   # the slot-0 decision (inv4 vs §2.7 a5/q9)
    rig = Rig().running()
    first = rig.slot0
    rig.turn(+1)
    rig.memory.on_write = lambda slot, record: rig.memory.slots.__setitem__(0, first)   # the unit lags once
    rig.service.slot0._step(ignore_settle=True)
    rig.memory.on_write = None
    rig.service.drain()
    assert rig.service.running and rig.r1c1() == 60                          # re-sent, still our session


def test_release_after_an_on_unit_change_restores_nothing():   # §2.7 a5/q9
    rig = Rig().running()
    rig.memory.slots[0] = named(rig.memory.slots[3], 99)        # loaded on the unit, no report seen
    rig.service.end(ReleaseReason.RELEASE)
    assert rig.memory.writes() == [] and "nothing restored" in rig.service.message


def test_returning_to_the_lab_starts_a_fresh_session():   # §2.7 a5/q9
    rig = Rig().running()
    rig.memory.slots[0] = rig.memory.slots[12]
    rig.service.on_view(UnitView.PROJECT)
    rig.service.on_view(UnitView.CUSTOM)
    rig.events.clear()
    rig.wall.advance(minutes=1)
    rig.load(TONNETZ_C_COPY, "tonnetz-c-copy.yaml")
    assert rig.events[:2] == [("read", 0), ("backup", "slot0-2026-10-24T20-16")]
    assert rig.backups.get(BackupId("slot0-2026-10-24T20-16")).data == rig.memory.slots[12].raw
    assert rig.service.running and rig.r1c1() == 48
    rig.service.end(ReleaseReason.RELEASE)
    assert rig.slot0 == rig.memory.slots[12]                  # the new session restores the project they loaded


def test_a_marker_left_by_a_crash_is_a_pending_recovery():   # a8
    backups = FakeBackups()
    backups.marker = BACKUP
    rig = Rig(backups=backups)
    state = rig.service.state()
    assert state.recovery == {"backup": BACKUP, "message": (
        "the last lab session did not end cleanly; slot 0 may still hold a generated layout: "
        f"restore {BACKUP} to slot 0, or dismiss")}
    rig.service.on_held(object())
    rig.load()
    assert rig.memory.writes() == [] and rig.engine.warnings == [f"restore {BACKUP} to slot 0 first"]
    rig.service.recovered(BACKUP)
    rig.service.drain()
    assert rig.service.running and rig.service.recovery is None and rig.r1c1() == 48


def test_dismissing_a_recovery_lets_the_lab_start():   # a8
    backups = FakeBackups()
    backups.marker = BACKUP
    rig = Rig(backups=backups)
    rig.service.on_held(object())
    rig.load()
    outcome = rig.service.dismiss_recovery()
    rig.service.drain()
    assert outcome.message == f"recovery dismissed; {BACKUP} stays listed" and rig.r1c1() == 48


# --- previews (q4) and state ----------------------------------------------------------------------------
def test_a_library_entry_previews_in_slot_0_with_the_same_backup_and_restore():   # §2.7 q4
    rig = Rig()
    rig.service.on_held(object())
    entry = named(rig.memory.slots[12], 42)
    outcome = rig.service.preview("Live set B", entry)
    rig.service.drain()
    assert outcome.message == "previewing Live set B in slot 0; leave to restore slot 0"
    assert rig.slot0 == entry and rig.events[:2] == [("read", 0), ("backup", BACKUP)]
    rig.turn(+1)
    rig.service.drain()
    assert rig.slot0 == entry                                         # a preview has no window
    left = rig.service.leave()
    assert left.message == RESTORED_MESSAGE and rig.slot0 == loops()


def test_the_state_shows_the_window_the_backup_and_the_note_target():   # §3.5, §2.7 q2
    rig = Rig(target=NoteTarget.parse("MPC Live III MIDI 1 ch 2")).running()
    rig.tempo()
    rig.turn(+2)
    rig.service.drain()
    state = rig.service.state().to_json()
    active = state["active"]
    assert (active["layout"], active["interval"], active["offset"]) == ("tonnetz-c", "5th", 2)
    assert active["counts"] == {"octave": 0, "fifth": 2, "third": 0} and active["session_backup"] == BACKUP
    assert active["pads"][0] == {"pad": "r1c1", "note": 62, "rest": active["pads"][0]["rest"], "silent": False,
                                 "name": "D"}
    assert active["rows"] is None and active["scale"] is None
    assert state["target"] == {"default": "MPC Live III MIDI 1 ch 2 aftertouch pass", "routed": True,
                               "from": "default", "text": "MPC Live III MIDI 1 ch 2 aftertouch pass"}
    assert [g["name"] for g in state["generators"]] == ["tonnetz", "isomorphic", "guitar", "modes"]
    assert active["neck"] is None and active["window"]["steps"] == ["Oct", "5th", "3rd"]
    assert rig.publisher.of_kind("lab")[-1].active["offset"] == 2


def test_the_state_gives_the_pad_grid_its_row_names_and_the_scale_spelled_in_key():
    rig = Rig().running()
    rig.load("name: Modes\nlab:\n  generator: modes\n  base: 49\n  scheme: scale\n  scale: locrian\n", "modes.yaml")
    active = rig.service.state().to_json()["active"]
    assert active["rows"][:2] == ["Locrian", "Phrygian"] and active["rows"][-1] == "Chromatic"
    assert active["scale"]["key"] == "locrian" and active["scale"]["root_name"] == "C♯"
    assert active["definition"]["scheme_params"] == {"scale": "locrian"}
    by_pad = {p["pad"]: p for p in active["pads"]}
    assert by_pad["r1c2"]["name"] == "D" and by_pad["r1c4"]["name"] == "F♯"   # C♯ Locrian: C♯ D E F♯ G A B
    assert by_pad["r2c5"]["name"] == "G♯"                       # C♯ Phrygian's 5: each row is spelled in its mode


def test_the_playing_layouts_key_reaches_the_harmony_views():   # spelling from context (2026-10-27)
    rig = Rig()
    keys = []
    rig.service._on_key = keys.append
    rig.running()
    assert keys[-1] is None                                           # Tonnetz C, scheme fifths: no key
    rig.load("name: Modes\nlab:\n  generator: modes\n  base: 49\n  scheme: scale\n  scale: locrian\n", "modes.yaml")
    assert keys[-1][1] == "C♯" and keys[-1][6] == "F♯" and rig.service.key() == keys[-1]
    rig.service.leave()
    assert keys[-1] is None


GUITAR = "name: Guitar\nlab:\n  generator: guitar\n  tuning: drop-d\n"


def test_a_guitar_layout_moves_by_fret_and_page_and_the_state_gives_the_neck():   # the guitar amendment
    rig = Rig().running()
    rig.load(GUITAR, "guitar.yaml")
    assert rig.oled == ("Guitar", "Frets 0-7")
    assert rig.slot0.pad(PadPos(2, 1)).note == 38 and rig.slot0.pad(PadPos(2, 1)).channel == 6
    assert rig.slot0.pad(PadPos(7, 8)).note == 71 and rig.slot0.pad(PadPos(7, 8)).channel == 1
    rig.turn(+2)
    rig.tempo()
    rig.turn(+1)
    rig.service.drain()
    assert rig.oled == ("Guitar", "Frets 8-15") and rig.slot0.pad(PadPos(2, 1)).note == 46
    active = rig.service.state().to_json()["active"]
    assert (active["interval"], active["offset"], active["transposition"]) == ("Page", 8, 8)
    assert active["window"] == {"steps": ["Fret", "Page"], "step": "Page", "position": 8, "label": "Page 8-15",
                                "lowest": 0, "highest": 17, "pages": [0, 8, 16, 17], "shown": 8, "unit": "Frets"}
    assert active["neck"]["first"] == 8 and active["neck"]["frets"] == 24
    assert active["neck"]["strings"][-1] == {"string": 6, "open": 38, "name": "D", "channel": 6}
    assert active["rows"][1] == "6 D" and active["rows"][0] == "" and active["pads"][8]["name"] == "B♭"   # r2c1: low D + 8
    assert rig.service.transposition_of("guitar") == 8                      # q3: push stores the window


def test_a_guitar_flashes_the_step_kind_and_the_neck_end_for_a_second():   # 2026-10-27
    rig = Rig().running()
    rig.load(GUITAR, "guitar.yaml")
    rig.tempo()
    assert rig.oled == ("Guitar", "Step: Page")
    rig.clock.advance(1.1)
    assert rig.oled == ("Guitar", "Frets 0-7")
    rig.turn(-1)                                       # past the nut: refused
    assert rig.oled == ("Guitar", "Neck end")
    rig.clock.advance(0.5)
    rig.tempo()                                        # a newer toggle cancels the pending flash's end …
    assert rig.oled == ("Guitar", "Step: Fret")
    rig.clock.advance(0.6)                             # … the first flash's second is up: nothing changes
    assert rig.oled == ("Guitar", "Step: Fret")
    rig.clock.advance(0.5)
    assert rig.oled == ("Guitar", "Frets 0-7")
    rig.turn(+1)
    rig.service.drain()
    assert rig.oled == ("Guitar", "Frets 1-8")         # a step shows the frets at once


def test_without_a_target_the_state_says_notes_are_only_shown():   # §2.7 q2
    state = Rig().running().service.state().to_json()
    assert state["target"] == {"default": None, "routed": False,
                               "text": "notes are only shown: no default target and no layout target"}


# --- helpers --------------------------------------------------------------------------------------------
def _with_section(layout):
    return layout, layout.section("lab")


def _wait(condition, seconds=2.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.001)
    raise AssertionError("timed out")
