"""Slots, backups and outcomes (T4)."""
from datetime import datetime

import pytest

from _apc64_host.domain.issues import DomainInvariantError
from _apc64_lab.domain.memory import (
    GLOBALS, Backup, BackupId, BackupSetId, EntryKind, LibraryEntry, OutcomeKind, Slot, StoredSlot, WriteOutcome,
    full_backup_due, pushed_message, unchanged_message,
)
from _apc64_lab.domain.records import refusal_text


def test_slot_25_is_refused():   # A49, d65
    with pytest.raises(DomainInvariantError) as error:
        StoredSlot.parse(25)
    assert refusal_text(error.value) == "slot 25: slots are 1–24"
    with pytest.raises(DomainInvariantError):
        Slot(25)


def test_slot_0_is_not_a_push_target():   # A50, d63
    with pytest.raises(DomainInvariantError) as error:
        StoredSlot.parse("0")
    assert refusal_text(error.value) == "slot 0 is the live edit buffer; activate the layout to play it there"
    assert Slot(0).is_edit_buffer and StoredSlot.parse("7") == 7 and isinstance(StoredSlot(7), Slot)


def test_backup_names_carry_target_and_minute():   # d76, A43, A47
    taken = datetime(2026, 10, 24, 20, 15, 42)
    assert BackupId.of(Slot(0), taken) == "slot0-2026-10-24T20-15"
    assert BackupId.of(GLOBALS, taken, serial=2) == "globals-2026-10-24T20-15-2"
    assert BackupId("slot7-2026-10-24T12-00").target == Slot(7)
    assert BackupId("globals-2026-10-24T12-00").target is GLOBALS
    assert BackupSetId.of(taken) == "set-2026-10-24T20-15"
    with pytest.raises(DomainInvariantError):
        BackupId("slot25-2026-10-24T12-00")


def test_a_backup_hashes_its_bytes():   # d78 (identical backups are recorded once, by hash)
    one = Backup(Slot(7), b"abc", datetime(2026, 10, 24))
    assert one.sha256 == Backup(Slot(7), b"abc", datetime(2026, 10, 25)).sha256


def test_outcomes_and_their_messages():   # §3.5, A52, A60
    outcome = WriteOutcome(OutcomeKind.PUSHED, pushed_message(StoredSlot(7)), BackupId("slot7-2026-10-24T12-00"))
    assert outcome.to_json() == {"result": "pushed", "backup": "slot7-2026-10-24T12-00",
                                 "message": "pushed to slot 7; takes effect when project 7 is next loaded"}
    assert unchanged_message(Slot(7)) == "slot 7 unchanged; nothing written"


def test_each_session_takes_a_full_backup_unless_one_is_younger_than_10_minutes():   # §2.7 a5/q9
    assert full_backup_due(None, 1000.0)
    assert not full_backup_due(1000.0, 1000.0 + 599)
    assert full_backup_due(1000.0, 1000.0 + 600)


def test_library_entries_carry_what_they_need():   # d81
    assert LibraryEntry("Tonnetz C", EntryKind.DEFINITION, layout="tonnetz-c").layout == "tonnetz-c"
    with pytest.raises(DomainInvariantError):
        LibraryEntry("Live set B", EntryKind.CAPTURED)
    with pytest.raises(DomainInvariantError):
        LibraryEntry(" ", EntryKind.DEFINITION, layout="x")
