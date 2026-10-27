"""The lab session end to end on the simulator: SessionService, LabModule, GuardedWriter and the
UnitMemory adapter behind the real gate and the real DeviceSession (its tap and release hook). Hermetic.

§2.7 a5/q9 (binding): the user loads another project mid-session, saves on the unit mid-session, returns to the lab,
and releases after an on-unit change (no restore over it); inv6: unplug and SIGTERM mid-session (restore or
report); a8: a crash marker on the next start. Also the slot-0 decision (inv4 vs §2.7 a5/q9): a slot 0
that matches nothing the lab wrote ends the session quietly, it is never rolled back."""
import time

from _apc64_host.application.ports import HostPorts
from _apc64_host.application.test_session import scenario, settle
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.layout import ControlEvent
from _apc64_host.domain.unit_status import ReleaseReason
from _apc64_host.infrastructure.simulated_apc64 import SimulatedApc64
from _apc64_host.notation.compiler import compile_text
from _apc64_lab.application.conftest import EngineDouble, FakeBackups, FakeLibrary, RecordingPublisher, Wall
from _apc64_lab.application.guarded_writer import GuardedWriter
from _apc64_lab.application.module import LabModule
from _apc64_lab.application.ports import SET_SESSION, HostLink
from _apc64_lab.application.project_memory import ProjectMemory
from _apc64_lab.application.registry import DefinitionIndex, GeneratorRegistry
from _apc64_lab.application.section_compiler import LabSectionCompiler
from _apc64_lab.application.session_service import SessionService
from _apc64_lab.domain.lab_section import INTERVAL_CYCLE, WINDOW_SHIFT
from _apc64_lab.domain.memory import BackupId, OutcomeKind, Slot
from _apc64_lab.domain.records import ProjectRecord
from _apc64_lab.domain.session import RESTORED_MESSAGE
from _apc64_lab.infrastructure.conftest import HeldUnit
from _apc64_lab.infrastructure.unit_memory import UnitMemoryAdapter

TONNETZ_C = "name: Tonnetz C\nlab:\n  generator: tonnetz\n  base: 48\n"
JAM = "name: Jam\ndevices: {mpc: MPC Live III MIDI 1}\npages:\n  1:\n    pad r1c1: note 36\n"


class Lab:
    """The lab's object graph by hand (T39's build_lab will compose the same), on a held simulated unit."""

    def __init__(self, unit: HeldUnit, backups=None, threaded=False):
        self.unit, self.sim = unit, unit.sim
        self.engine = EngineDouble()
        self.link = HostLink(HostPorts(display=self.engine, notes=self.engine, loader=self.engine,
                                       sysex=unit.session.sysex_tap, gate=unit.gate, clock=unit.rig.clock))
        self.memory = UnitMemoryAdapter(self.link, timeout=0.05)
        self.backups = backups or FakeBackups()
        self.wall = Wall()
        self.writer = GuardedWriter(self.memory, self.backups, unit.capability, self.link, self.wall)
        self.registry = GeneratorRegistry().load()
        self.index = DefinitionIndex()
        self.compiler = LabSectionCompiler(self.registry.generators, self.registry.schemes, None, self.index.record)
        self.publisher = RecordingPublisher()
        self.session = SessionService(self.writer, self.backups, self.registry, self.link, self.publisher,
                                      control=self.memory, index=self.index, wall=self.wall, threaded=threaded,
                                      settle=0.0)
        self.module = LabModule(self.link, self.writer, self.session, self.compiler)
        self.projects = ProjectMemory(self.writer, self.backups, FakeLibrary(), self.registry, self.index,
                                      self.session, self.wall)
        unit.use([self.module])

    def load(self, text=TONNETZ_C, file="tonnetz-c.yaml"):
        layout = compile_text(text, file, sections=self.module.layout_sections()).layout
        self.module.on_layout_loaded(layout, layout.section("lab"))
        self.session.drain()
        return layout

    def turn(self, steps=1):
        self.module.actions()[WINDOW_SHIFT](ControlEvent(steps=steps))
        self.session.drain()

    def tempo(self):
        self.module.actions()[INTERVAL_CYCLE](ControlEvent(press=True))

    def r1c1(self):
        return ProjectRecord(self.sim.slot(0)).pad(PadPos(1, 1)).note

    def slot0_writes(self):
        return self.sim.memory_log.count(("write", 0))


async def playing(sim=None, backups=None):
    unit = HeldUnit(sim)
    lab = Lab(unit, backups)                            # registered before the take, as at service start
    await unit.take()
    lab.sim.view(UnitView.CUSTOM)
    lab.loops = lab.sim.slot(0)                         # the user's project in the edit buffer
    lab.load()
    return lab


@scenario
async def test_activation_backs_up_slot_0_writes_the_lattice_and_backs_up_slots_1_to_24():   # A22, §2.7 a5/q9
    lab = await playing()
    backup = BackupId("slot0-2026-10-24T20-15")
    assert lab.backups.get(backup).data == lab.loops and lab.backups.marker == backup
    assert lab.r1c1() == 48 and lab.sim.unsaved and lab.engine.oled.rows == ("Tonnetz C", "Oct +0")
    (full,) = lab.backups.sets()
    assert full.kind == SET_SESSION and full.covers_stored_slots
    log = lab.sim.memory_log
    assert log.index(("write", 0)) < log.index(("read", 1))   # the full backup only after the first write


@scenario
async def test_shifts_and_tempo_play_on_the_unit():   # A24, A27, A29 end to end
    lab = await playing()
    lab.turn(+1)
    assert lab.r1c1() == 60
    lab.tempo()
    lab.turn(+2)
    lab.tempo()
    lab.turn(-1)
    assert lab.r1c1() == 48 + 12 + 14 - 4 and lab.engine.oled.rows == ("Tonnetz C", "3rd -1")


@scenario
async def test_the_user_loads_another_project_mid_session():   # §2.7 a5/q9
    lab = await playing()
    writes = lab.slot0_writes()
    lab.sim.load_project(12, back_to=UnitView.CUSTOM)        # Project view, then back to Custom view
    lab.turn(+1)
    assert lab.slot0_writes() == writes and lab.sim.slot(0) == lab.sim.slot(12)
    assert not lab.session.running and lab.session.message.startswith("lab session ended quietly (project view)")
    assert lab.backups.get(BackupId("slot0-2026-10-24T20-15")).data == lab.loops      # kept and listed
    await lab.unit.session.release(ReleaseReason.RELEASE)
    assert lab.slot0_writes() == writes and lab.sim.slot(0) == lab.sim.slot(12)   # no restore over it


@scenario
async def test_the_user_saves_on_the_unit_mid_session():   # §2.7 a5/q9
    lab = await playing()
    old5 = lab.sim.slot(5)
    generated = lab.sim.slot(0)
    lab.sim.save_project(5, back_to=UnitView.CUSTOM)       # the generated layout lands in project 5
    assert lab.sim.slot(5) == generated and not lab.session.running
    (full,) = lab.backups.sets()
    slot5 = dict(full.members)["slot5"]
    assert lab.backups.get(slot5).data == old5              # recoverable from the session's full backup
    outcome = lab.projects.restore(slot5, 5)                # one command puts project 5 back
    assert outcome.result is OutcomeKind.RESTORED and lab.sim.slot(5) == old5
    writes = lab.slot0_writes()
    await lab.unit.session.release(ReleaseReason.RELEASE)
    assert lab.slot0_writes() == writes and lab.sim.slot(0) == generated   # no restore over the saved layout


@scenario
async def test_returning_to_the_lab_starts_a_fresh_session():   # §2.7 a5/q9
    lab = await playing()
    lab.sim.load_project(12, back_to=UnitView.CUSTOM)
    lab.wall.advance(minutes=1)
    lab.load()                                              # Shift + encoder (or page, agent) back to Tonnetz C
    assert lab.session.running and lab.r1c1() == 48
    second = BackupId("slot0-2026-10-24T20-16")
    assert lab.backups.get(second).data == lab.sim.slot(12) and lab.backups.marker == second
    assert len(lab.backups.sets()) == 1                     # the full backup is 1 minute old: reused
    await lab.unit.session.release(ReleaseReason.RELEASE)
    assert lab.sim.slot(0) == lab.sim.slot(12) and lab.session.message == RESTORED_MESSAGE


@scenario
async def test_release_after_an_on_unit_change_restores_nothing():   # §2.7 a5/q9
    lab = await playing()
    lab.sim.set_slot(0, lab.sim.slot(9))                    # changed on the unit, no Project-view report
    writes = lab.slot0_writes()
    await lab.unit.session.release(ReleaseReason.RELEASE)
    assert lab.slot0_writes() == writes and lab.sim.slot(0) == lab.sim.slot(9)
    assert "nothing restored" in lab.session.message


@scenario
async def test_a_foreign_slot_0_read_back_ends_quietly_and_is_never_rolled_back():   # the slot-0 decision
    lab = await playing()
    lab.sim.mismatch_on_write(0, 4, 0x55)                   # the unit keeps something else than we sent
    lab.turn(+1)
    assert not lab.session.running and "slot 0 changed on the unit" in lab.session.message
    assert lab.slot0_writes() == 2                           # the first write and the shift: no rollback write


@scenario
async def test_release_and_sigterm_restore_slot_0():   # A42, inv6
    lab = await playing()
    lab.turn(+3)
    await lab.unit.session.release(ReleaseReason.RELEASE)
    assert lab.sim.slot(0) == lab.loops and not lab.sim.daw_mode
    assert lab.session.message == RESTORED_MESSAGE and lab.backups.marker is None
    lab2 = await playing()
    await lab2.unit.session.release(ReleaseReason.STOP)     # SIGTERM: uvicorn's lifespan release('stop')
    assert lab2.sim.slot(0) == lab2.loops


@scenario
async def test_an_unplug_mid_session_names_the_backup_and_the_next_take_offers_it():   # A43, inv6, a8
    lab = await playing()
    lab.sim.unplug()
    await settle()
    assert lab.session.message == ("slot 0 could not be restored; restore slot0-2026-10-24T20-15 after reconnecting")
    assert lab.backups.marker == "slot0-2026-10-24T20-15"
    lab.sim.plug()
    await lab.unit.take()
    writes = lab.slot0_writes()
    lab.load()
    assert lab.slot0_writes() == writes and lab.session.recovery == "slot0-2026-10-24T20-15"
    outcome = lab.projects.restore("slot0-2026-10-24T20-15", 0)
    assert outcome.result is OutcomeKind.RESTORED and lab.sim.slot(0) == lab.loops
    lab.session.drain()
    assert lab.session.running and lab.session.recovery is None   # the generated layout plays again


@scenario
async def test_a_crash_marker_is_offered_on_the_next_start():   # a8
    backups = FakeBackups()
    unit = HeldUnit()
    first = Lab(unit, backups)
    await unit.take()
    loops = unit.sim.slot(0)
    unit.sim.view(UnitView.CUSTOM)
    first.load()
    assert backups.marker == "slot0-2026-10-24T20-15"         # the service dies here: no release, no restore
    restarted = Lab(unit, backups)                             # the next start, same backups directory
    state = restarted.session.state()
    assert state.recovery["backup"] == "slot0-2026-10-24T20-15"
    restarted.module.on_held(unit.session.held_unit())
    restarted.load()
    assert unit.sim.slot(0) != loops                            # nothing taken over: slot 0 still the lattice
    outcome = restarted.projects.restore("slot0-2026-10-24T20-15", 0)
    restarted.session.drain()
    assert outcome.message.startswith("restored slot 0 from slot0-2026-10-24T20-15")
    assert restarted.session.recovery is None


@scenario
async def test_loading_a_host_layout_restores_slot_0():   # A44
    lab = await playing()
    lab.load(JAM, "jam.yaml")
    assert lab.sim.slot(0) == lab.loops and not lab.session.running


@scenario
async def test_a_spin_with_the_writer_thread_ends_at_the_final_offset():   # A30 with the slot-0 writer thread
    unit = HeldUnit()
    lab = Lab(unit, threaded=True)
    await unit.take()
    try:
        unit.sim.view(UnitView.CUSTOM)
        loops = unit.sim.slot(0)
        layout = compile_text(TONNETZ_C, "tonnetz-c.yaml", sections=lab.module.layout_sections()).layout
        lab.module.on_layout_loaded(layout, layout.section("lab"))
        _wait(lambda: lab.session.session.active and lab.slot0_writes() >= 1)
        lab.tempo()
        for _ in range(6):
            lab.module.actions()[WINDOW_SHIFT](ControlEvent(steps=1))
            time.sleep(0.02)
        _wait(lambda: lab.r1c1() == 90)
        _wait(lambda: lab.session.slot0.idle, 5.0)
        await unit.session.release(ReleaseReason.RELEASE)
        assert unit.sim.slot(0) == loops
    finally:
        lab.session.close()


def _wait(condition, seconds=3.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.002)
    raise AssertionError("timed out")
