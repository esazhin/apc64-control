"""T31: BackupStore files on tmp_path (s13 supplier, s14; A46, A47; d76–d78; a8)."""
import os
from datetime import datetime, timedelta

import pytest

from _apc64_lab.application.ports import SET_ALL, SET_SESSION, BackupStore, Corrupt, StorageError
from _apc64_lab.domain.memory import GLOBALS, Backup, Slot
from _apc64_lab.infrastructure.backup_files import BackupFiles

NOON = datetime(2026, 10, 24, 12, 0)


def raw(tag: int, size: int = 880) -> bytes:
    return bytes([tag]) * size


def test_files_implement_the_port_and_round_trip(tmp_path):
    store = BackupFiles(tmp_path / "backups")
    assert isinstance(store, BackupStore)
    backup_id = store.save(Backup(Slot(7), raw(1), NOON))
    assert backup_id == "slot7-2026-10-24T12-00" and (tmp_path / "backups" / "slot7-2026-10-24T12-00.bin").exists()
    got = store.get(backup_id)
    assert got.data == raw(1) and got.target == 7 and got.taken_at == NOON
    assert store.get("slot7-2026-10-24T13-00") is None


def test_forty_backups_stay_forty_when_the_newest_equals_the_slot(tmp_path):   # A46, d76, d78
    store = BackupFiles(tmp_path)
    for i in range(40):
        store.save(Backup(Slot(7), raw(i), NOON + timedelta(minutes=i)))
    again = store.save(Backup(Slot(7), raw(39), NOON + timedelta(hours=2)))
    listed = store.list(Slot(7))
    assert len(listed) == 40 and again == listed[-1].id == "slot7-2026-10-24T12-39"
    assert store.save(Backup(Slot(7), raw(0), NOON + timedelta(hours=2))) == "slot7-2026-10-24T14-00"   # older bytes: new


def test_same_minute_backups_get_a_serial(tmp_path):
    store = BackupFiles(tmp_path)
    assert store.save(Backup(Slot(3), raw(1), NOON)) == "slot3-2026-10-24T12-00"
    assert store.save(Backup(Slot(3), raw(2), NOON)) == "slot3-2026-10-24T12-00-2"
    assert [b.id for b in store.list(Slot(3))] == ["slot3-2026-10-24T12-00", "slot3-2026-10-24T12-00-2"]


def test_a_short_file_is_corrupt(tmp_path):   # A47, d77
    (tmp_path / "slot7-2026-10-24T12-00.bin").write_bytes(raw(5, 512))
    found = BackupFiles(tmp_path).get("slot7-2026-10-24T12-00")
    assert isinstance(found, Corrupt)
    assert found.text() == "slot7-2026-10-24T12-00 holds 512 bytes, expected 880; not restored"


def test_the_global_block_is_56_bytes(tmp_path):
    store = BackupFiles(tmp_path)
    gid = store.save(Backup(GLOBALS, raw(2, 56), NOON))
    assert gid == "globals-2026-10-24T12-00" and store.get(gid).target is GLOBALS


def test_sets_and_the_last_full_backup(tmp_path):   # d74, §2.7 a5/q9
    store = BackupFiles(tmp_path)
    members = [store.save(Backup(Slot(n), raw(n), NOON)) for n in range(1, 25)]
    assert store.last_full_backup_at() is None
    partial = store.save_set(members[:3], SET_SESSION, NOON, complete=False)
    full = store.save_set(members, SET_ALL, NOON + timedelta(seconds=30))
    assert (partial, full) == ("set-2026-10-24T12-00", "set-2026-10-24T12-00-2")
    assert store.last_full_backup_at() == NOON + timedelta(seconds=30)
    assert [s.kind for s in store.sets()] == [SET_SESSION, SET_ALL] and store.sets()[1].covers_stored_slots


def test_the_open_session_marker_is_kept_and_cleared(tmp_path):   # a8
    store = BackupFiles(tmp_path)
    assert store.open_session_left() is None
    store.open_session("slot0-2026-10-24T20-15")
    assert BackupFiles(tmp_path).open_session_left() == "slot0-2026-10-24T20-15"   # survives a restart
    store.close_session()
    store.close_session()
    assert store.open_session_left() is None


def test_writes_leave_no_partial_file(tmp_path):   # s14.c1
    store = BackupFiles(tmp_path)
    store.save(Backup(Slot(1), raw(1), NOON))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["slot1-2026-10-24T12-00.bin"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_a_read_only_directory_is_a_storage_error_naming_the_path(tmp_path):   # s14.c2
    folder = tmp_path / "ro"
    folder.mkdir()
    folder.chmod(0o500)
    try:
        with pytest.raises(StorageError) as error:
            BackupFiles(folder).save(Backup(Slot(1), raw(1), NOON))
        assert str(folder / "slot1-2026-10-24T12-00.bin") in error.value.path and error.value.reason
        assert list(folder.iterdir()) == []
    finally:
        folder.chmod(0o700)
