"""Contract 2 T15: the session's release hook and SysEx tap (inv6, pi4; s3 collaboration, s9/s41/s42 suppliers).

on_release(reason) runs once per release, after DAW off and before the gate detaches, for release, stop, SIGTERM
(the lifespan's release('stop')), unplug and an engine fault; a raising hook never stops the exit. The tap
reassembles a 1015-byte dump split by B0 5A 01 messages and hands it over as one frame; held() gives the
identity. The last cases show the lab's slot-0 decision is expressible on these seams: at release a module
reads slot 0 back through the tap, restores its backup over a record it wrote, and writes nothing over a project
the user loaded on the unit (§2.7 a5/q9)."""
import asyncio

from _apc64_host.application.modules import collect
from _apc64_host.application.outbound_gate import OutboundGate
from _apc64_host.application.ports import HostModuleBase, SysexTap
from _apc64_host.application.session import ReleaseResult
from _apc64_host.application.test_session import AGENT, Engine, Rig, scenario, settle
from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.outbound import CONTRACT1_POLICY, SysexCommand, WriteCapability
from _apc64_host.domain.unit_status import ReleaseReason
from _apc64_host.infrastructure.simulated_apc64 import PROJECT_SIZE, SimulatedApc64, project_dump
from _apc64_host.protocol import sysex

TOKEN = WriteCapability()
LAB_POLICY = CONTRACT1_POLICY.with_additions({SysexCommand.PROJECT_READ, SysexCommand.GLOBAL_READ}) \
    .with_scoped({SysexCommand.PROJECT_WRITE, SysexCommand.GLOBAL_WRITE}, TOKEN)
ENCODER = bytes.fromhex("B0 5A 01")


def read(slot):
    return sysex.akai_frame(sysex.PROJECT_READ, bytes([slot]))


class ChunkEngine(Engine):
    """The engine double, keeping every chunk the DAW tap passes on."""

    def __init__(self):
        super().__init__()
        self.chunks = []

    def on_held(self, unit):
        self.calls.append("held")
        self.unit = unit
        unit.daw.listen(self.chunks.append, lambda: self.calls.append("daw gone"))


class Recorder(HostModuleBase):
    name = "lab"

    def __init__(self, rig_ref, raises=False):
        self.rig_ref, self.raises, self.releases = rig_ref, raises, []

    def on_release(self, reason):
        rig = self.rig_ref()
        self.releases.append((reason, rig.sim.daw_mode, rig.gate.attached, rig.session.held_unit() is not None))
        if self.raises:
            raise RuntimeError("restore failed")


def rig_with(module_factory, sim=None, engine=None):
    holder = {}
    module = module_factory(lambda: holder["rig"])
    rig = Rig(sim=sim, gate=OutboundGate(LAB_POLICY), engine=engine)
    rig.session._modules = collect([module]).hooks           # as DeviceSession(modules=…) is given it
    rig.module = module
    holder["rig"] = rig
    return rig


async def taken(rig):
    rig.session.start()
    answer = await rig.session.take(AGENT)
    assert answer.result.value == "taken"
    return rig


# --- on_release (s3.c1, s3.c2, s41, s42) ---------------------------------------------------------------------
@scenario
async def test_release_runs_the_hook_once_after_daw_off_and_before_detach():
    rig = await taken(rig_with(Recorder))
    assert await rig.session.release(ReleaseReason.RELEASE) is ReleaseResult.RELEASED
    assert await rig.session.release(ReleaseReason.RELEASE) is ReleaseResult.NOT_HELD
    assert rig.module.releases == [(ReleaseReason.RELEASE, False, True, True)]   # DAW off sent, still attached
    assert not rig.gate.attached and rig.session.held_unit() is None


@scenario
async def test_stop_and_sigterm_run_the_hook_with_stop():
    rig = await taken(rig_with(Recorder))
    rig.session.stop()                                       # service stop (and the atexit safety net)
    assert rig.module.releases == [(ReleaseReason.STOP, False, True, True)]
    rig = await taken(rig_with(Recorder))
    await rig.session.release(ReleaseReason.STOP)            # SIGTERM: uvicorn's lifespan release('stop')
    rig.session.stop()
    assert rig.module.releases == [(ReleaseReason.STOP, False, True, True)]


@scenario
async def test_an_unplug_runs_the_hook_once_with_unplug():
    rig = await taken(rig_with(Recorder))
    rig.sim.unplug()
    await settle()
    assert rig.module.releases == [(ReleaseReason.UNPLUG, False, False, True)]   # nothing can be sent any more


@scenario
async def test_an_engine_fault_runs_the_hook_with_fault():
    rig = await taken(rig_with(Recorder))
    await settle()
    rig.engine.crash()
    await settle()
    assert [r[0] for r in rig.module.releases] == [ReleaseReason.FAULT]


@scenario
async def test_a_raising_hook_does_not_stop_the_exit():
    rig = await taken(rig_with(lambda ref: Recorder(ref, raises=True)))
    assert await rig.session.release() is ReleaseResult.RELEASED
    assert len(rig.module.releases) == 1
    assert rig.session.status().status == "asking" or not rig.session.held
    assert not rig.gate.attached and not rig.store.marker and not rig.sim.daw_mode


@scenario
async def test_no_hook_runs_for_a_take_that_never_reached_daw_mode():
    rig = rig_with(Recorder, sim=SimulatedApc64(silent=True))
    rig.session.start()
    pending = asyncio.ensure_future(rig.session.take(AGENT))
    await settle()
    rig.clock.advance(2.5)                                   # no identity reply: the attempt is abandoned
    await pending
    rig.session.stop()
    assert rig.module.releases == []


# --- the SysEx tap (s9.c1, s9.c2; a33) ------------------------------------------------------------------------
@scenario
async def test_a_1015_byte_reply_split_by_encoder_messages_reaches_the_tap_as_one_frame():
    sim = SimulatedApc64()
    sim.faults.chunks, sim.faults.between = 4, ENCODER
    rig = await taken(rig_with(Recorder, sim=sim, engine=ChunkEngine()))
    frames, ended = [], []
    tap = rig.session.sysex_tap
    assert isinstance(tap, SysexTap)
    tap.subscribe({SysexCommand.PROJECT_WRITE, SysexCommand.GLOBAL_WRITE}, frames.append, ended.append)
    rig.engine.chunks.clear()
    rig.gate.send([read(7)])
    assert frames == [project_dump(7, sim.slot(7))] and len(frames[0]) == 1015
    assert b"".join(rig.engine.chunks) == ENCODER * 3       # the turns still reach the engine; the dump does not
    await rig.session.release()
    assert ended == [ReleaseReason.RELEASE]


@scenario
async def test_held_gives_the_identity_with_firmware_1_2_1_6_and_none_when_not_held():
    rig = rig_with(Recorder)
    assert rig.session.sysex_tap.held() is None
    await taken(rig)
    unit = rig.session.sysex_tap.held()
    assert str(unit.identity.firmware) == sysex.KNOWN_FIRMWARE == "1.2.1.6"
    assert unit is rig.engine.unit                           # the same HeldUnit the engine got
    await rig.session.release()
    assert rig.session.sysex_tap.held() is None


@scenario
async def test_without_a_subscriber_the_daw_bytes_reach_the_engine_unchanged():
    rig = await taken(rig_with(Recorder, engine=ChunkEngine()))
    rig.engine.chunks.clear()
    chunk = project_dump(3, bytes(PROJECT_SIZE))[:500]        # half a dump, then a turn: contract 1's stream
    rig.sim.emit("daw", chunk)
    rig.sim.emit("daw", ENCODER)
    assert rig.engine.chunks == [chunk, ENCODER]


@scenario
async def test_a_cancelled_subscription_gets_nothing_more():
    rig = await taken(rig_with(Recorder))
    frames = []
    subscription = rig.session.sysex_tap.subscribe({SysexCommand.PROJECT_WRITE}, frames.append)
    rig.gate.send([read(1)])
    subscription.cancel()
    rig.gate.send([read(2)])
    assert [f[7] for f in frames] == [1]


# --- the lab's slot-0 decision, expressed on these seams (§2.7 a5/q9) -------------------------------------
class SessionEnd(HostModuleBase):
    """What the lab's SessionService will do at release: read slot 0 back; restore the backup only over a
    record the lab itself wrote; over anything else (a project the user loaded) write nothing."""
    name = "lab"

    def __init__(self, rig_ref):
        self.rig_ref, self.backup, self.written, self.outcome = rig_ref, None, set(), None

    def session_write(self, record):
        rig = self.rig_ref()
        replies = []
        sub = rig.session.sysex_tap.subscribe({SysexCommand.PROJECT_WRITE}, replies.append)
        rig.gate.send([read(0)])
        self.backup = sysex.unpack7(replies[0][8:-1])          # the one session backup, before the first write
        sub.cancel()
        rig.gate.send([project_dump(0, record)], issuer=TOKEN)
        self.written.add(record)

    def on_release(self, reason):
        rig = self.rig_ref()
        replies = []
        sub = rig.session.sysex_tap.subscribe({SysexCommand.PROJECT_WRITE}, replies.append)
        try:
            rig.gate.send([read(0)])                           # synchronous here; a real reply waits on the reader
            slot0 = sysex.unpack7(replies[0][8:-1])
        finally:
            sub.cancel()
        if slot0 not in self.written:
            self.outcome = "quiet"                             # the user changed projects: no restore over it
            return
        rig.gate.send([project_dump(0, self.backup)], issuer=TOKEN)
        self.outcome = "restored"


@scenario
async def test_at_release_slot_0_holding_the_labs_record_is_restored_from_the_backup():
    rig = await taken(rig_with(SessionEnd))
    loops = rig.sim.slot(0)
    rig.module.session_write(bytes([0x2A]) * PROJECT_SIZE)
    assert rig.sim.slot(0) != loops
    await rig.session.release()
    assert rig.module.outcome == "restored" and rig.sim.slot(0) == loops


@scenario
async def test_at_release_after_the_user_loaded_another_project_nothing_is_written():
    rig = await taken(rig_with(SessionEnd))
    rig.module.session_write(bytes([0x2A]) * PROJECT_SIZE)
    rig.sim.load_project(12, back_to=UnitView.CUSTOM)          # on the unit, mid-session
    writes_before = rig.sim.memory_log.count(("write", 0))
    await rig.session.release()
    assert rig.module.outcome == "quiet"
    assert rig.sim.slot(0) == rig.sim.slot(12) and rig.sim.memory_log.count(("write", 0)) == writes_before
