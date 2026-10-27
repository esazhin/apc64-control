import asyncio
import threading

import pytest

from _apc64_host.application.activity import ActivityLog
from _apc64_host.application.conftest import (
    Catalog, ManualClock, MemoryStore, RecordingFeedback, RecordingTargets, run,
)
from _apc64_host.application.engine import EngineOk, HeldUnit, HostEngine, UnknownLayout
from _apc64_host.application.library import LayoutLibrary
from _apc64_host.application.outbound_gate import GateResult, OutboundGate
from _apc64_host.application.play_stream import PlayStream
from _apc64_host.domain.conftest import (
    RED, bank, drum_pads, feedback, layout, mix_strips, note, notes_rule, page, toggle_cc,
)
from _apc64_host.domain.controls import PadPos, SceneButton, Shift, Strip, TrackButton
from _apc64_host.domain.effects import (
    ActivityResult, InputSource, Press, Release, StripMove, UnitView,
)
from _apc64_host.domain.layout import LayoutId, NavState, UnitPortRole
from _apc64_host.domain.leds import LedState
from _apc64_host.domain.midi import ControlChange, NoteOff, NoteOn, PolyAftertouch
from _apc64_host.domain.outbound import CONTRACT1_POLICY
from _apc64_host.domain.resolver import resolve
from _apc64_host.infrastructure.simulated_apc64 import SimulatedApc64
from _apc64_host.protocol import sysex
from _apc64_host.protocol.midi_codec import encode
from _apc64_host.protocol.surface_map import NOTE_OF, encode_input, encode_led

R1C1, R1C2 = PadPos(1, 1), PadPos(1, 2)
MPC_PORT = "MPC Live III MIDI 1"


def jam(id="jam", name="Jam", **kw):
    pages = kw.pop("pages", None) or [
        page(1, "Drums", {**drum_pads(), R1C1: note(36, colour=RED), TrackButton(1): toggle_cc(20)}),
        page(2, "Keys", {R1C1: note(50)}), page(4, "Four", {R1C1: note(60)})]
    return layout(id, name, pages=pages, banks=[bank(1, "Mix", mix_strips())], routing=[notes_rule()], **kw)


class GateDouble:
    """Records every frame offered; answers DROPPED while nothing is attached (the unit is not held)."""

    def __init__(self):
        self.frames = []
        self.attached = False

    def send(self, frames):
        frames = list(frames)
        self.frames += frames
        return [GateResult.SENT if self.attached else GateResult.DROPPED for _ in frames]


class Learn:
    def __init__(self, capture=()):
        self.capture = set(capture)
        self.seen = []

    def intercept(self, control):
        self.seen.append(control)
        return "captured" if control in self.capture else "pass"


class Calibration:
    def __init__(self):
        self.observed = []

    def observe(self, played, view):
        self.observed.append((played, view))


class Rig:
    def __init__(self, layouts=(jam(),), missing=(), catalog=None, gate=None, learn=None, store=None):
        self.clock = ManualClock()
        self.gate = gate or GateDouble()
        self.targets = RecordingTargets(missing)
        self.feedback = RecordingFeedback()
        self.activity = ActivityLog()
        self.stream = PlayStream(self.clock)
        self.watch = self.stream.subscribe()
        self.library = LayoutLibrary()
        self.learn = learn or Learn()
        self.calibration = Calibration()
        self.store = store or MemoryStore()
        self.engine = HostEngine(gate=self.gate, targets=self.targets, feedback=self.feedback,
                                 activity=self.activity, stream=self.stream, library=self.library,
                                 learn=self.learn, calibration=self.calibration, clock=self.clock,
                                 store=self.store, catalog=catalog, wall=lambda: 1234.5)
        for lay in layouts:
            self.library.register(lay.id, lay)
        if layouts:
            self.engine.start()

    def texts(self):
        return [e.text() for e in self.activity.recent()]


def test_a_replica_click_with_no_unit_sends_the_binding_and_the_leds_are_dropped_silently():   # A16, A70
    rig = Rig()
    assert rig.engine.replica_input(Press(R1C1)) == EngineOk(rig.engine.nav)
    rig.engine.replica_input(Release(R1C1))
    assert rig.targets.sent == [(MPC_PORT, NoteOn(10, 36, 127)), (MPC_PORT, NoteOff(10, 36))]
    assert rig.gate.frames and not rig.engine.held   # the LED went to the gate, which dropped it
    events = [e for e in rig.watch.take() if e.kind in ("press", "release")]
    assert [(e.kind, e.source, e.at) for e in events] == [("press", InputSource.REPLICA, 1234.5),
                                                          ("release", InputSource.REPLICA, 1234.5)]


def test_a_missing_device_is_listed_not_sent_and_labelled_missing():   # A83
    rig = Rig(missing=["MPC Live"])
    rig.engine.replica_input(Press(R1C1))
    assert rig.texts()[0] == "pad r1c1 → note 36 ch 10 → mpc: not sent, mpc missing"
    snapshot = rig.engine.snapshot()
    assert snapshot.missing == {"mpc"}
    assert resolve(snapshot.layout, snapshot.nav, snapshot.missing)[R1C1].label == "Note 36 → mpc (missing)"
    press = next(e for e in rig.watch.take() if e.kind == "press")
    assert press.reason == "not sent: mpc missing"


def test_missing_devices_come_from_the_port_catalog_and_presence_changes():   # d58, d61 (A86 engine side)
    rig = Rig(catalog=Catalog("USB MIDI Interface MIDI 1"))
    assert rig.engine.snapshot().missing == {"mpc", "bitwig"}
    rig.targets.presence[0](MPC_PORT, True)
    assert rig.engine.snapshot().missing == {"bitwig"}
    rig.targets.presence[0](MPC_PORT, False)
    assert rig.engine.snapshot().missing == {"mpc", "bitwig"}


def test_a_press_is_listed_and_streamed_with_time_source_control_velocity_and_message():   # A120
    rig = Rig()
    rig.engine.replica_input(Press(R1C1, source=InputSource.UNIT))
    assert rig.texts()[0] == "pad r1c1 → note 36 ch 10 → MPC Live III MIDI 1: sent"
    assert rig.activity.recent()[0].at == 1234.5
    press = next(e for e in rig.watch.take() if e.kind == "press")
    assert (press.control, press.velocity, press.sent, press.at) == (R1C1, 127, ("note 36 ch 10",), 1234.5)


def test_holding_with_no_layouts_shows_no_layout_and_a_dark_surface():   # A37
    rig = Rig(layouts=())
    rig.engine.on_held(HeldUnit(_Conn()))
    rows = [sysex.parse_oled(f) for f in rig.gate.frames if sysex.parse_oled(f)]
    assert rows == [(0, "No layout"), (1, "")]
    leds = [f for f in rig.gate.frames if sysex.command_of(f).value == "channel_message" and f[0] & 0xF0 == 0x90]
    assert leds and all(f[2] == 0 for f in leds)


def test_the_last_selection_wins_and_unknown_layouts_are_refused():   # A142, s16.c3
    rig = Rig()
    assert rig.engine.select_page(2).nav.page == 2
    assert rig.engine.select_page(4).nav.page == 4
    assert rig.engine.snapshot().nav.page == 4
    assert rig.engine.load("tonnetz") == UnknownLayout("tonnetz", ("jam",))
    assert rig.engine.load("../etc") == UnknownLayout("../etc", ("jam",))
    with pytest.raises(Exception, match="pages are 1–8"):
        rig.engine.select_page(0)


def test_unit_bytes_from_two_reader_threads_are_handled_in_arrival_order():   # s46, a5
    rig = Rig()
    daw, notes = _Conn(), _Conn()
    rig.engine.on_held(HeldUnit(daw, notes))
    presses = [encode_input(Press(PadPos.from_index(i))) for i in range(16)]
    played = [encode(NoteOn(1, 40 + i, 50)) for i in range(16)]
    threads = [threading.Thread(target=lambda: [daw.on_bytes(b) for b in presses]),
               threading.Thread(target=lambda: [notes.on_bytes(b) for b in played])]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    pads = [m.note for p, m in rig.targets.sent if m.channel == 10]
    routed = [m.note for p, m in rig.targets.sent if m.channel == 2]
    assert pads == list(range(36, 52)) and routed == list(range(40, 56))


def test_a_return_to_session_view_redraws_every_host_led():   # s44, A101 engine side
    rig = Rig()
    daw = _Conn()
    rig.engine.on_held(HeldUnit(daw))
    daw.on_bytes(sysex.encode_view_report(UnitView.NOTE))
    rig.gate.frames.clear()
    daw.on_bytes(sysex.encode_view_report(UnitView.SESSION))
    assert encode_led(R1C1, LedState(RED, 1)) in rig.gate.frames   # bound pad at 25 %
    assert len([f for f in rig.gate.frames if f[0] & 0xF0 == 0x90 and f[1] < 64]) == 64


def test_the_oled_name_reverts_after_2_s():   # s52
    rig = Rig()
    rig.engine.on_held(HeldUnit(_Conn()))
    rig.clock.advance(2.0)
    rig.gate.frames.clear()
    rig.engine.select_page(2)
    assert [sysex.parse_oled(f) for f in rig.gate.frames if sysex.parse_oled(f)] == [(0, "Keys"), (1, "Page 2")]
    rig.gate.frames.clear()
    rig.clock.advance(2.0)
    assert [sysex.parse_oled(f) for f in rig.gate.frames if sysex.parse_oled(f)] == [(0, "Jam"),
                                                                                  (1, "P2 Keys | B1 M")]


def test_nav_and_strip_positions_are_persisted_and_restored_on_hold():   # s53, q6
    rig = Rig(layouts=(jam(), jam("amb", "Ambient")))
    assert rig.engine.nav.layout == "amb"   # nothing remembered: the first by name
    rig.engine.load("jam")
    rig.engine.select_page(2)
    rig.engine.replica_input(StripMove(Strip(1), 3000))
    assert rig.store.nav[0] == NavState("jam", 2, 1, False)
    rig.clock.advance(1.0)
    assert rig.store.nav[1] == {("jam", 1, Strip(1)): 3000}

    later = Rig(layouts=(), store=MemoryStore(nav=rig.store.nav))
    later.library.register(LayoutId("amb"), jam("amb", "Ambient"))
    later.library.register(LayoutId("jam"), jam())
    later.engine.on_held(HeldUnit(_Conn()))
    assert later.engine.nav == NavState("jam", 2, 1, False)
    assert later.engine.snapshot().positions[("jam", 1, Strip(1))] == 3000


def test_a_captured_touch_runs_no_binding_and_its_release_is_swallowed():   # s50, A132 engine side
    rig = Rig(learn=Learn(capture={TrackButton(1)}))
    rig.engine.replica_input(Press(TrackButton(1)))
    rig.engine.replica_input(Release(TrackButton(1)))
    rig.engine.replica_input(Press(SceneButton(2)))
    assert rig.targets.sent == [] and rig.engine.nav.page == 2
    assert rig.learn.seen == [TrackButton(1), SceneButton(2)]


def test_played_notes_are_shown_to_calibration_routed_and_aftertouch_folded():   # s51, q7, A102
    rig = Rig()
    notes = _Conn()
    rig.engine.on_held(HeldUnit(_Conn(), notes))
    notes.on_bytes(encode(NoteOn(1, 53, 56)))
    for pressure in (5, 10, 0):
        notes.on_bytes(encode(PolyAftertouch(1, 53, pressure)))
    notes.on_bytes(encode(NoteOff(1, 53)))
    assert [m for _, m in rig.targets.sent] == [NoteOn(2, 53, 56), PolyAftertouch(2, 53, 5),
                                               PolyAftertouch(2, 53, 10), PolyAftertouch(2, 53, 0), NoteOff(2, 53)]
    assert rig.calibration.observed[0][0].message == NoteOn(1, 53, 56)
    entries = rig.activity.recent()
    assert [e.subject for e in entries] == ["note 53", "note 53"] and entries[1].aftertouch == 0
    assert [e.kind for e in rig.watch.take() if e.note == 53] == ["note_on", "aftertouch", "aftertouch",
                                                                 "aftertouch", "note_off"]


def test_feedback_ports_are_listened_to_and_drive_leds():   # s45.c3, A77 engine side
    lay = jam(pages=[page(1, "Drums", {TrackButton(1): toggle_cc(20, device="bitwig",
                                                                 feedback=feedback("cc", 20, "bitwig"))})])
    rig = Rig(layouts=(lay,))
    rig.engine.on_held(HeldUnit(_Conn()))
    assert [s.port for s in rig.feedback.active()] == ["Bitwig Studio In"]
    rig.gate.frames.clear()
    rig.feedback.deliver("Bitwig Studio In", ControlChange(1, 20, 127))
    assert rig.gate.frames == [encode_led(TrackButton(1), LedState(lay.page(1).binding("base", TrackButton(1))
                                                                   .look_colour, 6))]
    assert rig.engine.snapshot().toggles == {TrackButton(1): True}


def test_a_swap_reloads_only_the_active_layout():   # s61
    rig = Rig(layouts=(jam(), jam("amb", "Ambient")))
    assert rig.engine.swap("jam", jam()) is False
    changed = jam("amb", "Ambient", pages=[page(1, "One", {R1C1: note(40)})])
    assert rig.engine.swap("amb", changed) is True
    rig.engine.replica_input(Press(R1C1))
    assert rig.targets.sent[-1] == (MPC_PORT, NoteOn(10, 40, 127))


def test_a_project_write_from_any_part_of_the_host_is_refused_and_listed():   # A31 (s44 → s56 → s47)
    rig = Rig(gate=OutboundGate(CONTRACT1_POLICY, wall=lambda: 1.0))
    rig.engine.send_to_unit([sysex.akai_frame(sysex.PROJECT_WRITE, b"\x00\x00\x01")], subject="lab")
    entry = rig.activity.recent()[0]
    assert (entry.subject, entry.result, entry.message) == ("lab", ActivityResult.REFUSED, "project write (0x14)")
    assert rig.gate.device_log()[-1].refusal_text() == "refused: project write (0x14)"


def test_a_fault_surfaces_from_run_and_the_engine_keeps_serving():   # s38.c3
    rig = Rig()

    async def scenario():
        task = asyncio.ensure_future(rig.engine.run())
        await asyncio.sleep(0)
        original = rig.engine._surface.handle
        rig.engine._surface.handle = lambda event: (_ for _ in ()).throw(RuntimeError("boom"))
        rig.engine.select_page(2)
        rig.engine._surface.handle = original
        rig.engine.replica_input(Press(R1C1))
        with pytest.raises(RuntimeError, match="boom"):
            await asyncio.wait_for(task, 1)

    run(scenario())
    assert rig.targets.sent == [(MPC_PORT, NoteOn(10, 36, 127))]


def test_released_gives_the_clear_frames_and_stops_reading_the_unit():   # s38.c2
    rig = Rig()
    daw = _Conn()
    rig.engine.on_held(HeldUnit(daw))
    frames = rig.engine.on_released()
    assert sysex.oled_frames(sysex.OledText.blank()) == tuple(frames[-2:])
    daw.on_bytes(encode_input(Press(R1C1)))
    assert rig.targets.sent == [] and not rig.engine.held


def test_subscribers_hear_about_changes():   # s69
    rig = Rig()
    calls = []
    rig.engine.subscribe(lambda: calls.append(rig.engine.snapshot().nav.page))
    rig.engine.select_page(2)
    assert calls[-1] == 2


def test_the_engine_drives_the_simulated_unit_end_to_end():   # A2 (engine part), A101, A128 spot check
    sim = SimulatedApc64()
    gate = OutboundGate(CONTRACT1_POLICY)
    rig = Rig(gate=gate)
    connection = sim.open("daw", sim.address("daw"))
    gate.attach(connection)
    rig.engine.on_held(HeldUnit(connection))
    assert sim.oled == {0: "Jam", 1: "Layout"} and sim.leds[(0x90, 0)] == RED.index
    sim.press(R1C1)
    sim.release(R1C1)
    sim.press(Shift())
    sim.view(UnitView.NOTE)
    sim.view(UnitView.SESSION)
    sim.release(Shift())
    assert rig.targets.sent[:2] == [(MPC_PORT, NoteOn(10, 36, 127)), (MPC_PORT, NoteOff(10, 36))]
    frame = rig.engine.snapshot().frame
    for control, state in frame.leds.items():   # every LED the replica shows is what the unit was told
        assert sim.leds[(0x90, NOTE_OF[control])] == encode_led(control, state)[2], control
    assert sim.hazards == []


class _Conn:
    """A held connection double: the engine listens; the test pushes bytes from any thread."""

    def __init__(self):
        self.on_bytes = self.on_gone = None

    def listen(self, on_bytes, on_gone):
        self.on_bytes, self.on_gone = on_bytes, on_gone

    def close(self):
        pass
