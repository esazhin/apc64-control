"""Contract 2 T12: the simulated APC64's memory (pi1; §3.5 fault injection; §2.7 a5/q9 on-unit load and save).

Reads and writes go through a real OutboundGate whose policy is the lab's shape (reads added, writes scoped to
a WriteCapability), so these frames are exactly what the lab will send. Contract 1's simulator tests stay in
test_simulated_apc64.py."""
import pytest

from _apc64_host.application.outbound_gate import GateResult, OutboundGate
from _apc64_host.application.ports import PortGone
from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.layout import UnitPortRole
from _apc64_host.domain.outbound import CONTRACT1_POLICY, SysexCommand, WriteCapability
from _apc64_host.infrastructure.simulated_apc64 import (
    FIXTURES, GLOBAL_SIZE, PROJECT_SIZE, SimulatedApc64, global_dump, project_dump,
)
from _apc64_host.protocol import sysex
from _apc64_host.protocol.stream import MidiStreamSplitter

TOKEN = WriteCapability()
POLICY = CONTRACT1_POLICY.with_additions({SysexCommand.PROJECT_READ, SysexCommand.GLOBAL_READ}) \
    .with_scoped({SysexCommand.PROJECT_WRITE, SysexCommand.GLOBAL_WRITE}, TOKEN)


def read(slot):
    return sysex.akai_frame(sysex.PROJECT_READ, bytes([slot]))


GLOBAL_READ = sysex.akai_frame(sysex.GLOBAL_READ, b"")


class Unit:
    """The simulator behind the gate, with every DAW-port message the host would receive, split."""

    def __init__(self, **kwargs):
        self.sim = SimulatedApc64(**kwargs)
        self.gate = OutboundGate(POLICY)
        self.connection = self.sim.open(UnitPortRole.DAW, self.sim.address(UnitPortRole.DAW))
        self.received, self.chunks, self.gone = [], [], []
        splitter = MidiStreamSplitter()

        def on_bytes(chunk):
            self.chunks.append(chunk)
            self.received += splitter.feed(chunk)
        self.connection.listen(on_bytes, lambda: self.gone.append(True))
        self.gate.attach(self.connection)

    def send(self, *frames, issuer=None):
        return self.gate.send(list(frames), issuer=issuer)

    def dumps(self):
        return [m for m in self.received if sysex.command_of(m) in (SysexCommand.PROJECT_WRITE,
                                                                        SysexCommand.GLOBAL_WRITE)]


def loops():
    """'Loops': slot 7's captured record with a recognisable change, as a raw 880-byte record."""
    sim = SimulatedApc64()
    raw = bytearray(sim.slot(7))
    raw[4:7] = b"\x10\x20\x30"
    return bytes(raw)


def test_the_unit_starts_as_the_captured_snapshot_and_answers_reads_with_the_1015_byte_dump():
    unit = Unit()
    lines = [bytes.fromhex(line) for line in (FIXTURES / "apc64-snapshot-2026-10-22.hex").read_text().splitlines()
             if line.startswith("F0 47 00 53 14")]
    assert [project_dump(n, unit.sim.slot(n)) for n in range(25)] == lines
    assert global_dump(unit.sim.global_block) == (FIXTURES / "apc64-global-settings-2026-10-22.syx").read_bytes()
    assert unit.send(read(7)) == [GateResult.SENT]
    (dump,) = unit.dumps()
    assert len(dump) == 1015 and dump[:8] == bytes.fromhex("F0 47 00 53 14 07 6F 07") and dump == lines[7]
    assert unit.sim.memory_log == [("read", 7)]


def test_a_write_is_applied_slot_0_marks_the_project_unsaved_and_slot_25_stays_silent():
    unit = Unit()
    record = loops()
    assert unit.send(project_dump(7, record), issuer=TOKEN) == [GateResult.SENT]
    assert unit.sim.slot(7) == record and not unit.sim.unsaved
    unit.send(read(7))
    assert unit.dumps() == [project_dump(7, record)]          # read-back equals what was written
    unit.send(project_dump(0, record), issuer=TOKEN)
    assert unit.sim.slot(0) == record and unit.sim.unsaved
    unit.received.clear()
    unit.send(read(25))
    assert unit.received == [] and unit.sim.memory_log[-1] == ("read", 25)


def test_back_to_back_slot_0_writes_end_on_the_last():
    # §2.7 a2: 10 writes with no read-back between them are all accepted
    unit = Unit()
    records = [bytes([n]) * PROJECT_SIZE for n in range(10)]
    assert unit.send(*[project_dump(0, r) for r in records], issuer=TOKEN) == [GateResult.SENT] * 10
    assert unit.sim.slot(0) == records[-1]


def test_globals_are_read_and_written():
    unit = Unit()
    unit.send(GLOBAL_READ)
    assert unit.dumps() == [global_dump(unit.sim.global_block)] and len(unit.dumps()[0]) == 72
    block = bytearray(unit.sim.global_block)
    block[55] = 100
    unit.send(global_dump(bytes(block)), issuer=TOKEN)
    assert unit.sim.global_block == bytes(block) and len(unit.sim.global_block) == GLOBAL_SIZE


def test_a_token_less_write_never_reaches_the_simulated_memory():
    unit = Unit()
    before = list(unit.sim.slots)
    assert unit.send(project_dump(3, loops())) == [GateResult.REFUSED]
    assert unit.sim.slots == before and unit.sim.memory_log == []


# --- faults ---------------------------------------------------------------------------------------------------
def test_no_reply_and_silent_slots():
    unit = Unit()
    unit.sim.faults.no_reply = True
    unit.send(read(7), GLOBAL_READ)
    assert unit.dumps() == []
    unit.sim.faults.no_reply = False
    unit.sim.faults.silent_slots = {7}
    unit.send(read(7), read(8))
    assert [d[7] for d in unit.dumps()] == [8]


def test_a_short_dump_unpacks_to_fewer_bytes():
    # A51: the dump unpacks to 700 bytes
    unit = Unit()
    unit.sim.faults.short_dump = 700
    unit.send(read(7))
    (dump,) = unit.dumps()
    assert len(sysex.unpack7(dump[8:-1])) == 700


def test_a_read_back_mismatch_stores_a_different_byte():
    # A4: the unit reads back pad r3c4 with a different colour than was written (pad 20, byte 4 = red)
    unit = Unit()
    record = loops()
    unit.sim.mismatch_on_write(7, offset=19 * 12 + 4, value=0x55)
    unit.send(project_dump(7, record), issuer=TOKEN)
    unit.send(read(7))
    back = sysex.unpack7(unit.dumps()[0][8:-1])
    assert back != record and back[19 * 12 + 4] == 0x55
    assert [i for i in range(PROJECT_SIZE) if back[i] != record[i]] == [19 * 12 + 4]


def test_an_unplug_mid_write_fails_the_write_and_tells_the_host_afterwards():
    # A54/d71: the port goes away while slot 7 is written; the host hears of it once complete_unplug runs
    unit = Unit()
    before = unit.sim.slot(7)
    unit.sim.faults.unplug_on_write = 7
    presence = []
    unit.sim.subscribe(presence.append)
    with pytest.raises(PortGone, match="slot 7"):
        unit.send(project_dump(7, loops()), issuer=TOKEN)
    assert unit.sim.slot(7) == before and not unit.gate.attached
    assert unit.gone == [] and presence == []         # nothing re-entered the host inside the gate's send
    unit.sim.complete_unplug()
    assert unit.gone == [True] and presence == [None] and unit.sim.find() is None


def test_a_reply_can_arrive_in_chunks_with_encoder_messages_between_them():
    # a33: the dump reaches the host split across reads, B0 5A 01 between the pieces (T15's tap reassembles it)
    unit = Unit()
    unit.sim.faults.chunks, unit.sim.faults.between = 3, bytes.fromhex("B0 5A 01")
    unit.send(read(7))
    assert b"".join(c for c in unit.chunks if c != bytes.fromhex("B0 5A 01")) == project_dump(7, unit.sim.slot(7))
    assert unit.chunks.count(bytes.fromhex("B0 5A 01")) == 2


def test_a_mode_report_and_answering_view_requests():
    unit = Unit()
    unit.sim.view(UnitView.CUSTOM)
    assert unit.received[-1] == sysex.encode_view_report(UnitView.CUSTOM) == bytes.fromhex("F0 47 00 53 19 00 01 09 F7")
    unit.received.clear()
    custom_request = sysex.akai_frame(sysex.PAD_MODE, b"\x09")
    unit.sim.current_view = UnitView.SESSION
    unit.send(custom_request)
    assert unit.received == [] and unit.sim.current_view is UnitView.CUSTOM    # obeyed, no answer (live 2026-10-27)
    unit.sim.report_view_requests = True
    unit.send(custom_request)
    assert unit.received == [bytes.fromhex("F0 47 00 53 19 00 01 09 F7")]
    assert unit.sim.current_view is UnitView.CUSTOM


# --- §2.7 a5/q9: the user loads and saves projects on the unit mid-session ---------------------------------
def test_the_user_loads_another_project_on_the_unit():
    unit = Unit()
    generated = bytes([0x2A]) * PROJECT_SIZE
    unit.send(project_dump(0, generated), issuer=TOKEN)            # the lab's layout sits in slot 0
    unit.received.clear()
    unit.sim.load_project(12, back_to=UnitView.CUSTOM)
    assert unit.received == [sysex.encode_view_report(UnitView.PROJECT), sysex.encode_view_report(UnitView.CUSTOM)]
    assert unit.sim.slot(0) == unit.sim.slot(12) != generated
    assert unit.sim.loaded_project == 12 and not unit.sim.unsaved
    unit.send(read(0))
    assert unit.dumps()[-1] == project_dump(0, unit.sim.slot(12))   # slot 0 now matches nothing the lab wrote


def test_the_user_saves_on_the_unit_while_a_generated_layout_is_in_slot_0():
    unit = Unit()
    unit.sim.load_project(5, report=False)
    generated = bytes([0x2B]) * PROJECT_SIZE
    unit.send(project_dump(0, generated), issuer=TOKEN)
    assert unit.sim.unsaved
    unit.sim.save_project()                                          # to the loaded project, 5
    assert unit.sim.slot(5) == generated and not unit.sim.unsaved
    assert unit.received[-1] == sysex.encode_view_report(UnitView.PROJECT)
    unit.sim.save_project(9, report=False)
    assert unit.sim.slot(9) == generated
    assert unit.sim.memory_log[-2:] == [("save_on_unit", 5), ("save_on_unit", 9)]
    with pytest.raises(ValueError):
        unit.sim.load_project(0)
