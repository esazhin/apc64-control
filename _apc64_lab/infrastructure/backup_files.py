"""BackupStore over files in backups/ (contract s13 supplier, s14; inv1; d73–d78; a8; A46, A47).

    backups/slot7-2026-10-24T12-00.bin       the raw bytes (880 for a slot, 56 for the global block)
    backups/slot7-2026-10-24T12-00-2.bin     a second backup of slot 7 in the same minute
    backups/sets/set-2026-10-24T12-00.json   one 'back up all' or a session's full backup: its members
    backups/open-session.json                the open-session marker of a running lab session (a8)

Names are by date and slot (d76); backups are kept without limit. A backup whose bytes equal the newest backup of
the same target is recorded once (d78): its id is returned again. Every file is written to a temporary name and
moved into place with os.replace, so a crash never leaves a partial backup (s14.c1); an OSError becomes a
StorageError naming the path (s14.c2). A file that is not a whole record is reported Corrupt on get (d77, A47).
The directory is git-ignored.
"""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from _apc64_host.domain.issues import DomainInvariantError

from ..application.ports import BackupInfo, BackupSet, Corrupt, StorageError
from ..domain.memory import GLOBALS, Backup, BackupId, BackupSetId, BackupTarget, target_name
from ..domain.records import GLOBAL_SIZE, PROJECT_SIZE

MARKER = "open-session.json"
_STAMP = "%Y-%m-%dT%H-%M"


def _stamp_of(backup_id: str) -> tuple[str, int]:
    """('2026-10-24T12-00', serial) of 'slot7-2026-10-24T12-00[-2]'."""
    parts = backup_id.split("-")
    name_free = "-".join(parts[1:])                       # '2026-10-24T12-00[-2]'
    pieces = name_free.split("-")
    if len(pieces) == 5:
        return "-".join(pieces[:4]), int(pieces[4])
    return name_free, 1


def write_atomically(path: Path, data: bytes) -> None:
    """Write to a temporary sibling, then os.replace it into place (s14.c1)."""
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError as error:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise StorageError(path, error.strerror or str(error)) from None


class BackupFiles:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    # --- paths ------------------------------------------------------------------------------------------
    def _path(self, backup_id: str) -> Path:
        return self.root / f"{backup_id}.bin"

    def _ids(self, target: BackupTarget | None = None) -> list[BackupId]:
        if not self.root.is_dir():
            return []
        found = []
        for path in self.root.glob("*.bin"):
            try:
                backup_id = BackupId(path.stem)
            except DomainInvariantError:
                continue                                   # not one of ours
            if target is None or backup_id.target == target:
                found.append(backup_id)
        return sorted(found, key=lambda i: (_stamp_of(i)[0], target_name(i.target), _stamp_of(i)[1]))

    # --- BackupStore ------------------------------------------------------------------------------------
    def save(self, backup: Backup) -> BackupId:
        same_target = self._ids(backup.target)
        if same_target:
            newest = same_target[-1]
            try:
                if self._path(newest).read_bytes() == backup.data:
                    return newest                          # d78: recorded once
            except OSError:
                pass
        serial = 1
        while self._path(backup_id := BackupId.of(backup.target, backup.taken_at, serial)).exists():
            serial += 1
        write_atomically(self._path(backup_id), backup.data)
        return backup_id

    def save_set(self, members, kind: str, taken_at: datetime, complete: bool = True) -> BackupSetId:
        sets = self.root / "sets"
        serial = 1
        while (sets / f"{(set_id := BackupSetId.of(taken_at, serial))}.json").exists():
            serial += 1
        members = [str(BackupId(m)) for m in members]
        body = {"id": str(set_id), "taken_at": taken_at.isoformat(timespec="seconds"), "kind": kind,
                "complete": bool(complete),
                "members": [[target_name(BackupId(m).target), m] for m in members]}
        write_atomically(sets / f"{set_id}.json", json.dumps(body, indent=1).encode())
        return set_id

    def get(self, backup_id) -> Backup | Corrupt | None:
        backup_id = BackupId(backup_id)
        try:
            data = self._path(backup_id).read_bytes()
        except FileNotFoundError:
            return None
        except OSError as error:
            return Corrupt(str(backup_id), f"cannot be read ({error.strerror or error})")
        expected = GLOBAL_SIZE if backup_id.target is GLOBALS else PROJECT_SIZE
        if len(data) != expected:
            return Corrupt(str(backup_id), f"holds {len(data)} bytes, expected {expected}")   # A47
        return Backup(backup_id.target, data, datetime.strptime(_stamp_of(backup_id)[0], _STAMP))

    def list(self, target: BackupTarget | None = None) -> list[BackupInfo]:
        listed = []
        for backup_id in self._ids(target):
            try:
                data = self._path(backup_id).read_bytes()
            except OSError:
                continue
            listed.append(BackupInfo(backup_id, backup_id.target, datetime.strptime(_stamp_of(backup_id)[0], _STAMP),
                                     len(data), hashlib.sha256(data).hexdigest()))
        return listed

    def sets(self) -> list[BackupSet]:
        folder = self.root / "sets"
        if not folder.is_dir():
            return []
        found = []
        for path in sorted(folder.glob("set-*.json")):
            try:
                body = json.loads(path.read_text())
                found.append(BackupSet(BackupSetId(body["id"]), datetime.fromisoformat(body["taken_at"]),
                                       str(body["kind"]), tuple((str(n), BackupId(i)) for n, i in body["members"]),
                                       bool(body.get("complete", True))))
            except (OSError, ValueError, KeyError, TypeError, DomainInvariantError):
                continue                                   # a damaged manifest is not a full backup
        return sorted(found, key=lambda s: s.taken_at)

    def last_full_backup_at(self) -> datetime | None:
        full = [s.taken_at for s in self.sets() if s.covers_stored_slots]
        return max(full) if full else None

    # --- the open-session marker (a8) -------------------------------------------------------------------
    def open_session(self, backup_id) -> None:
        body = {"backup": str(BackupId(backup_id)), "opened_at": datetime.now().isoformat(timespec="seconds")}
        write_atomically(self.root / MARKER, json.dumps(body).encode())

    def close_session(self) -> None:
        try:
            (self.root / MARKER).unlink(missing_ok=True)
        except OSError as error:
            raise StorageError(self.root / MARKER, error.strerror or str(error)) from None

    def open_session_left(self) -> BackupId | None:
        try:
            return BackupId(json.loads((self.root / MARKER).read_text())["backup"])
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError, DomainInvariantError):
            return None
