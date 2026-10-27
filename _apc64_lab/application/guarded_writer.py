"""GuardedWriter: the only issuer of project (0x14) and global-settings (0x18) writes, and the sole holder of the
WriteCapability (contract §7.1, inv1–inv4, inv8, d67–d73, d96).

Command path (push, restore, import push, bulk edit, globals), one sequence under the single-writer lock:
    read the slot or block → back it up → merge the change onto it (unknown bytes kept) → unchanged? nothing
    written → write → read back → equal: done; different (or no answer): write the backup back, read it back,
    and warn on the page and OLED naming the slot or block (inv4).
A second command while one runs is refused 'busy: <the one running> in progress' (d96, A7).

Session fast path (§7.1, inv7): slot 0 only. session_write sends the record and returns once it is transmitted;
it takes no backup (the lab session took one before its first write) and no read-back (the session verifies
after a burst settles). It waits only while a command holds the unit's memory, so the session coalesces then.

Slot-0 decision (made in the build, inv4 vs §2.7 a5/q9): command writes keep inv4's rollback on a mismatch;
session writes never roll back — a slot 0 that matches nothing the lab wrote means the user changed projects, which SessionService handles (it ends quietly).
"""
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.outbound import SysexCommand

from ..domain.memory import (
    EDIT_BUFFER, GLOBALS, Backup, BackupId, BackupTarget, OutcomeCode, OutcomeKind, Slot, WriteOutcome,
    unchanged_message,
)
from ..domain.records import GlobalSettings, ProjectRecord, refusal_text
from .ports import (
    NOT_HELD_TEXT, BackupStore, Gone, HostLink, Interrupted, MalformedReply, MemoryFault, NoReply, NotHeld,
    StorageError, UnitMemory, WrongFirmware,
)

NOT_HELD_NOTHING = f"{NOT_HELD_TEXT}; nothing read or written"   # A6


class Busy(Exception):
    def __init__(self, what: str):
        self.what = what
        super().__init__(f"busy: {what} in progress")


def refused(message: str, code: OutcomeCode, field: str | None = None, fix: str | None = None,
            backup: BackupId | None = None) -> WriteOutcome:
    return WriteOutcome(OutcomeKind.REFUSED, message, backup, code, field, fix)


def failed(message: str, backup: BackupId | None = None, code: OutcomeCode = OutcomeCode.UNIT) -> WriteOutcome:
    return WriteOutcome(OutcomeKind.FAILED, message, backup, code)


def invalid(error: DomainInvariantError) -> WriteOutcome:
    return refused(refusal_text(error), OutcomeCode.INVALID, error.field, error.fix)


def busy(error: Busy) -> WriteOutcome:
    return refused(str(error), OutcomeCode.BUSY)


@dataclass(frozen=True)
class _Target:
    """A slot or the global block: its name in messages, its backup target, and how to read and write it."""
    name: str
    backup_target: BackupTarget
    read: Callable[[], object]
    write: Callable[[object], None]


class GuardedWriter:
    def __init__(self, memory: UnitMemory, backups: BackupStore, capability, link: HostLink | None = None,
                 wall: Callable[[], datetime] = datetime.now):
        self._memory, self._backups = memory, backups
        self._capability = capability
        self._link = link or HostLink()
        self._wall = wall
        self._io = threading.RLock()        # the unit's memory: one exchange at a time (commands and session)
        self._commands = threading.Lock()   # guards _running
        self._running: str | None = None

    # --- what the module declares to the gate -----------------------------------------------------------
    def scoped_writes(self) -> dict:
        """{PROJECT_WRITE: capability, GLOBAL_WRITE: capability} for LabModule.outbound_scoped() (inv2)."""
        return {SysexCommand.PROJECT_WRITE: self._capability, SysexCommand.GLOBAL_WRITE: self._capability}

    def holds(self, capability) -> bool:
        return capability is self._capability

    @property
    def memory(self) -> UnitMemory:
        return self._memory

    # --- locks ------------------------------------------------------------------------------------------
    @property
    def running(self) -> str | None:
        return self._running

    @contextmanager
    def command(self, what: str):
        """One memory command at a time (d96): raises Busy naming the one in progress."""
        with self._commands:
            if self._running is not None:
                raise Busy(self._running)
            self._running = what
        try:
            with self._io:
                yield
        finally:
            with self._commands:
                self._running = None

    @contextmanager
    def exchange(self):
        """The unit's memory for one read or write (session steps, and reads outside a command)."""
        with self._io:
            yield

    def abort(self) -> None:
        """A release is under way: waits in flight end at once (memory.abort)."""
        self._memory.abort()

    def resume(self) -> None:
        self._memory.resume()

    # --- reads ------------------------------------------------------------------------------------------
    def read_project(self, slot: Slot, interrupt=None) -> ProjectRecord:
        with self._io:
            return self._memory.read_project(Slot(slot), interrupt)

    def read_globals(self) -> GlobalSettings:
        with self._io:
            return self._memory.read_globals()

    def save_backup(self, target: BackupTarget, data: bytes) -> BackupId:
        return self._backups.save(Backup(target, bytes(data), self._wall()))

    # --- the command path -------------------------------------------------------------------------------
    def write_project(self, slot: Slot, change: Callable[[ProjectRecord], ProjectRecord], *, what: str,
                      success: Callable[[BackupId], str], kind: OutcomeKind = OutcomeKind.PUSHED) -> WriteOutcome:
        slot = Slot(slot)
        target = _Target(f"slot {int(slot)}", slot, lambda: self._memory.read_project(slot),
                         lambda record: self._memory.write_project(slot, record, self._capability))
        return self._guarded(target, change, success, unchanged_message(slot), kind, what)

    def write_globals(self, change: Callable[[GlobalSettings], GlobalSettings], *, what: str,
                      success: Callable[[BackupId], str], unchanged: str) -> WriteOutcome:
        target = _Target("the global settings", GLOBALS, self._memory.read_globals,
                         lambda settings: self._memory.write_globals(settings, self._capability))
        return self._guarded(target, change, success, unchanged, OutcomeKind.PUSHED, what)

    def _guarded(self, target: _Target, change, success, unchanged: str, kind: OutcomeKind,
                 what: str) -> WriteOutcome:
        try:
            with self.command(what):
                return self._pipeline(target, change, success, unchanged, kind)
        except Busy as error:
            return busy(error)

    def _pipeline(self, target: _Target, change, success, unchanged: str, kind: OutcomeKind) -> WriteOutcome:
        try:
            self._memory.check_writable()
        except NotHeld:
            return refused(NOT_HELD_NOTHING, OutcomeCode.NOT_HELD)
        except WrongFirmware as error:
            return refused(f"{error}; nothing written", OutcomeCode.FIRMWARE)
        # 1. the record read right before the write is the backup and the base of the merge (d69, d73)
        try:
            current = target.read()
        except NotHeld:
            return refused(NOT_HELD_NOTHING, OutcomeCode.NOT_HELD)
        except MalformedReply as error:
            return failed(f"{error.text(target.name)}; nothing written")                     # A51
        except (NoReply, Interrupted, Gone):
            return failed(f"could not back up {target.name}; nothing written")                # A5, d79
        # 2. merge (inv3: only the named fields change)
        try:
            intended = change(current)
        except DomainInvariantError as error:
            return invalid(error)
        if intended == current:
            return WriteOutcome(OutcomeKind.UNCHANGED, unchanged)                             # A52, d68, d94
        # 3. the backup, before anything is written (inv1, A1)
        try:
            backup_id = self._backups.save(Backup(target.backup_target, current.to_raw(), self._wall()))
        except StorageError as error:
            return refused(f"could not save the backup of {target.name} ({error.path}: {error.reason}); "
                           "nothing written", OutcomeCode.STORAGE)
        # 4. the write
        try:
            target.write(intended)
        except NotHeld:
            return failed(f"{NOT_HELD_TEXT}; nothing written", backup_id, OutcomeCode.NOT_HELD)
        except MemoryFault:
            return failed(f"{target.name} may be partial; restore {backup_id}", backup_id)    # A54, d71
        # 5. read-back, and the rollback of inv4
        if self._read_back(target) == intended:
            return WriteOutcome(kind, success(backup_id), backup_id)
        try:
            target.write(current)
            restored = self._read_back(target) == current
        except MemoryFault:
            restored = False
        if restored:
            message = f"write to {target.name} failed, restored from backup"                 # A4, d67
        else:
            message = f"write to {target.name} failed and could not be restored; restore {backup_id}"
        self._link.warn(message)
        return failed(message, backup_id)

    @staticmethod
    def _read_back(target: _Target):
        try:
            return target.read()
        except MemoryFault:
            return None

    # --- the session fast path (slot 0) -----------------------------------------------------------------
    def check_writable(self) -> None:
        self._memory.check_writable()

    def session_read(self, interrupt=None) -> ProjectRecord:
        with self._io:
            return self._memory.read_project(EDIT_BUFFER, interrupt)

    def session_write(self, record: ProjectRecord, allow: Callable[[], bool] | None = None) -> bool:
        """Slot 0 only; returns once transmitted (True), or False when `allow()` — asked once the unit's memory
        is ours — says the session no longer wants it. Raises the MemoryFault that stopped it."""
        with self._io:
            if allow is not None and not allow():
                return False
            self._memory.write_project(EDIT_BUFFER, record, self._capability)
            return True
