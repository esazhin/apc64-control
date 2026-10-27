"""T26: ProjectMemory over fakes (s13 and s15 collaboration, s31 supplier; inv1, inv8, inv9; A45, A46, A47, A48,
A49, A50, A53, A55–A60; §2.7 q1, q3, q4, q5; d63, d74–d83)."""
from datetime import timedelta

from _apc64_host.domain.outbound import WriteCapability
from _apc64_host.notation.compiler import compile_text
from _apc64_lab.application.conftest import (
    LOOPS_TAG, EngineDouble, Events, FakeBackups, FakeLibrary, FakeMemory, Wall, host_ports, named,
)
from _apc64_lab.application.guarded_writer import GuardedWriter
from _apc64_lab.application.ports import SET_ALL, Corrupt, HostLink
from _apc64_lab.application.project_memory import ProjectMemory
from _apc64_lab.application.registry import DefinitionIndex, GeneratorRegistry
from _apc64_lab.application.section_compiler import LabSectionCompiler
from _apc64_lab.domain.generators import FifthsHue, TonnetzCheckerboard, generate
from _apc64_lab.domain.memory import (
    GLOBALS, Backup, BackupId, EntryKind, LibraryEntry, OutcomeCode, OutcomeKind, Slot,
)
from _apc64_lab.domain.pads import Rgb
from _apc64_lab.domain.test_apc64_preset import file_of, items_of

TONNETZ_C = generate(TonnetzCheckerboard(), {"base": 48, "channel": 1}, FifthsHue())
PUSHED_7 = "pushed to slot 7; takes effect when project 7 is next loaded"


class SessionStub:
    def __init__(self):
        self.running, self.window, self.recovered_ids, self.previews, self.activated = False, None, [], [], []

    def transposition_of(self, layout_id):
        return self.window

    def recovered(self, backup_id):
        self.recovered_ids.append(str(backup_id))

    def preview(self, name, record):
        self.previews.append((name, record))
        return "previewing"

    def activate(self, layout_id):
        self.activated.append(layout_id)
        return "activated"


class Rig:
    def __init__(self):
        self.events = Events()
        self.memory, self.backups, self.library = FakeMemory(self.events), FakeBackups(self.events), FakeLibrary()
        self.engine = EngineDouble()
        self.wall = Wall()
        self.writer = GuardedWriter(self.memory, self.backups, WriteCapability("t"), HostLink(host_ports(self.engine)),
                                    self.wall)
        self.registry = GeneratorRegistry().load()
        self.index = DefinitionIndex()
        compiler = LabSectionCompiler(self.registry.generators, self.registry.schemes, None, self.index.record)
        compile_text("name: Tonnetz C\nlab:\n  generator: tonnetz\n  base: 48\n", "tonnetz-c.yaml",
                     sections={"lab": compiler})
        self.index.named("tonnetz-c", "Tonnetz C")
        self.session = SessionStub()
        self.memory_service = ProjectMemory(self.writer, self.backups, self.library, self.registry, self.index,
                                            self.session, self.wall)


def test_backup_all_saves_slots_0_to_24_and_the_globals_as_one_set():   # A45, d74
    rig = Rig()
    outcome = rig.memory_service.backup_all()
    assert outcome.result is OutcomeKind.BACKED_UP
    assert outcome.message == "backed up slots 0–24 and the global settings as set-2026-10-24T20-15"
    (full,) = rig.backups.sets()
    assert full.kind == SET_ALL and [name for name, _ in full.members] == [f"slot{n}" for n in range(25)] + ["globals"]
    assert rig.memory.writes() == []


def test_backup_all_without_holding_the_unit():   # A6
    rig = Rig()
    rig.memory.held = False
    assert rig.memory_service.backup_all().message == "take control of the APC64 first; nothing read or written"
    assert rig.backups.sets() == []


def test_a_backup_equal_to_the_newest_is_not_duplicated():   # A46, d78
    rig = Rig()
    for minute in range(40):
        data = rig.memory.slots[7].raw if minute == 39 else named(rig.memory.slots[7], minute + 100).raw
        rig.backups.save(Backup(Slot(7), data, rig.wall.now - timedelta(minutes=40 - minute)))
    outcome = rig.memory_service.backup(7)
    assert outcome.result is OutcomeKind.UNCHANGED and "no new backup" in outcome.message
    assert len(rig.backups.list(Slot(7))) == 40


def test_a_corrupt_backup_is_refused_and_the_slot_unchanged():   # A47, d77
    rig = Rig()
    rig.backups.corrupt["slot7-2026-10-24T12-00"] = Corrupt("slot7-2026-10-24T12-00", "holds 512 bytes, expected 880")
    before = rig.memory.slots[7]
    outcome = rig.memory_service.restore("slot7-2026-10-24T12-00", 7)
    assert outcome.message == "slot7-2026-10-24T12-00 holds 512 bytes, expected 880; not restored"
    assert outcome.code is OutcomeCode.CORRUPT and rig.memory.slots[7] == before


def test_restore_backs_up_the_current_project_first():   # A48, inv1
    rig = Rig()
    loops = rig.memory.slots[7]
    old = rig.backups.save(Backup(Slot(7), loops.raw, rig.wall.now - timedelta(hours=8)))
    rig.memory.slots[7] = loops.with_pads(TONNETZ_C)
    rig.events.clear()
    outcome = rig.memory_service.restore(old, 7)
    assert outcome.result is OutcomeKind.RESTORED
    assert outcome.message == f"restored slot 7 from {old}; takes effect when project 7 is next loaded"
    assert rig.events[1][0] == "backup" and rig.backups.get(outcome.backup).data == loops.with_pads(TONNETZ_C).raw
    assert rig.memory.slots[7] == loops


def test_slot_0_is_restored_only_from_a_slot_0_backup_and_not_during_a_session():   # d63, a8
    rig = Rig()
    stored = rig.backups.save(Backup(Slot(7), rig.memory.slots[7].raw, rig.wall.now))
    assert rig.memory_service.restore(stored, 0).message.startswith("slot 0 is restored only from a slot-0 backup")
    session_backup = rig.backups.save(Backup(Slot(0), named(rig.memory.slots[0], 55).raw, rig.wall.now))
    rig.session.running = True
    assert rig.memory_service.restore(session_backup, 0).code is OutcomeCode.SESSION
    rig.session.running = False
    outcome = rig.memory_service.restore(session_backup, 0)
    assert outcome.result is OutcomeKind.RESTORED and rig.session.recovered_ids == [session_backup]
    assert outcome.message.endswith("the unit shows the project as unsaved, nothing was saved")


def test_globals_backups_restore_to_the_global_block_only():
    rig = Rig()
    gid = rig.backups.save(Backup(GLOBALS, rig.memory.globals.raw, rig.wall.now))
    assert rig.memory_service.restore(gid, 7).code is OutcomeCode.INVALID
    assert rig.memory_service.restore(gid, "globals").result is OutcomeKind.UNCHANGED


def test_push_refuses_slots_outside_1_to_24():   # A49, A50, d63, d65
    rig = Rig()
    assert rig.memory_service.push("Tonnetz C", 25).message == "slot 25: slots are 1–24"
    assert rig.memory_service.push("Tonnetz C", 0).message == (
        "slot 0 is the live edit buffer; activate the layout to play it there")
    assert rig.events == []


def test_the_page_and_the_agent_push_alike():   # A60, inv9
    rig = Rig()
    first = rig.memory_service.push("Tonnetz C", 7)
    second = rig.memory_service.push("tonnetz-c", 8)
    assert (first.message, second.message) == (PUSHED_7, "pushed to slot 8; takes effect when project 8 is next loaded")
    assert first.backup.startswith("slot7-") and second.backup.startswith("slot8-")


def test_push_stores_the_layout_where_it_currently_sits():   # §2.7 q3
    rig = Rig()
    rig.session.window = 14                            # '5th +2' on the pads
    rig.memory_service.push("Tonnetz C", 7)
    assert rig.memory.slots[7].pads[0].note == 62
    rig.memory_service.push("Tonnetz C", 8, offset=0)  # an explicit offset overrides it
    assert rig.memory.slots[8].pads[0].note == 48
    refused = rig.memory_service.push("Tonnetz C", 9, offset=60)
    assert refused.field == "offset" and refused.message.startswith("offset +60 puts the pads outside 0–127")


def test_a_push_backs_up_what_the_unit_holds_right_before():   # A53, d69
    rig = Rig()
    rig.memory.slots[7] = named(rig.memory.slots[7], 120)          # 12:00: recoloured and saved on the unit
    rig.wall.advance(minutes=5)
    outcome = rig.memory_service.push("Tonnetz C", 7)
    assert rig.backups.get(outcome.backup).data == named(FakeMemory().slots[7], 120).raw


def test_capture_and_a_taken_name():   # A58, A59, d82, d83
    rig = Rig()
    rig.memory.slots[12] = named(rig.memory.slots[12], 12)
    outcome = rig.memory_service.capture(12, "Live set B")
    assert (outcome.result, outcome.message) == (OutcomeKind.STORED, 'saved slot 12 to the library as "Live set B"')
    listed = {e["name"]: e for e in rig.memory_service.library()}
    assert listed["Live set B"]["kind"] == "captured" and listed["Tonnetz C"]["kind"] == "definition"
    again = rig.memory_service.capture(13, "Live set B")
    assert again.message == 'name "Live set B" is already in the library' and again.code is OutcomeCode.TAKEN
    assert rig.memory_service.capture(13, "tonnetz c").message == 'name "Tonnetz C" is already in the library'


def test_import_lists_the_preset_and_writes_nothing():   # A55, A56, A57 (application half), d84–d87
    rig = Rig()
    data = file_of(items_of(rig.memory.slots[3].raw))
    outcome = rig.memory_service.import_preset(None, data, "Boss RC-600.APC64")
    assert outcome.message == 'imported "Boss RC-600" (64 pads, 8 strips); nothing written to the unit'
    assert rig.library.get("Boss RC-600").kind is EntryKind.IMPORTED and rig.events == []
    short = file_of(items_of(rig.memory.slots[3].raw)[:580])
    assert rig.memory_service.import_preset("x", short).message == "580 items, expected 592"


def test_a_captured_entry_is_pushed_keeping_the_slots_unknown_bytes():   # inv3
    rig = Rig()
    source = named(rig.memory.slots[12], 12)
    rig.library.put(LibraryEntry("Live set B", EntryKind.CAPTURED, source, source="slot 12"))
    raw = bytearray(rig.memory.slots[7].raw)
    raw[11] = 0x05
    rig.memory.slots[7] = type(source)(bytes(raw))
    rig.memory_service.push("Live set B", 7)
    after = rig.memory.slots[7]
    assert after.pads[0].unknown == 0x05 and after.pads[5].rest == Rgb(12, 12, 12)


def test_bulk_edits_go_through_the_guarded_path():   # §2.7 q1
    rig = Rig()
    outcome = rig.memory_service.bulk_edit(5, "all pads channel 3")
    assert outcome.message == "edited slot 5 (all pads channel 3); takes effect when project 5 is next loaded"
    assert all(p.channel == 3 for p in rig.memory.slots[5].pads) and outcome.backup.startswith("slot5-")
    assert rig.events[:3] == [("read", 5), ("backup", outcome.backup), ("write", 5)]
    bad = rig.memory_service.bulk_edit(5, "all pads channel 17")
    assert bad.result is OutcomeKind.REFUSED and rig.memory.writes(5) == [("write", 5)]


def test_bulk_edit_of_a_library_entry_stores_it_back():   # §2.7 q1
    rig = Rig()
    rig.library.put(LibraryEntry("Live set B", EntryKind.CAPTURED, rig.memory.slots[12], source="slot 12"))
    outcome = rig.memory_service.bulk_edit("Live set B", ["pads r1c1-r2c8 colour red"])
    assert outcome.result is OutcomeKind.STORED and rig.events == []
    assert rig.library.get("Live set B").record.pads[0].rest == Rgb(255, 0, 0)


def test_a_slot_reads_as_decoded_record_and_raw_hex():   # §3.5 GET /api/lab/slots/{n}
    rig = Rig()
    found = rig.memory_service.slot(7)
    assert found["slot"] == 7 and len(found["pads"]) == 64 and len(found["strips"]) == 8
    assert bytes.fromhex(found["raw"]) == rig.memory.slots[7].raw
    assert rig.memory_service.slot(25).message == "slot 25: slots are 0–24"


def test_previews_go_to_the_session():   # §2.7 q4
    rig = Rig()
    rig.library.put(LibraryEntry("Live set B", EntryKind.CAPTURED, rig.memory.slots[12], source="slot 12"))
    assert rig.memory_service.preview("Live set B") == "previewing"
    assert rig.memory_service.preview("Tonnetz C") == "activated" and rig.session.activated == ["tonnetz-c"]
