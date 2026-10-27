"""T30: the UnitMemory adapter against SimulatedApc64 behind the real gate and session tap (s6 supplier; s7–s10
collaboration; A3, A51; a1–a3, a32, a33). Hermetic: the simulator, never a real port."""
import pytest

from _apc64_host.application.outbound_gate import GateResult
from _apc64_host.application.test_session import scenario
from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.outbound import SysexCommand, WriteCapability
from _apc64_host.domain.unit_status import ReleaseReason
from _apc64_host.infrastructure.simulated_apc64 import SimulatedApc64
from _apc64_lab.application.ports import Gone, Interrupted, MalformedReply, NoReply, NotHeld, UnitControl, UnitMemory
from _apc64_lab.domain.memory import Slot
from _apc64_lab.domain.memory_sysex import project_write_frame
from _apc64_lab.domain.pads import Rgb
from _apc64_lab.domain.records import GlobalChange, ProjectRecord
from _apc64_lab.infrastructure.conftest import HeldUnit
from _apc64_lab.application.ports import WrongFirmware

ENCODER = bytes.fromhex("B0 5A 01")


def recoloured(record: ProjectRecord, value=0x2A) -> ProjectRecord:
    return record.with_pad_records({0: record.pads[0].with_fields(rest=Rgb(value, 1, 128))})


@scenario
async def test_the_adapter_implements_the_ports_and_reads_a_slot():   # s6.c2, s10.c1/c2
    unit = await HeldUnit().take()
    assert isinstance(unit.memory, UnitMemory) and isinstance(unit.memory, UnitControl)
    assert unit.memory.read_project(Slot(7)).raw == unit.sim.slot(7)
    assert unit.sim.memory_log[-1] == ("read", 7)


@scenario
async def test_slot_0_is_written_with_the_token_and_reads_back_byte_exact():   # s8.c1, s10.c3/c4, a1, a3
    unit = await HeldUnit().take()
    record = recoloured(unit.memory.read_project(Slot(0)))
    unit.memory.write_project(Slot(0), record, unit.capability)
    assert unit.memory.read_project(Slot(0)) == record and unit.sim.unsaved
    sent = [e for e in unit.gate.device_log() if e.command is SysexCommand.PROJECT_WRITE]
    assert [e.outcome.value for e in sent] == ["sent"]


@scenario
async def test_back_to_back_writes_are_each_applied():   # s10.c5, §2.7 a2
    unit = await HeldUnit().take()
    base = unit.memory.read_project(Slot(0))
    for value in range(10):
        unit.memory.write_project(Slot(0), recoloured(base, value), unit.capability)
    assert unit.sim.slot(0) == recoloured(base, 9).raw and unit.sim.memory_log.count(("write", 0)) == 10


@scenario
async def test_a_write_without_the_token_is_refused_at_the_gate():   # A3, s44 through the real gate
    unit = await HeldUnit().take()
    drums = unit.sim.slot(3)
    frame = project_write_frame(Slot(3), recoloured(ProjectRecord(drums)))
    assert unit.gate.send([frame]) == [GateResult.REFUSED]
    assert unit.gate.send([frame], issuer=WriteCapability("look-alike")) == [GateResult.REFUSED]
    assert unit.sim.slot(3) == drums
    assert [e.hazard_line() for e in unit.gate.device_log() if e.hazard] == ["HAZARD refused: project write slot 3"] * 2


@scenario
async def test_slots_above_24_cannot_be_asked_for_and_a_silent_slot_is_no_reply():   # s10.c2, d65
    unit = await HeldUnit().take()
    with pytest.raises(DomainInvariantError):
        unit.memory.read_project(25)
    unit.sim.faults.silent_slots.add(7)
    with pytest.raises(NoReply):
        unit.memory.read_project(Slot(7))


@scenario
async def test_a_700_byte_dump_is_malformed():   # A51, s7.c2, d66
    unit = await HeldUnit().take()
    unit.sim.faults.short_dump = 700
    with pytest.raises(MalformedReply) as error:
        unit.memory.read_project(Slot(7))
    assert error.value.text("slot 7") + "; nothing written" == "slot 7 read returned 700 bytes, expected 880; nothing written"


@scenario
async def test_a_dump_split_by_encoder_messages_is_one_reply():   # a33, s9.c2
    sim = SimulatedApc64()
    sim.faults.chunks, sim.faults.between = 4, ENCODER
    unit = await HeldUnit(sim).take()
    assert unit.memory.read_project(Slot(5)).raw == sim.slot(5)


@scenario
async def test_not_held_before_the_take_and_after_the_release():   # s8.c2, d70
    unit = HeldUnit()
    with pytest.raises(NotHeld):
        unit.memory.read_project(Slot(0))
    await unit.take()
    await unit.session.release(ReleaseReason.RELEASE)
    with pytest.raises(NotHeld):
        unit.memory.write_project(Slot(0), ProjectRecord(unit.sim.slot(0)), unit.capability)


@scenario
async def test_an_unplug_during_the_write_is_gone():   # s6.c3, A54's adapter half
    unit = await HeldUnit().take()
    unit.sim.faults.unplug_on_write = 7
    with pytest.raises(Gone):
        unit.memory.write_project(Slot(7), recoloured(ProjectRecord(unit.sim.slot(7))), unit.capability)


@scenario
async def test_other_firmware_refuses_writes():   # a32
    unit = await HeldUnit(SimulatedApc64(firmware=(1, 2, 1, 7))).take()
    with pytest.raises(WrongFirmware) as error:
        unit.memory.write_project(Slot(0), ProjectRecord(unit.sim.slot(0)), unit.capability)
    assert str(error.value) == "the APC64 reports firmware 1.2.1.7; memory writes are verified only on 1.2.1.6"


@scenario
async def test_the_global_block_reads_and_writes():   # s10.c6
    unit = await HeldUnit().take()
    settings = unit.memory.read_globals()
    assert settings.raw == unit.sim.global_block
    changed = settings.with_change(GlobalChange.parse({"led_level": 25}))
    unit.memory.write_globals(changed, unit.capability)
    assert unit.memory.read_globals() == changed and unit.sim.global_block[:20] == settings.raw[:20]


@scenario
async def test_the_view_request_asks_for_custom():   # s10.c7, d21
    unit = await HeldUnit().take()
    unit.sim.report_view_requests = True
    assert unit.memory.request_view(UnitView.CUSTOM)
    assert unit.sim.written[-1] == bytes.fromhex("F0 47 00 53 19 00 01 09 F7")
    assert unit.sim.current_view is UnitView.CUSTOM


@scenario
async def test_abort_and_interrupt_end_waits_at_once():   # inv7, the release path
    unit = await HeldUnit().take()
    unit.sim.faults.no_reply = True
    with pytest.raises(Interrupted):
        unit.memory.read_project(Slot(0), interrupt=lambda: True)
    unit.memory.abort()
    with pytest.raises(Gone):
        unit.memory.read_project(Slot(0))
    unit.memory.resume()
    unit.sim.faults.no_reply = False
    assert unit.memory.read_project(Slot(0)).raw == unit.sim.slot(0)
