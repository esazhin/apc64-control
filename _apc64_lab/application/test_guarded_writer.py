"""T24: GuardedWriter over UnitMemory and BackupStore doubles (s6 and s13 collaboration; inv1–inv4, inv8;
A1, A2, A4, A5, A6, A7, A51, A52, A54, d67–d73, d79, d96)."""
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.outbound import SysexCommand, WriteCapability
from _apc64_lab.application.conftest import Events, FakeBackups, FakeMemory, Wall
from _apc64_lab.application.guarded_writer import GuardedWriter
from _apc64_lab.application.ports import HostLink
from _apc64_lab.domain.generators import FifthsHue, TonnetzCheckerboard, generate
from _apc64_lab.domain.memory import GLOBALS, OutcomeCode, OutcomeKind, StoredSlot, pushed_message
from _apc64_lab.domain.records import GlobalChange

from _apc64_lab.application.conftest import EngineDouble, host_ports

TONNETZ_C = generate(TonnetzCheckerboard(), {"base": 48, "channel": 1}, FifthsHue())
SLOT7 = StoredSlot(7)


def tonnetz_c(record):
    return record.with_pads(TONNETZ_C)


class Rig:
    def __init__(self):
        self.events = Events()
        self.memory = FakeMemory(self.events)
        self.backups = FakeBackups(self.events)
        self.engine = EngineDouble()
        self.capability = WriteCapability("test")
        self.writer = GuardedWriter(self.memory, self.backups, self.capability,
                                    HostLink(host_ports(self.engine)), Wall())

    def push(self, slot=SLOT7, change=tonnetz_c):
        return self.writer.write_project(slot, change, what=f"push to slot {int(slot)}",
                                         success=lambda backup: pushed_message(slot))


def test_a_push_backs_up_first_then_writes_and_reads_back():   # A1, inv1, s6.c1
    rig = Rig()
    loops = rig.memory.slots[7]
    outcome = rig.push()
    assert outcome.result is OutcomeKind.PUSHED and outcome.backup == "slot7-2026-10-24T20-15"
    assert outcome.message == "pushed to slot 7; takes effect when project 7 is next loaded"
    assert rig.events == [("read", 7), ("backup", "slot7-2026-10-24T20-15"), ("write", 7), ("read", 7)]
    assert rig.backups.get(outcome.backup).data == loops.raw and rig.memory.slots[7] == tonnetz_c(loops)
    assert outcome.to_json() == {"result": "pushed", "backup": "slot7-2026-10-24T20-15",
                                 "message": "pushed to slot 7; takes effect when project 7 is next loaded"}


def test_unknown_bytes_survive_the_merge():   # A2, inv3
    rig = Rig()
    raw = bytearray(rig.memory.slots[7].raw)
    raw[11 * 12 + 11] = 0x05                          # pad 12, byte 11
    strip3 = 64 * 12 + 2 * 14
    raw[strip3 + 3], raw[strip3 + 5] = 0x02, 0x03
    rig.memory.slots[7] = type(rig.memory.slots[7])(bytes(raw))
    rig.push()
    after = rig.memory.slots[7]
    assert after.pads[11].unknown == 0x05 and (after.strip(3).unknown3, after.strip(3).unknown5) == (0x02, 0x03)


def test_a_differing_read_back_restores_the_backup_and_warns():   # A4, inv4, d67
    rig = Rig()
    loops = rig.memory.slots[7]
    rig.memory.mismatch[7] = 3 * 12 + 4 * 0 + 4       # pad r1c4's rest red byte stored wrong
    outcome = rig.push()
    assert outcome.result is OutcomeKind.FAILED
    assert outcome.message == "write to slot 7 failed, restored from backup"
    assert rig.memory.slots[7] == loops and rig.engine.warnings == ["write to slot 7 failed, restored from backup"]
    assert rig.memory.writes(7) == [("write", 7), ("write", 7)]


def test_a_rollback_that_fails_names_the_backup():
    rig = Rig()
    rig.memory.mismatch[7] = 40

    def unplug_after_first(slot, record):
        rig.memory.gone_on_write.add(7)
    rig.memory.on_write = unplug_after_first
    outcome = rig.push()
    assert outcome.message == ("write to slot 7 failed and could not be restored; restore slot7-2026-10-24T20-15")


def test_no_answer_to_the_backup_read_writes_nothing():   # A5, d79
    rig = Rig()
    rig.memory.no_reply.add(7)
    outcome = rig.push()
    assert (outcome.result, outcome.message) == (OutcomeKind.FAILED, "could not back up slot 7; nothing written")
    assert rig.memory.writes() == [] and rig.backups.order == []


def test_not_held_reads_and_writes_nothing():   # A6, d70
    rig = Rig()
    rig.memory.held = False
    outcome = rig.push()
    assert outcome.message == "take control of the APC64 first; nothing read or written"
    assert outcome.code is OutcomeCode.NOT_HELD and rig.events == []


def test_a_short_dump_writes_nothing():   # A51 (application half), d66
    rig = Rig()
    rig.memory.short[7] = 700
    outcome = rig.push()
    assert outcome.message == "slot 7 read returned 700 bytes, expected 880; nothing written"
    assert rig.memory.writes() == []


def test_an_identical_record_writes_nothing():   # A52, d68
    rig = Rig()
    rig.push()
    rig.events.clear()
    outcome = rig.push()
    assert (outcome.result, outcome.message) == (OutcomeKind.UNCHANGED, "slot 7 unchanged; nothing written")
    assert rig.events == [("read", 7)] and outcome.backup is None


def test_an_unplug_mid_write_names_the_slot_and_its_backup():   # A54, d71
    rig = Rig()
    rig.memory.gone_on_write.add(7)
    outcome = rig.push()
    assert outcome.result is OutcomeKind.FAILED
    assert outcome.message == "slot 7 may be partial; restore slot7-2026-10-24T20-15"
    assert outcome.backup == "slot7-2026-10-24T20-15"


def test_a_second_command_during_a_push_is_busy():   # A7, d96
    rig = Rig()
    before = rig.memory.globals
    with rig.writer.command("push to slot 5"):
        outcome = rig.writer.write_globals(lambda g: g.with_change(GlobalChange.parse({"led_level": 100})),
                                           what="change the global settings", success=lambda b: "set",
                                           unchanged="LED level unchanged; nothing written")
    assert (outcome.result, outcome.message) == (OutcomeKind.REFUSED, "busy: push to slot 5 in progress")
    assert outcome.code is OutcomeCode.BUSY and rig.memory.globals == before and rig.events == []
    assert rig.writer.running is None


def test_a_refused_merge_writes_nothing_and_names_the_field():   # inv10
    rig = Rig()

    def bad(record):
        raise DomainInvariantError("transpose", "transpose +80 puts pad r8c8 at note 165", "notes are 0–127")
    outcome = rig.push(change=bad)
    assert outcome.result is OutcomeKind.REFUSED and outcome.field == "transpose"
    assert outcome.message == "transpose +80 puts pad r8c8 at note 165; notes are 0–127"
    assert rig.memory.writes() == [] and rig.backups.order == []


def test_a_backup_that_cannot_be_saved_writes_nothing():   # s14.c2
    rig = Rig()
    rig.backups.fail = "Permission denied"
    outcome = rig.push()
    assert outcome.code is OutcomeCode.STORAGE
    assert outcome.message == ("could not save the backup of slot 7 (backups/slot7.bin: Permission denied); "
                               "nothing written")
    assert rig.memory.writes() == []


def test_other_firmware_is_refused():   # a32
    rig = Rig()
    rig.memory.firmware = "1.2.1.7"
    outcome = rig.push()
    assert outcome.code is OutcomeCode.FIRMWARE and outcome.message.endswith("verified only on 1.2.1.6; nothing written")


def test_the_global_block_takes_the_same_path():   # inv1, inv4 for 0x18
    rig = Rig()
    change = GlobalChange.parse({"led_level": 100})
    outcome = rig.writer.write_globals(lambda g: g.with_change(change), what="change the global settings",
                                       success=lambda b: "LED level 100%", unchanged="unchanged")
    assert outcome.result is OutcomeKind.PUSHED and outcome.backup.startswith("globals-")
    assert rig.events[:3] == [("read", "globals"), ("backup", outcome.backup), ("write", "globals")]
    assert rig.backups.get(outcome.backup).target is GLOBALS and rig.memory.globals.led_percent == 100
    rig.memory.mismatch["globals"] = 55
    outcome = rig.writer.write_globals(lambda g: g.with_change(GlobalChange.parse({"led_level": 25})),
                                       what="x", success=lambda b: "ok", unchanged="unchanged")
    assert outcome.message == "write to the global settings failed, restored from backup"
    assert rig.memory.globals.led_percent == 100


def test_the_session_path_writes_slot_0_only_with_the_capability_and_no_backup():   # inv7 fast path
    rig = Rig()
    record = tonnetz_c(rig.memory.slots[0])
    rig.writer.session_write(record)
    assert rig.events == [("write", 0)] and rig.memory.slots[0] == record
    assert rig.writer.session_read() == record


def test_the_writer_declares_both_writes_scoped_to_its_one_capability():   # inv2
    rig = Rig()
    scoped = rig.writer.scoped_writes()
    assert set(scoped) == {SysexCommand.PROJECT_WRITE, SysexCommand.GLOBAL_WRITE}
    assert all(c is rig.capability for c in scoped.values()) and rig.writer.holds(rig.capability)
