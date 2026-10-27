from datetime import datetime

from _apc64_host.application.activity import ActivityLog
from _apc64_host.application.calibration import CalibrationService
from _apc64_host.application.conftest import ManualClock, MemoryStore, RecordingFeedback, RecordingTargets
from _apc64_host.application.engine import HeldUnit, HostEngine
from _apc64_host.application.learn import LearnKind, LearnStatus
from _apc64_host.application.library import LayoutLibrary
from _apc64_host.application.outbound_gate import OutboundGate
from _apc64_host.application.play_stream import PlayStream
from _apc64_host.application.state_view import StateDiff, StateSnapshot, StateView, UnknownControl
from _apc64_host.domain.calibration import Calibration
from _apc64_host.domain.conftest import RED, bank, layout, mix_strips, note, page, toggle_cc
from _apc64_host.domain.controls import PadPos, Shift, Strip, TrackButton
from _apc64_host.domain.effects import Press
from _apc64_host.domain.issues import LayoutIssue, Severity, SourceRef
from _apc64_host.domain.layout import LayoutId, UnitPortRole
from _apc64_host.domain.leds import LedBehaviour
from _apc64_host.domain.midi import NoteOn
from _apc64_host.domain.outbound import CONTRACT1_POLICY
from _apc64_host.domain.unit_status import Asking, Busy, ConsentSource, Held, Holder
from _apc64_host.protocol.midi_codec import encode

R1C1 = PadPos(1, 1)
AT = datetime(2026, 10, 23, 14, 2)


def jam(routing=()):
    return layout(pages=[page(1, "Drums", {R1C1: note(36, colour=RED), TrackButton(1): toggle_cc(20)},
                              {R1C1: note(48)}),
                         page(2, "Keys", {R1C1: note(50)})],
                  banks=[bank(1, "Mix", mix_strips())], routing=routing)


class Session:
    def __init__(self, status=Asking(), firmware=None):
        self._status, self.firmware, self.callbacks = status, firmware, []

    def status(self):
        return self._status

    def subscribe(self, callback):
        self.callbacks.append(callback)

    def set(self, status):
        self._status = status
        for callback in self.callbacks:
            callback(status)


class Learn:
    def __init__(self, status=LearnStatus()):
        self._status, self.callbacks = status, []

    def status(self):
        return self._status

    def subscribe(self, callback):
        self.callbacks.append(callback)

    def set(self, status):
        self._status = status
        for callback in self.callbacks:
            callback(status)

    def intercept(self, control):
        return "pass"


class Rig:
    def __init__(self, lay=None, session=None, calibration=None):
        self.library = LayoutLibrary()
        self.library.register(LayoutId("jam"), lay or jam())
        self.learn = Learn()
        self.session = session or Session()
        self.calibration = CalibrationService(MemoryStore(calibration=calibration), now=lambda: AT)
        clock = ManualClock()
        self.engine = HostEngine(gate=OutboundGate(CONTRACT1_POLICY), targets=RecordingTargets(),
                                 feedback=RecordingFeedback(), activity=ActivityLog(), stream=PlayStream(clock),
                                 library=self.library, learn=self.learn, calibration=self.calibration,
                                 clock=clock, store=MemoryStore())
        self.engine.start()
        self.view = StateView(engine=self.engine, session=self.session, library=self.library,
                              calibration=self.calibration, learn=self.learn)


def test_the_snapshot_carries_nav_labels_leds_status_issues_learn_and_calibration():
    rig = Rig()
    rig.library.set_issues(LayoutId("broken"), [LayoutIssue(Severity.ERROR, SourceRef("broken.yaml", 7), None,
                                                            "unknown device mcp", "declared devices: mpc")])
    state = rig.view.snapshot()
    assert (state.layout, state.layout_name, state.page.number, state.page.display, state.bank.display) == (
        "jam", "Jam", 1, "Drums", "Mix")
    r1c1 = state.controls[R1C1]
    assert (r1c1.label_base, r1c1.label_shift, r1c1.empty, r1c1.toggle) == ("Note 36 → mpc", "Note 48 → mpc",
                                                                            False, None)
    assert r1c1.led.colour == RED and r1c1.led.behaviour is LedBehaviour.BRIGHT_25
    assert state.controls[PadPos(8, 8)].empty and state.controls[PadPos(8, 8)].label_base == ""   # inv2
    assert state.controls[TrackButton(1)].toggle is False
    assert state.controls[Strip(1)].bar is not None
    assert state.unit.text == "Take control of APC64?" and state.unit.status == "asking"
    assert [e.message() for e in state.errors] == ["broken.yaml line 7: unknown device mcp; declared devices: mpc"]
    assert state.oled == ("Jam", "Layout")
    assert state.calibration is None and state.calibration_label == "pad position unknown"
    assert state.routing.text == "expressive pads not routed in this layout"
    assert [s.display for s in state.pages][:3] == ["Drums", "Keys", ""]


def test_shift_held_in_the_page_swaps_the_current_layer():   # A88 state side
    rig = Rig()
    rig.engine.set_page_shift(True)
    state = rig.view.snapshot()
    assert state.shift and state.controls[R1C1].empty is False and state.controls[TrackButton(1)].empty


def test_the_card_shows_both_layers_ports_and_elsewhere_in_one_step():   # A129
    rig = Rig()
    view = rig.view.card("pad r1c1")
    assert view.lines[:2] == ("Base: Note 36 → mpc ch 10, momentary", "Shift: Note 48 → mpc ch 10, momentary")
    assert "mpc connected" in view.lines and "Page 2: Note 50" in view.lines
    assert rig.view.card(TrackButton(1)).lines[2] == "toggle off"
    assert isinstance(rig.view.card("pad r9c1"), UnknownControl)


def test_subscribers_get_the_snapshot_then_only_diffs():   # s26
    rig = Rig()
    seen = []
    rig.view.subscribe(seen.append)
    assert isinstance(seen[0], StateSnapshot)
    rig.engine.select_page(2)
    diff = seen[-1]
    assert isinstance(diff, StateDiff) and diff.changed["page"].number == 2
    assert diff.controls[R1C1].label_base == "Note 50 → mpc" and TrackButton(2) not in diff.controls
    count = len(seen)
    rig.engine.select_page(2)
    assert len(seen) == count   # nothing changed: no diff
    rig.session.set(Busy(holder=Holder("Bitwig Studio")))
    assert seen[-1].changed["unit"].text == "Busy: held by Bitwig Studio" and seen[-1].controls == {}


def test_unit_status_comes_from_the_session():   # s70, A19, A22 state side
    rig = Rig(session=Session(Held(by=ConsentSource.AGENT, firmware_warning="untested firmware 1.2.2.0"),
                              firmware="1.2.2.0"))
    unit = rig.view.snapshot().unit
    assert (unit.text, unit.taken_by, unit.firmware, unit.warnings) == (
        "Held (taken by command-line tool)", "agent", "1.2.2.0", ("untested firmware 1.2.2.0",))
    assert rig.view.snapshot().warnings[0] == "untested firmware 1.2.2.0"


def test_learn_selection_shows_on_its_control():   # s90
    rig = Rig()
    seen = []
    rig.view.subscribe(seen.append)
    rig.learn.set(LearnStatus(LearnKind.TOUCH, TrackButton(3)))
    assert seen[-1].controls[TrackButton(3)].selected and seen[-1].changed["learn"].selected == TrackButton(3)


def test_played_notes_carry_their_position_or_say_unknown():   # A115, A121, A122, s72
    for calibration, pad, position in [(None, None, "pad position unknown"),
                                       (Calibration(AT, 36, 99), PadPos(3, 2), "calibrated 14:02 (assumed)")]:
        rig = Rig(calibration=calibration)
        notes = _Conn()
        rig.engine.on_held(HeldUnit(_Conn(), notes))
        notes.on_bytes(encode(NoteOn(1, 53, 56)))
        [played] = rig.view.snapshot().played
        assert (played.label, played.velocity, played.routed, played.pad, played.position) == (
            "F2 (53)", 56, False, pad, position)
        assert rig.view.snapshot().calibration_label == (position if calibration else "pad position unknown")


def test_a_deleted_active_file_is_flagged():   # A56 state side
    rig = Rig()
    rig.library.mark_deleted(LayoutId("jam"))
    state = rig.view.snapshot()
    assert state.file_deleted and state.layout == "jam"


def test_overview_and_surface_catalog():
    rig = Rig()
    overview = rig.view.overview()
    assert overview.page == 1 and overview.overview.pages[1].base[R1C1].label == "Note 50 → mpc"
    surface = rig.view.surface()
    assert len(surface.controls) > 64 and surface.approximate and "approximate" in surface.palette_note
    assert any(e.id == Shift() for e in surface.controls)


class _Conn:
    def __init__(self):
        self.on_bytes = None

    def listen(self, on_bytes, on_gone):
        self.on_bytes = on_bytes

    def close(self):
        pass
