"""Contract 2 T14: engine module dispatch (s1, s2, s20, s21, s37, s40 suppliers; s11 collaboration).

The real engine with a recording test module: ModuleAction bindings on the base-layer encoder and Tempo, the
Shift + encoder browser untouched, the single load point, pad-mode reports, led_filter, ModuleDisplay and
NoteEnder. Unit input is fed as the recorded wire bytes (fixtures/daw-mode-buttons-in-note-and-custom-view-
2026-10-23.log: B0 5A 01/7F/03, 90 48, 19 00 01 09/02/08, Custom 90 18 26 and A0 aftertouch).
Rows: A32, A33, A34, A35, A40, A41 (engine side)."""
from _apc64_host.application.conftest import RecordingConnection
from _apc64_host.application.engine import EngineOk, HeldUnit
from _apc64_host.application.modules import collect
from _apc64_host.application.ports import HostModuleBase, LayoutLoader, ModuleDisplay, NoteEnder, NotePlayer
from _apc64_host.application.test_engine import MPC_PORT, GateDouble, Rig, jam
from _apc64_host.domain.conftest import encoder_cc, layout, note, page
from _apc64_host.domain.controls import (
    Encoder, EncoderPress, FunctionButton, FunctionName, PadPos, Shift,
)
from _apc64_host.domain.effects import (
    ENDED_BY_WINDOW_SHIFT, NOTE_ENDED, ActivityResult, EncoderTurn, Led, PlaySourceKind, Press, Release, UnitView,
)
from _apc64_host.domain.layout import (
    AftertouchPolicy, Binding, ControlEvent, LayoutId, ModuleAction, RoutingRule, UnitPortRole,
)
from _apc64_host.domain.midi import ControlChange, NoteOff, NoteOn, PolyAftertouch
from _apc64_host.domain.oled import OledText
from _apc64_host.domain.unit_status import ReleaseReason
from _apc64_host.protocol import sysex
from _apc64_host.protocol.surface_map import encode_input

TEMPO = FunctionButton(FunctionName.TEMPO)
SHIFT_DOWN, SHIFT_UP = encode_input(Press(Shift())), encode_input(Release(Shift()))
TEMPO_DOWN, TEMPO_UP = bytes.fromhex("90 48 7F"), bytes.fromhex("80 48 00")
CUSTOM_VIEW = bytes.fromhex("F0 47 00 53 19 00 01 09 F7")


def custom_rule():
    return RoutingRule(UnitPortRole.CUSTOM, "mpc", 1, aftertouch=AftertouchPolicy.PASS)


def tonnetz(id="tonnetz-c", name="Tonnetz C"):
    """A generated layout as the 'lab:' section compiles it: implied base-layer encoder and Tempo actions."""
    implied = {Encoder(): Binding((), label="window shift", module_action=ModuleAction("lab", "window_shift")),
               TEMPO: Binding((), label="interval", module_action=ModuleAction("lab", "interval_cycle"))}
    return layout(id, name, pages=[page(1, "Lab", implied)], routing=[custom_rule()])


def jam_with_encoder():
    """'Jam': the encoder bound to CC 30 to mpc (A34), and Custom-view notes routed to mpc ch 1 (A40)."""
    return layout("jam", "Jam", pages=[page(1, "Drums", {PadPos(1, 1): note(36), Encoder(): encoder_cc(30)})],
                  routing=[custom_rule()])


class Lab(HostModuleBase):
    """A recording module: its actions and hooks, and calls back into the engine from inside a hook."""
    name = "lab"

    def __init__(self, suppress_pads=False, on_loaded=None):
        self.calls, self.events = [], []
        self.suppress_pads, self._on_loaded = suppress_pads, on_loaded

    def actions(self):
        return {"window_shift": lambda e: self.events.append(("window_shift", e)),
                "interval_cycle": lambda e: self.events.append(("interval_cycle", e))}

    def on_held(self, unit):
        self.calls.append(("on_held", unit.identity))

    def on_layout_loaded(self, layout, section):
        self.calls.append(("on_layout_loaded", layout.id if layout else None))
        if self._on_loaded:
            self._on_loaded(layout)

    def on_pad_mode(self, view):
        self.calls.append(("on_pad_mode", view))

    def led_filter(self, led):
        return None if self.suppress_pads and isinstance(led.control, PadPos) else led


class LabRig(Rig):
    def __init__(self, layouts=None, module=None, **kw):
        self.module = module or Lab()
        self._collection = collect([self.module])
        super().__init__(layouts=(), **kw)
        self.engine._modules, self.engine._hooks = self._collection, self._collection.hooks   # as constructed
        for lay in layouts if layouts is not None else (jam_with_encoder(), tonnetz()):
            self.library.register(lay.id, lay)
        self.engine.start()

    def hold(self, identity="identity 1.2.1.6"):
        self.daw, self.custom = RecordingConnection(), RecordingConnection()
        self.gate.attached = True
        self.engine.on_held(HeldUnit(self.daw, None, self.custom, identity=identity))

    def unit(self, data):
        self.daw.on_bytes(bytes(data))

    def custom_port(self, data):
        self.custom.on_bytes(bytes(data))


def rig_on_tonnetz(**kw):
    rig = LabRig(**kw)
    rig.hold()
    rig.engine.load("tonnetz-c")
    rig.module.calls.clear()
    return rig


def test_the_engine_is_constructed_with_the_modules():
    from _apc64_host.application.engine import HostEngine
    rig = Rig()
    collection = collect([Lab()])
    engine = HostEngine(gate=rig.gate, targets=rig.targets, feedback=rig.feedback, activity=rig.activity,
                        stream=rig.stream, library=rig.library, learn=rig.learn, calibration=rig.calibration,
                        clock=rig.clock, store=rig.store, modules=collection)
    assert engine._modules is collection
    for protocol in (ModuleDisplay, NoteEnder, LayoutLoader, NotePlayer):
        assert isinstance(engine, protocol)


# --- ModuleAction bindings (s2.c7, s1.c1, s1.c2) ---------------------------------------------------------------
def test_a32_a_single_encoder_message_worth_3_steps_calls_the_action_with_plus_3():
    rig = rig_on_tonnetz()
    rig.unit(bytes.fromhex("B0 5A 03"))
    rig.unit(bytes.fromhex("B0 5A 7F"))
    assert rig.module.events == [("window_shift", ControlEvent(3, False)), ("window_shift", ControlEvent(-1, False))]
    assert rig.targets.sent == []                                  # a module action sends no MIDI
    assert "encoder → lab.window_shift +3 → lab: sent" in rig.texts()


def test_tempo_press_calls_the_interval_action_and_its_release_does_nothing():
    rig = rig_on_tonnetz()
    rig.unit(TEMPO_DOWN)
    rig.unit(TEMPO_UP)
    assert rig.module.events == [("interval_cycle", ControlEvent(0, True))]


def test_a33_shift_plus_encoder_browses_host_layouts_and_never_calls_the_action():
    rig = rig_on_tonnetz()
    rig.unit(SHIFT_DOWN)
    rig.unit(bytes.fromhex("B0 5A 01"))
    assert rig.engine.snapshot().oled.row0 == "Jam"                # the host's layout browser
    assert rig.module.events == []
    rig.unit(encode_input(Press(EncoderPress())))                  # Shift + encoder press loads 'Jam'
    assert rig.engine.layout.id == "jam" and ("on_layout_loaded", "jam") in rig.module.calls


def test_a35_shift_plus_tempo_with_no_shift_binding_does_nothing():
    rig = rig_on_tonnetz()
    rig.unit(SHIFT_DOWN)
    rig.unit(TEMPO_DOWN)
    rig.unit(TEMPO_UP)
    rig.unit(SHIFT_UP)
    assert rig.module.events == [] and rig.targets.sent == []


def test_a34_a_host_layout_binding_the_encoder_to_cc_30_is_unchanged():
    rig = LabRig()
    rig.hold()
    rig.engine.load("jam")
    rig.unit(bytes.fromhex("B0 5A 01"))
    assert rig.targets.sent == [(MPC_PORT, ControlChange(1, 30, 65))]
    assert rig.module.events == []
    assert rig.texts()[-1] == "encoder → CC 30 = 65 ch 1 → MPC Live III MIDI 1: sent"   # contract 1's line


def test_s40_the_replica_encoder_and_tempo_dispatch_like_the_unit():
    # A37 (engine side): POST /api/control/encoder/move {value: 1} and tempo/press reach the same path
    rig = rig_on_tonnetz()
    assert rig.engine.replica_input(EncoderTurn(1)) == EngineOk(rig.engine.nav)
    rig.engine.replica_input(Press(TEMPO))
    rig.engine.replica_input(Release(TEMPO))
    assert rig.module.events == [("window_shift", ControlEvent(1, False)), ("interval_cycle", ControlEvent(0, True))]


def test_a_failing_module_action_is_listed_and_never_faults_the_engine():
    rig = rig_on_tonnetz()

    def broken(event):
        raise RuntimeError("lab bug")
    rig.engine._modules.actions[ModuleAction("lab", "window_shift")] = broken
    rig.unit(bytes.fromhex("B0 5A 01"))
    assert "encoder → lab.window_shift +1 → lab: not sent, module action failed" in rig.texts()
    rig.unit(TEMPO_DOWN)
    assert rig.module.events == [("interval_cycle", ControlEvent(0, True))]


def test_module_action_bindings_label_as_the_module_says():
    rig = rig_on_tonnetz()
    from _apc64_host.domain.resolver import binding_detail, resolve
    meaning = resolve(rig.engine.layout, rig.engine.nav)
    assert meaning.controls[Encoder()].label == "window shift" and meaning.controls[TEMPO].label == "interval"
    assert binding_detail(rig.engine.layout.page(1).encoder) == "lab.window_shift (module action), momentary"


# --- Custom-view notes (s1.c4, s21) ------------------------------------------------------------------------------
def test_a40_a_custom_pad_at_velocity_38_then_aftertouch_reaches_mpc_unchanged():
    rig = rig_on_tonnetz()
    rig.custom_port(bytes.fromhex("90 30 26"))
    rig.custom_port(bytes.fromhex("A0 30 46"))
    assert rig.targets.sent == [(MPC_PORT, NoteOn(1, 48, 38)), (MPC_PORT, PolyAftertouch(1, 48, 70))]
    played = [e for e in rig.watch.take() if e.kind in ("note_on", "aftertouch")]
    assert [(e.kind, e.port.kind) for e in played] == [("note_on", PlaySourceKind.CUSTOM),
                                                      ("aftertouch", PlaySourceKind.CUSTOM)]


def test_a41_end_notes_sends_one_note_off_publishes_the_ended_event_and_absorbs_the_release():
    rig = rig_on_tonnetz()
    rig.custom_port(bytes.fromhex("90 30 26"))
    rig.watch.take()
    rig.engine.end_notes([48])
    assert rig.targets.sent[-1] == (MPC_PORT, NoteOff(1, 48))
    ended = rig.watch.take()
    assert [(e.kind, e.note, e.reason, e.port.kind) for e in ended] == [
        (NOTE_ENDED, 48, ENDED_BY_WINDOW_SHIFT, PlaySourceKind.CUSTOM)]
    assert rig.engine.snapshot().played == ()                       # the views clear 48
    rig.custom_port(bytes.fromhex("A0 30 50"))                     # still pressed after the shift
    rig.custom_port(bytes.fromhex("80 30 00"))                     # … then released
    assert [m for _, m in rig.targets.sent].count(NoteOff(1, 48)) == 1
    assert rig.watch.take() == []
    rig.custom_port(bytes.fromhex("90 30 40"))                     # the next press plays normally again
    rig.custom_port(bytes.fromhex("80 30 00"))
    assert rig.targets.sent[-2:] == [(MPC_PORT, NoteOn(1, 48, 64)), (MPC_PORT, NoteOff(1, 48))]


def test_two_pads_on_the_same_note_are_both_ended_and_both_releases_absorbed():
    # A80 with a shift: two note-ons of 41 are two held notes
    rig = rig_on_tonnetz()
    rig.custom_port(bytes.fromhex("90 29 40 90 29 41"))
    rig.engine.end_notes([41, 99])                                 # 99 is not held: nothing for it
    assert [m for _, m in rig.targets.sent].count(NoteOff(1, 41)) == 2
    rig.custom_port(bytes.fromhex("80 29 00 80 29 00"))
    assert [m for _, m in rig.targets.sent].count(NoteOff(1, 41)) == 2


# --- hooks: held, the single load point, pad mode, LEDs (s2.c6, s2.c8, s37) --------------------------------------
def test_on_held_is_called_once_per_take_with_the_identity():
    rig = LabRig()
    rig.hold("identity A")
    rig.engine.on_released()
    rig.hold("identity B")
    assert [c for c in rig.module.calls if c[0] == "on_held"] == [("on_held", "identity A"), ("on_held", "identity B")]


def test_on_layout_loaded_fires_from_the_single_load_point_for_every_load_path():
    rig = LabRig()                                                 # start: the first layout by name goes live
    assert rig.module.calls == [("on_layout_loaded", "jam")]
    rig.hold()
    rig.engine.load("tonnetz-c")                                   # the API, the page and the CLI
    rig.engine.swap("tonnetz-c", tonnetz(name="Tonnetz C v2"))     # hot reload of the active layout (s37)
    rig.unit(SHIFT_DOWN)                                           # the Shift + encoder browser
    rig.unit(bytes.fromhex("B0 5A 7F"))
    rig.unit(encode_input(Press(EncoderPress())))
    rig.unit(SHIFT_UP)
    loads = [c[1] for c in rig.module.calls if c[0] == "on_layout_loaded"]
    assert loads == ["jam", "tonnetz-c", "tonnetz-c", "jam"]
    assert rig.engine.swap("tonnetz-c", tonnetz()) is False        # not active: no reload, no hook


def test_every_pad_mode_report_reaches_on_pad_mode():
    rig = rig_on_tonnetz()
    for code in ("09", "02", "08", "09"):
        rig.unit(bytes.fromhex(f"F0 47 00 53 19 00 01 {code} F7"))
    assert [c[1] for c in rig.module.calls if c[0] == "on_pad_mode"] == [
        UnitView.CUSTOM, UnitView.NOTE, UnitView.PROJECT, UnitView.CUSTOM]


def test_a_none_from_led_filter_suppresses_that_led_frame_only():
    rig = LabRig(module=Lab(suppress_pads=True))
    rig.hold()
    rig.gate.frames.clear()
    rig.engine.load("jam")                                         # Session view: pad r1c1 would be drawn
    pad_frames = [f for f in rig.gate.frames if f[0] & 0xF0 == 0x90 and f[1] < 64]
    assert pad_frames == []
    assert any(sysex.command_of(f).value == "oled_text" for f in rig.gate.frames)


def test_without_modules_the_led_frames_are_as_before():
    plain = Rig(layouts=(jam_with_encoder(),))
    plain.gate.attached = True
    plain.engine.on_held(HeldUnit(RecordingConnection()))
    assert any(f[0] & 0xF0 == 0x90 and f[1] < 64 for f in plain.gate.frames)


# --- ModuleDisplay (s2.c3, s2.c8) ---------------------------------------------------------------------------------
def test_the_resting_text_shows_whenever_no_host_transient_is_on_screen():
    rig = rig_on_tonnetz()
    rig.clock.advance(3)                                           # the 'Tonnetz C / Layout' name has gone
    rig.engine.set_resting_oled(OledText("Tonnetz C", "5th +1"))
    assert rig.engine.snapshot().oled.rows == ("Tonnetz C", "5th +1")
    rig.unit(SHIFT_DOWN)
    rig.unit(bytes.fromhex("B0 5A 01"))                            # the browser is a host transient …
    assert rig.engine.snapshot().oled.row0 == "Jam"
    rig.unit(SHIFT_UP)                                             # … letting go of Shift cancels it
    assert rig.engine.snapshot().oled.rows == ("Tonnetz C", "5th +1")
    rig.engine.set_resting_oled(None)
    assert rig.engine.snapshot().oled.row0 == "Tonnetz C" and rig.engine.snapshot().oled.row1 != "5th +1"


def test_a_warning_shows_on_the_banner_state_and_the_oled():
    rig = rig_on_tonnetz()
    rig.engine.warn("write to slot 7 failed, restored from backup")
    snapshot = rig.engine.snapshot()
    assert snapshot.warnings == ("write to slot 7 failed, restored from backup",)
    assert snapshot.oled.rows == ("write to slot", "7 failed, rest")
    rig.engine.warn("write to slot 7 failed, restored from backup")      # the same warning once
    assert len(rig.engine.snapshot().warnings) == 1
    rig.engine.warn(None)
    assert rig.engine.snapshot().warnings == ()


def test_calls_made_from_inside_a_hook_run_after_the_current_input():
    seen = []
    holder = {}

    def loaded(layout):
        holder["engine"].set_resting_oled(OledText(layout.display_name, "Oct +0"))
        seen.append(holder["engine"].snapshot().oled.row1)        # not yet applied: queued behind the load
    rig = LabRig(module=Lab(on_loaded=loaded), layouts=())
    holder["engine"] = rig.engine
    rig.library.register(LayoutId("tonnetz-c"), tonnetz())         # goes live at once (the only layout)
    assert seen == ["Layout"]
    rig.clock.advance(3)
    assert rig.engine.snapshot().oled.rows == ("Tonnetz C", "Oct +0")


def test_play_events_carry_their_source():
    rig = rig_on_tonnetz()
    rig.watch.take()
    rig.unit(bytes.fromhex("B0 5A 01"))
    rig.custom_port(bytes.fromhex("90 30 26"))
    events = rig.watch.take()
    assert [(e.kind, e.port.kind) for e in events] == [("turn", PlaySourceKind.SESSION_BINDING),
                                                      ("note_on", PlaySourceKind.CUSTOM)]
    assert events[0].reason == "module lab.window_shift"


def test_a_released_unit_stops_led_output_and_release_reason_reaches_no_engine_hook():
    rig = rig_on_tonnetz()
    frames = rig.engine.on_released()
    assert frames and not rig.engine.held
    assert not any(c[0] == "on_release" for c in rig.module.calls)   # the session calls on_release (T15)
    assert ReleaseReason.UNPLUG  # the reasons the session passes


# --- the performer's seams (contract 2 §2.10): take_played and NotePlayer.perform ------------------------------
class Taker(Lab):
    """Takes every Custom-port note and aftertouch, and plays its own notes back through perform()."""

    def __init__(self):
        super().__init__()
        self.taken = []

    def take_played(self, played):
        if played.role is not UnitPortRole.CUSTOM or isinstance(played.message, ControlChange):
            return None
        self.taken.append(played.message)
        return "played by the performer"


def test_a_taken_note_is_not_routed_but_its_held_event_is_published():
    rig = rig_on_tonnetz(module=Taker())
    rig.watch.take()
    rig.custom_port(bytes.fromhex("92 30 26 A2 30 46 82 30 00 B0 10 40"))   # string 3 (channel 3), then a strip CC
    assert rig.module.taken == [NoteOn(3, 48, 38), PolyAftertouch(3, 48, 70), NoteOff(3, 48, 0)]
    assert rig.targets.sent == [(MPC_PORT, ControlChange(1, 16, 64))]        # only the CC is routed
    events = [e for e in rig.watch.take() if e.kind in ("note_on", "aftertouch", "note_off")]
    assert [(e.kind, e.note, e.channel, e.reason, e.sent, e.port.kind, e.port.played) for e in events] == [
        ("note_on", 48, 3, "played by the performer", (), PlaySourceKind.CUSTOM, True),
        ("aftertouch", 48, 3, "played by the performer", (), PlaySourceKind.CUSTOM, True),
        ("note_off", 48, 3, "played by the performer", (), PlaySourceKind.CUSTOM, True)]


def test_perform_routes_like_the_unit_with_the_performer_source():
    rig = rig_on_tonnetz(module=Taker())
    rig.watch.take()
    rig.engine.perform([NoteOn(5, 45, 90), NoteOn(1, 64, 100)])
    rig.engine.perform([NoteOff(5, 45)])
    assert rig.targets.sent == [(MPC_PORT, NoteOn(1, 45, 90)), (MPC_PORT, NoteOn(1, 64, 100)),
                                (MPC_PORT, NoteOff(1, 45))]              # the rule's channel, as for a pad
    events = rig.watch.take()
    assert [(e.kind, e.note, e.channel, e.port.kind, e.port.played) for e in events] == [
        ("note_on", 45, 5, PlaySourceKind.PERFORMER, False), ("note_on", 64, 1, PlaySourceKind.PERFORMER, False),
        ("note_off", 45, 5, PlaySourceKind.PERFORMER, False)]
    assert [(p.note, p.velocity) for p in rig.engine.snapshot().played] == [(64, 100)]   # the played-notes row


def test_a_window_shift_ends_performed_notes_and_absorbs_their_later_note_off():
    rig = rig_on_tonnetz(module=Taker())
    rig.engine.perform([NoteOn(2, 60, 90)])
    rig.engine.end_notes([60])
    rig.engine.perform([NoteOff(2, 60)])                                  # the performer's own off: absorbed
    assert [m for _, m in rig.targets.sent] == [NoteOn(1, 60, 90), NoteOff(1, 60)]


def test_without_a_taker_custom_notes_route_as_before():
    rig = rig_on_tonnetz()
    rig.custom_port(bytes.fromhex("92 30 26"))
    assert rig.targets.sent == [(MPC_PORT, NoteOn(1, 48, 38))]


def test_a_failing_take_played_leaves_the_note_to_the_router():
    class Broken(Lab):
        def take_played(self, played):
            raise RuntimeError("boom")
    rig = rig_on_tonnetz(module=Broken())
    rig.custom_port(bytes.fromhex("90 30 26"))
    assert rig.targets.sent == [(MPC_PORT, NoteOn(1, 48, 38))]
