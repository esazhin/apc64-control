"""DeviceSession against the consent and release rows of contract §4.2 (A1–A30, A114), over the simulated APC64."""
import asyncio

import pytest

from _apc64_host.application.activity import ActivityLog
from _apc64_host.application.conftest import ManualClock, MemoryStore, RecordingFeedback, RecordingTargets
from _apc64_host.application.engine import HostEngine
from _apc64_host.application.library import LayoutLibrary
from _apc64_host.application.outbound_gate import GateResult, OutboundGate
from _apc64_host.application.play_stream import PlayStream
from _apc64_host.application.ports import ConsentAnswer, PortGone
from _apc64_host.application.session import ASK_TEXT, DeviceSession, ReleaseResult, TakeAnswer, TakeResult
from _apc64_host.domain.conftest import RED, layout, note, notes_rule, page
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.layout import LayoutId, UnitPortRole
from _apc64_host.domain.midi import NoteOff, NoteOn
from _apc64_host.domain.outbound import CONTRACT1_POLICY, SysexCommand
from _apc64_host.domain.unit_status import ConsentSource, Holder, ReleaseReason, UnitPresence
from _apc64_host.infrastructure.simulated_apc64 import SimulatedApc64
from _apc64_host.protocol import sysex
from _apc64_host.protocol.surface_map import clear_frames

DAW, NOTES, CUSTOM = UnitPortRole.DAW, UnitPortRole.NOTES, UnitPortRole.CUSTOM
BANNER, NOTIFICATION, AGENT = ConsentSource.BANNER, ConsentSource.NOTIFICATION, ConsentSource.AGENT


class Prompt:
    """ConsentPrompt double: each ask waits until the test clicks Take or something withdraws it."""

    def __init__(self):
        self.asks, self.withdrawn, self.pending = [], 0, None

    async def ask(self, text):
        self.asks.append(text)
        self.pending = asyncio.get_running_loop().create_future()
        return await self.pending

    def withdraw(self):
        self.withdrawn += 1
        if self.pending is not None and not self.pending.done():
            self.pending.set_result(ConsentAnswer.DISMISSED)

    def click_take(self):
        self.pending.set_result(ConsentAnswer.TAKE)


class Engine:
    """Engine double: records the lifecycle, listens to the held connections, can fail its run()."""

    def __init__(self):
        self.calls, self.unit, self.run_future = [], None, None

    def on_held(self, unit):
        self.calls.append("held")
        self.unit = unit
        unit.daw.listen(lambda chunk: None, lambda: self.calls.append("daw gone"))

    def on_released(self):
        self.calls.append("released")
        return clear_frames()

    async def run(self):
        self.run_future = asyncio.get_running_loop().create_future()
        await self.run_future

    def crash(self):
        self.run_future.set_exception(RuntimeError("engine bug"))


class Rig:
    def __init__(self, sim=None, store=None, auto_accept=False, engine=None, gate=None, locator=None):
        self.sim = sim if sim is not None else SimulatedApc64()
        self.clock = ManualClock()
        self.prompt = Prompt()
        self.store = store or MemoryStore()
        self.gate = gate or OutboundGate(CONTRACT1_POLICY)
        self.engine = engine or Engine()
        self.session = DeviceSession(locator=locator or self.sim, holders=self.sim.holder_lookup, port=self.sim,
                                     prompt=self.prompt, store=self.store, gate=self.gate, engine=self.engine,
                                     clock=self.clock, auto_accept=auto_accept)
        self.statuses = []
        self.session.subscribe(self.statuses.append)

    @property
    def text(self):
        return self.session.status().text


def scenario(test):
    """Runs an async test body with the rig on a fresh loop."""
    def wrapper(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    wrapper.__name__ = test.__name__
    return wrapper


async def settle():
    for _ in range(10):
        await asyncio.sleep(0)


def daw_mode_frames(sim):
    return sim.frames(SysexCommand.DAW_MODE)


# --- appearing and asking -------------------------------------------------------------------------------------
@scenario
async def test_a_unit_that_appears_is_asked_about_and_left_untouched():   # A1, A23 (card moved)
    rig = Rig(sim=SimulatedApc64(card=4, present=False))
    rig.session.start()
    assert rig.session.status().status == "absent" and rig.text == "APC64 not connected"
    rig.sim.plug(card=5)
    await settle()
    assert rig.text == ASK_TEXT and rig.prompt.asks == [ASK_TEXT]
    assert rig.sim.written == [] and not rig.sim.daw_mode and rig.sim.opened == []


@scenario
async def test_yes_in_the_banner_identifies_and_enters_daw_mode():   # A2 (session side), A21
    rig = Rig()
    rig.session.start()
    answer = await rig.session.take(BANNER)
    assert answer == TakeAnswer(TakeResult.TAKEN, BANNER)
    assert rig.sim.daw_mode and rig.text == "Held" and rig.session.firmware == "1.2.1.6"
    assert rig.sim.commands[:4] == [SysexCommand.DRUM_FLAG, SysexCommand.PAD_MODE, SysexCommand.IDENTITY_REQUEST,
                                    SysexCommand.DAW_MODE]
    assert rig.engine.calls == ["held"] and rig.store.marker
    assert sorted(r for r, _ in rig.sim.opened) == sorted([DAW, NOTES, CUSTOM])
    assert rig.prompt.withdrawn >= 1
    lan = Rig()
    lan.session.start()
    await lan.session.take(ConsentSource.LAN_BROWSER)
    assert lan.text == "Held"


@scenario
async def test_take_in_the_desktop_notification_holds_the_unit():   # A3, s35
    rig = Rig()
    rig.session.start()
    await settle()
    rig.prompt.click_take()
    await settle()
    assert rig.sim.daw_mode and rig.session.status().by is NOTIFICATION and rig.text == "Held"


@scenario
async def test_no_leaves_the_port_free_and_bitwig_can_take_it():   # A4
    rig = Rig()
    rig.session.start()
    await settle()
    assert rig.session.decline() == "ok"
    rig.sim.hold(DAW, "Bitwig Studio")
    await settle()
    assert rig.text == "Not held" and rig.sim.written == [] and rig.sim.opened == []


@scenario
async def test_auto_accept_takes_the_unit_on_plug_in():   # A5
    rig = Rig(sim=SimulatedApc64(present=False), auto_accept=True)
    rig.session.start()
    rig.sim.plug()
    await settle()
    assert rig.sim.daw_mode and rig.text == "Held (taken automatically)" and rig.prompt.asks == []


@scenario
async def test_an_unanswered_question_stays_open_and_takes_nothing():   # A6
    rig = Rig()
    rig.session.start()
    await settle()
    rig.clock.advance(600)
    await settle()
    assert rig.text == ASK_TEXT and not rig.sim.daw_mode and rig.sim.written == []


@scenario
async def test_a_second_yes_is_answered_already_held_without_a_second_handshake():   # A7
    rig = Rig()
    rig.session.start()
    await settle()
    first = await rig.session.take(BANNER)
    assert first.result is TakeResult.TAKEN
    second = await rig.session.take(NOTIFICATION)
    assert second.result is TakeResult.ALREADY_HELD and second.text == "already held"
    assert len(rig.sim.frames(SysexCommand.IDENTITY_REQUEST)) == 1 and len(daw_mode_frames(rig.sim)) == 1


@scenario
async def test_two_yeses_at_once_take_the_unit_once():   # d17
    rig = Rig()
    rig.session.start()
    answers = await asyncio.gather(rig.session.take(BANNER), rig.session.take(AGENT))
    assert sorted(a.result for a in answers) == [TakeResult.ALREADY_HELD, TakeResult.TAKEN]
    assert len(daw_mode_frames(rig.sim)) == 1


@scenario
async def test_after_a_release_the_banner_asks_again_and_the_unit_stays_out_of_daw_mode():   # A8, A30
    rig = Rig()
    rig.session.start()
    await rig.session.take(AGENT)
    assert rig.text == "Held (taken by command-line tool)"   # A22
    assert await rig.session.release(ReleaseReason.RELEASE) is ReleaseResult.RELEASED
    rig.clock.advance(600)
    await settle()
    assert rig.text == ASK_TEXT and not rig.session.held and not rig.sim.daw_mode
    assert ReleaseResult.RELEASED.text == "Not held"


# --- another program ------------------------------------------------------------------------------------------
@scenario
async def test_busy_names_the_holder_and_nothing_is_sent():   # A9, A10
    for holder in ("Bitwig Studio", "Chrome"):
        rig = Rig()
        rig.sim.hold(DAW, holder)
        rig.session.start()
        assert rig.text == f"Busy: held by {holder}"
        answer = await rig.session.take(BANNER)
        assert answer.result is TakeResult.BUSY and answer.holder == Holder(holder)
        assert rig.text == f"Busy: held by {holder}" and rig.sim.written == []


@scenario
async def test_no_permission_is_not_busy():   # A12
    rig = Rig()
    rig.sim.no_permission = True
    rig.session.start()
    answer = await rig.session.take(ConsentSource.LAN_BROWSER)
    assert answer.result is TakeResult.NO_PERMISSION and rig.text == "No permission to open APC64"


@scenario
async def test_when_the_holder_lets_go_the_host_asks_again_without_taking():   # A13, s33
    rig = Rig()
    rig.sim.hold(DAW, "Bitwig Studio")
    rig.session.start()
    await rig.session.take(BANNER)
    opened = list(rig.sim.opened)
    rig.sim.free(DAW)
    await settle()
    assert rig.text == ASK_TEXT and rig.prompt.asks and rig.sim.opened == opened and not rig.sim.daw_mode


@scenario
async def test_a_missed_free_event_is_caught_by_the_holder_recheck():   # d27, s41
    rig = Rig()
    rig.sim.hold(DAW, "Bitwig Studio")
    rig.session.start()
    await rig.session.take(BANNER)
    rig.sim.busy_roles.discard(DAW)
    rig.sim.holders[DAW] = None   # freed without telling anyone
    rig.clock.advance(1.0)
    await settle()
    assert rig.text == ASK_TEXT


@scenario
async def test_only_the_notes_port_busy_still_holds_but_routes_nothing_from_it():   # A15
    targets = RecordingTargets()
    engine = _real_engine(targets)
    rig = Rig(engine=engine)
    engine._gate = rig.gate
    rig.sim.hold(NOTES, None)
    rig.session.start()
    answer = await rig.session.take(BANNER)
    assert answer.result is TakeResult.TAKEN and rig.sim.daw_mode
    assert rig.session.status().notices == ("APC64 Notes busy: expressive pads not routed",)
    rig.sim.play(NOTES, NoteOn(1, 53, 56))
    assert targets.sent == []


@scenario
async def test_a_second_unit_is_ignored_and_said_so():   # A17
    class TwoUnits:
        def find(self):
            return UnitPresence("hw:4,0,0", "hw:4,0,1", "hw:4,0,3", ignored=1)

        def subscribe(self, callback):
            pass

    rig = Rig(locator=TwoUnits())
    rig.session.start()
    assert rig.text == ASK_TEXT and "second APC64 ignored" in rig.session.status().notices


# --- identity -------------------------------------------------------------------------------------------------
@scenario
async def test_a_silent_device_gets_no_daw_mode_message():   # A18, s41
    rig = Rig(sim=SimulatedApc64(silent=True))
    rig.session.start()
    take = asyncio.ensure_future(rig.session.take(BANNER))
    await settle()
    assert not take.done()
    rig.clock.advance(2.0)
    answer = await take
    assert answer.result is TakeResult.NOT_AN_APC64 and answer.text == "No APC64 identity reply"
    assert "No APC64 identity reply" in rig.session.status().notices
    assert daw_mode_frames(rig.sim) == [] and rig.sim.connections == {}


@scenario
async def test_another_product_is_refused():   # d2, s39
    rig = Rig(sim=SimulatedApc64(product=0x51))
    rig.session.start()
    answer = await rig.session.take(BANNER)
    assert answer.result is TakeResult.NOT_AN_APC64 and answer.detail == "not an APC64 (product 0x51)"
    assert daw_mode_frames(rig.sim) == [] and not rig.store.marker


@scenario
async def test_unknown_firmware_is_a_warning_not_a_refusal():   # A19
    rig = Rig(sim=SimulatedApc64(firmware=(1, 2, 2, 0)))
    rig.session.start()
    await rig.session.take(BANNER)
    assert rig.session.held and rig.session.status().firmware_warning == "untested firmware 1.2.2.0"


@scenario
async def test_a_stale_marker_says_maybe_stuck_and_sends_nothing():   # A20, s36
    rig = Rig(store=MemoryStore(marker=True))
    rig.session.start()
    await settle()
    assert rig.text == "APC64 may still be in DAW mode: Take to reset, or replug it"
    assert rig.sim.written == [] and rig.prompt.asks == [ASK_TEXT]
    await rig.session.take(BANNER)
    await rig.session.release()
    assert rig.store.marker is False


@scenario
async def test_auto_accept_never_resets_a_unit_that_may_be_stuck():   # A20 with auto-accept (a build decision)
    rig = Rig(store=MemoryStore(marker=True), auto_accept=True)
    rig.session.start()
    await settle()
    assert rig.session.status().status == "maybe_stuck" and rig.sim.written == []


# --- release --------------------------------------------------------------------------------------------------
@scenario
async def test_release_clears_then_switches_daw_mode_off_then_frees_the_port():   # A25, A26
    for reason in (ReleaseReason.RELEASE, ReleaseReason.STOP):
        rig = Rig()
        rig.session.start()
        await rig.session.take(BANNER)
        written = len(rig.sim.written)
        assert await rig.session.release(reason) is ReleaseResult.RELEASED
        tail = rig.sim.written[written:]
        assert tail == clear_frames() + [sysex.daw_off()]
        assert rig.sim.dark() and not rig.sim.daw_mode and rig.sim.connections == {}
        assert rig.sim.open(DAW, rig.sim.address(DAW))   # Bitwig could open it now
        assert rig.engine.calls == ["held", "released"] and not rig.store.marker


@scenario
async def test_release_happens_once_and_release_when_not_held_sends_nothing():   # A29, inv14
    rig = Rig()
    rig.session.start()
    assert await rig.session.release() is ReleaseResult.NOT_HELD
    assert ReleaseResult.NOT_HELD.text == "APC64 is not held" and rig.sim.written == []
    await rig.session.take(BANNER)
    await rig.session.release()
    assert await rig.session.release() is ReleaseResult.NOT_HELD
    assert len([f for f in rig.sim.written if f == sysex.daw_off()]) == 1


@scenario
async def test_unplug_while_held_releases_without_sending_and_a_replug_asks_again():   # A23, A24, A27
    rig = Rig()
    rig.session.start()
    await rig.session.take(BANNER)
    written = len(rig.sim.written)
    rig.sim.unplug()
    await settle()
    assert rig.text == "APC64 unplugged: released" and rig.sim.written[written:] == []
    assert rig.engine.calls == ["held", "daw gone", "released"] and not rig.store.marker
    rig.sim.plug(card=5)
    await settle()
    assert rig.text == ASK_TEXT and not rig.sim.daw_mode and rig.prompt.asks[-1] == ASK_TEXT


@scenario
async def test_an_engine_fault_runs_the_same_release():   # A28, s38
    rig = Rig()
    rig.session.start()
    await rig.session.take(BANNER)
    await settle()
    rig.engine.crash()
    await settle()
    assert rig.sim.dark() and not rig.sim.daw_mode and rig.sim.connections == {}
    assert "Released after an internal error" in rig.session.status().notices


@scenario
async def test_release_order_with_a_gate_double_and_daw_off_tried_after_a_failed_clear():   # s37 collaboration
    class Gate:
        def __init__(self):
            self.log, self.fail_clear = [], False

        def attach(self, connection):
            self.log.append("attach")

        def detach(self):
            self.log.append("detach")

        def send(self, frames):
            frames = list(frames)
            if frames == [sysex.daw_off()]:
                self.log.append("daw off")
            elif frames and frames[0] == clear_frames()[0]:
                self.log.append("clear")
                if self.fail_clear:
                    raise PortGone("write failed")
            if sysex.IDENTITY_REQUEST in frames:
                rig.sim._received(sysex.IDENTITY_REQUEST)
            return [GateResult.SENT] * len(frames)

    gate = Gate()
    rig = Rig(gate=gate)
    rig.session.start()
    await rig.session.take(BANNER)
    await rig.session.release()
    assert gate.log[-3:] == ["clear", "daw off", "detach"]
    gate.fail_clear = True
    await rig.session.take(BANNER)
    await rig.session.release()
    assert gate.log[-4:] == ["clear", "attach", "daw off", "detach"]


@scenario
async def test_notes_played_while_not_held_go_nowhere():   # A114
    targets = RecordingTargets()
    engine = _real_engine(targets)
    rig = Rig(engine=engine)
    rig.session.start()
    rig.sim.play(NOTES, NoteOn(1, 53, 56))
    await rig.session.take(BANNER)
    await rig.session.release()
    rig.sim.play(NOTES, NoteOn(1, 53, 56))
    assert targets.sent == []


@scenario
async def test_a_take_with_the_real_engine_draws_the_layout():   # A2 end to end, A37
    targets = RecordingTargets()
    engine = _real_engine(targets)
    rig = Rig(engine=engine)
    engine._gate = rig.gate
    rig.session.start()
    await rig.session.take(BANNER)
    assert rig.sim.daw_mode and rig.sim.oled[0] == "Jam" and rig.sim.leds[(0x90, 0)] == RED.index
    rig.sim.press(PadPos(1, 1))
    rig.sim.play(NOTES, NoteOn(1, 53, 56))
    assert [m for _, m in targets.sent] == [NoteOn(10, 36, 127), NoteOn(2, 53, 56)]
    await rig.session.release()
    assert rig.sim.dark() and not rig.sim.daw_mode


def _real_engine(targets):
    library = LayoutLibrary()
    library.register(LayoutId("jam"), layout(pages=[page(1, "Drums", {PadPos(1, 1): note(36, colour=RED)})],
                                             routing=[notes_rule()]))
    clock = ManualClock()
    engine = HostEngine(gate=OutboundGate(CONTRACT1_POLICY), targets=targets, feedback=RecordingFeedback(),
                        activity=ActivityLog(), stream=PlayStream(clock), library=library,
                        learn=type("Learn", (), {"intercept": lambda self, c: "pass"})(),
                        calibration=type("Cal", (), {"observe": lambda self, p, v: None})(),
                        clock=clock, store=MemoryStore())
    engine.start()
    return engine


@scenario
async def test_reader_threads_reach_the_session_and_engine_through_the_loop():   # a5, s46 with real threads
    loop = asyncio.get_running_loop()
    sim = SimulatedApc64(threaded=True)
    targets = RecordingTargets()
    engine = _real_engine(targets)
    engine._dispatch = loop.call_soon_threadsafe
    gate = OutboundGate(CONTRACT1_POLICY)
    engine._gate = gate
    session = DeviceSession(locator=sim, holders=sim.holder_lookup, port=sim, prompt=Prompt(), store=MemoryStore(),
                            gate=gate, engine=engine, clock=ManualClock(), dispatch=loop.call_soon_threadsafe)
    session.start()
    answer = await asyncio.wait_for(session.take(BANNER), 2)
    assert answer.result is TakeResult.TAKEN
    for _ in range(50):
        sim.press(PadPos(1, 1))
        sim.release(PadPos(1, 1))
        sim.play(NOTES, NoteOn(1, 60, 99))
    for _ in range(200):
        await asyncio.sleep(0.005)
        if len(targets.sent) == 150:
            break
    pads = [m for _, m in targets.sent if m.channel == 10]
    assert len(targets.sent) == 150 and pads[:2] == [NoteOn(10, 36, 127), NoteOff(10, 36)]
    await session.release()
    assert not sim.daw_mode and sim.dark()



@scenario
async def test_a_lost_daw_connection_with_the_unit_still_attached_still_switches_daw_mode_off():   # inv14
    rig = Rig()
    rig.session.start()
    await rig.session.take(BANNER)
    rig.sim.connections[DAW]._on_gone()   # the read failed, the unit itself is still there
    await settle()
    assert not rig.sim.daw_mode and rig.sim.written[-1] == sysex.daw_off() and not rig.store.marker
    assert rig.text == "APC64 unplugged: released"


@scenario
async def test_a_busy_holder_named_at_start_is_rechecked_every_second():   # d27
    rig = Rig()
    rig.sim.hold(DAW, "Bitwig Studio")
    rig.session.start()
    rig.sim.holders[DAW] = None
    rig.sim.busy_roles.discard(DAW)
    rig.clock.advance(1.0)
    await settle()
    assert rig.text == ASK_TEXT and rig.prompt.asks == [ASK_TEXT]
