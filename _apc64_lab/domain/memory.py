"""Slots, backups, library entries and write outcomes (contract §7.1: impossible states unrepresentable).

A push to slot 25 or to slot 0 cannot be typed: StoredSlot accepts 1–24 only, and its refusals carry the
exact messages of A49/A50. Slot 0 (the live edit buffer) is written only by lab sessions (d63).
"""
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from _apc64_host.domain.issues import DomainInvariantError

SLOT_COUNT = 25          # 0–24 answer; 25+ do not (p3)
FULL_BACKUP_MAX_AGE = 600.0   # §2.7 a5/q9: a session reuses a full backup younger than 10 minutes


class Slot(int):
    """Any slot the unit answers: 0 (edit buffer) or 1–24."""

    def __new__(cls, value):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < SLOT_COUNT:
            raise DomainInvariantError("slot", f"slot {value}", "slots are 0–24", joiner=": ")
        return super().__new__(cls, value)

    @property
    def is_edit_buffer(self) -> bool:
        return self == 0

    def name(self) -> str:
        return f"slot{int(self)}"


EDIT_BUFFER = Slot(0)


class StoredSlot(Slot):
    """A saved project, 1–24: the only push and restore targets (d63, d65)."""

    def __new__(cls, value):
        if isinstance(value, int) and not isinstance(value, bool) and value == 0:
            raise DomainInvariantError("slot", "slot 0 is the live edit buffer",
                                       "activate the layout to play it there")
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value < SLOT_COUNT:
            raise DomainInvariantError("slot", f"slot {value}", "slots are 1–24", joiner=": ")
        return int.__new__(cls, value)

    @classmethod
    def parse(cls, value) -> "StoredSlot":
        """From a number or its text; the A49/A50 refusals otherwise."""
        text = str(value).strip()
        if isinstance(value, bool) or not text.lstrip("-").isdigit():
            raise DomainInvariantError("slot", f"slot {value}", "slots are 1–24", joiner=": ")
        return cls(int(text))


class Globals(StrEnum):
    """The global-settings block as a backup target."""
    BLOCK = "globals"


GLOBALS = Globals.BLOCK
BackupTarget = Slot | Globals


def target_name(target: BackupTarget) -> str:
    return "globals" if target is GLOBALS else Slot(target).name()


_STAMP = "%Y-%m-%dT%H-%M"
_BACKUP_ID = re.compile(r"^(slot(?:[0-9]|1[0-9]|2[0-4])|globals)-(\d{4}-\d\d-\d\dT\d\d-\d\d)(?:-(\d+))?$")
_SET_ID = re.compile(r"^set-(\d{4}-\d\d-\d\dT\d\d-\d\d)(?:-(\d+))?$")


class BackupId(str):
    """'slot7-2026-10-24T12-00' (d76: named by date and slot); a '-2' suffix tells same-minute backups apart."""

    def __new__(cls, value):
        value = str(value)
        if not _BACKUP_ID.match(value):
            raise DomainInvariantError("backup", f"'{value}' is not a backup name",
                                       "backups are named like slot7-2026-10-24T12-00 or globals-2026-10-24T12-00")
        return super().__new__(cls, value)

    @classmethod
    def of(cls, target: BackupTarget, taken_at: datetime, serial: int = 1) -> "BackupId":
        return cls(f"{target_name(target)}-{taken_at.strftime(_STAMP)}" + (f"-{serial}" if serial > 1 else ""))

    @property
    def target(self) -> BackupTarget:
        name = _BACKUP_ID.match(self).group(1)
        return GLOBALS if name == "globals" else Slot(int(name.removeprefix("slot")))


class BackupSetId(str):
    """'set-2026-10-24T12-00': one 'back up all' (d74)."""

    def __new__(cls, value):
        value = str(value)
        if not _SET_ID.match(value):
            raise DomainInvariantError("backup set", f"'{value}' is not a backup set name",
                                       "backup sets are named like set-2026-10-24T12-00")
        return super().__new__(cls, value)

    @classmethod
    def of(cls, taken_at: datetime, serial: int = 1) -> "BackupSetId":
        return cls(f"set-{taken_at.strftime(_STAMP)}" + (f"-{serial}" if serial > 1 else ""))


@dataclass(frozen=True)
class Backup:
    """The bytes of one slot or the global block, read from the unit just before an overwrite (d73)."""
    target: BackupTarget
    data: bytes
    taken_at: datetime

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def full_backup_due(last_full_backup_at: float | None, now: float) -> bool:
    """§2.7 a5/q9: each lab session backs up slots 1–24, unless a full backup is younger than 10 minutes."""
    return last_full_backup_at is None or now - last_full_backup_at >= FULL_BACKUP_MAX_AGE


class EntryKind(StrEnum):
    DEFINITION = "definition"     # a generated-layout definition (a layout file with a lab: section)
    CAPTURED = "captured"         # a project read from a slot (d83)
    IMPORTED = "imported"         # an Akai .APC64 preset (d84)


@dataclass(frozen=True)
class LibraryEntry:
    """One named library entry (d81). Captured and imported entries carry their 880-byte record."""
    name: str
    kind: EntryKind
    record: object | None = None   # ProjectRecord for captured/imported entries
    layout: str | None = None      # the layout id for a definition
    source: str | None = None      # slot or file it came from

    def __post_init__(self):
        if not str(self.name).strip():
            raise DomainInvariantError("name", "the library entry has no name", "give it a name, e.g. 'Live set B'")
        if self.kind is EntryKind.DEFINITION and not self.layout:
            raise DomainInvariantError("layout", "a definition entry names its layout", "give the layout id")
        if self.kind is not EntryKind.DEFINITION and self.record is None:
            raise DomainInvariantError("record", f"a {self.kind} entry carries its project record",
                                       "capture or import the record first")


class OutcomeKind(StrEnum):
    PUSHED = "pushed"
    RESTORED = "restored"
    UNCHANGED = "unchanged"
    REFUSED = "refused"
    FAILED = "failed"
    BACKED_UP = "backed_up"      # backup all / one slot: read and stored, nothing written
    STORED = "stored"            # capture, import, or a library-entry edit: stored, nothing written
    ACTIVATED = "activated"      # a layout or preview made live in slot 0 through a lab session


class OutcomeCode(StrEnum):
    """Why a command was refused or failed, for the API's status mapping (the message stays the one text)."""
    INVALID = "invalid"          # a slot, entry, field or value is wrong (400)
    BUSY = "busy"                # another memory command is running (409, d96)
    NOT_HELD = "not_held"        # the host does not hold the unit (409, d70)
    FIRMWARE = "firmware"        # the unit reports other firmware than the verified one (a32)
    NOT_FOUND = "not_found"      # no such backup or library entry
    TAKEN = "taken"              # the library name is in use (d82)
    CORRUPT = "corrupt"          # a backup or library file is not a whole record (d77)
    STORAGE = "storage"          # a file could not be written (s14.c2)
    UNIT = "unit"                # the unit did not answer, answered short, went away or read back wrong
    SESSION = "session"          # slot 0 belongs to the running lab session, or a recovery is pending


@dataclass(frozen=True)
class WriteOutcome:
    """Every memory command's answer, the same on the CLI, API and page (§3.5: {result, backup, message}).
    `code`, `field` and `fix` are for the API's 4xx mapping ({problem, fix, field}); to_json is §3.5's shape."""
    result: OutcomeKind
    message: str
    backup: BackupId | None = None
    code: OutcomeCode | None = None
    field: str | None = None
    fix: str | None = None
    extra: dict | None = None    # what the command produced besides the message (a set id, a summary)

    @property
    def ok(self) -> bool:
        return self.result not in (OutcomeKind.REFUSED, OutcomeKind.FAILED)

    def to_json(self) -> dict:
        return {"result": str(self.result), "backup": self.backup, "message": self.message}


def pushed_message(slot: StoredSlot) -> str:
    """d62, A60: 'pushed to slot 7; takes effect when project 7 is next loaded'."""
    return f"pushed to slot {int(slot)}; takes effect when project {int(slot)} is next loaded"


def unchanged_message(slot: Slot) -> str:
    return f"slot {int(slot)} unchanged; nothing written"   # A52
