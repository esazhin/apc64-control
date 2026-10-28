"""The lab's ports (contract §7 ports): what its use cases need from the unit's memory, the backup and library
files, plugin discovery, the page and the host, as structural Protocols.

Adapters implement them (infrastructure/unit_memory.py, backup_files.py, library_files.py, plugin_discovery.py,
presentation/publisher.py); services take them in their constructors and never import an adapter.

Interpretation (a build decision): the memory faults of s6.c3 (NoReply, Malformed, NotHeld, Gone,
WrongFirmware) are raised as typed exceptions rather than returned, so the guarded write pipeline reads as one
sequence. Each carries the text the contract gives it.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Protocol, runtime_checkable

from _apc64_host.application.ports import HostPorts
from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.oled import OledText

from ..domain.memory import Backup, BackupId, BackupSetId, BackupTarget, LibraryEntry, Slot, target_name
from ..domain.memory_sysex import Malformed
from ..domain.records import GlobalSettings, ProjectRecord

READ_TIMEOUT = 2.0   # A5: no answer within 2 s is NoReply
NOT_HELD_TEXT = "take control of the APC64 first"


# --- unit memory faults (s6.c3) --------------------------------------------------------------------------
class MemoryFault(Exception):
    """A unit-memory call that did not complete. `text(what)` names what was being read or written."""

    def text(self, what: str) -> str:
        return f"{what}: {self}"


class NoReply(MemoryFault):
    """The unit did not answer a read within the timeout (A5)."""


class MalformedReply(MemoryFault):
    """The reply did not unpack to a whole record (A51: 700 of 880 bytes)."""

    def __init__(self, malformed: Malformed):
        self.malformed = malformed
        super().__init__(f"read returned {malformed.received} bytes, expected {malformed.expected}")

    def text(self, what: str) -> str:
        return self.malformed.text(what)


class NotHeld(MemoryFault):
    """The host does not hold the unit (d70, A6)."""

    def __init__(self, message: str = NOT_HELD_TEXT):
        super().__init__(message)


class Gone(MemoryFault):
    """The unit went away during the call (unplugged, released), or the call was aborted by a release."""


class WrongFirmware(MemoryFault):
    """The held unit reports another firmware than the one the record layouts are verified on (a32)."""

    def __init__(self, firmware: str, known: str):
        self.firmware, self.known = firmware, known
        super().__init__(f"the APC64 reports firmware {firmware}; memory writes are verified only on {known}")


class Interrupted(MemoryFault):
    """The caller's interrupt() asked to stop waiting (a newer slot-0 write is due, inv7)."""


class Refused(MemoryFault):
    """The outbound gate refused the frame (a write without the capability: never expected on this path)."""


# --- the unit --------------------------------------------------------------------------------------------
@runtime_checkable
class UnitMemory(Protocol):
    """The unit's project slots and global block (s6.c1). Every call raises a MemoryFault on failure."""

    def check_writable(self) -> None:
        """NotHeld when the unit is not held, WrongFirmware when its firmware is not the verified one."""
        ...

    def read_project(self, slot: Slot, interrupt: Callable[[], bool] | None = None) -> ProjectRecord: ...
    def write_project(self, slot: Slot, record: ProjectRecord, capability) -> None: ...
    def read_globals(self, interrupt: Callable[[], bool] | None = None) -> GlobalSettings: ...
    def write_globals(self, settings: GlobalSettings, capability) -> None: ...

    def abort(self) -> None:
        """Every wait in flight ends at once as Gone (a release is under way)."""
        ...

    def resume(self) -> None:
        """Waits work again (the release's own reads)."""
        ...


@runtime_checkable
class UnitControl(Protocol):
    def request_view(self, view: UnitView = UnitView.CUSTOM) -> bool:
        """Asks the unit for a pad mode (s10.c7); False when nothing is held or it was not sent. Sent through the
        host (ViewRequester), the view counts as reported at once: the unit obeys but never echoes (2026-10-27)."""
        ...


# --- backups (s13) ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Corrupt:
    """A backup or library file that is not a whole record (d77, A47)."""
    name: str
    reason: str

    def text(self, verb: str = "not restored") -> str:
        """'slot7-2026-10-24T12-00 holds 512 bytes, expected 880; not restored' (A47)."""
        return f"{self.name} {self.reason}; {verb}"


class StorageError(Exception):
    """A backup or library file could not be written (s14.c2: the OSError mapped, with the path)."""

    def __init__(self, path: str, reason: str):
        self.path, self.reason = str(path), reason
        super().__init__(f"{path}: {reason}")


@dataclass(frozen=True)
class BackupInfo:
    """One stored backup as listed (d76)."""
    id: BackupId
    target: BackupTarget
    taken_at: datetime
    size: int
    sha256: str

    def to_json(self) -> dict:
        return {"id": str(self.id), "target": target_name(self.target), "taken_at": self.taken_at.isoformat(),
                "size": self.size, "sha256": self.sha256}


SET_ALL, SET_SESSION = "all", "session"   # 'back up all' (d74) and a lab session's slots 1–24 (§2.7 a5/q9)


@dataclass(frozen=True)
class BackupSet:
    id: BackupSetId
    taken_at: datetime
    kind: str
    members: tuple[tuple[str, BackupId], ...]     # (target name, backup id), in slot order
    complete: bool = True

    @property
    def covers_stored_slots(self) -> bool:
        """A full backup in §2.7's sense: every stored slot 1–24 is in it."""
        names = {name for name, _ in self.members}
        return self.complete and all(f"slot{n}" in names for n in range(1, 25))

    def to_json(self) -> dict:
        return {"id": str(self.id), "taken_at": self.taken_at.isoformat(), "kind": self.kind,
                "complete": self.complete, "members": {name: str(i) for name, i in self.members}}


@runtime_checkable
class BackupStore(Protocol):
    def save(self, backup: Backup) -> BackupId:
        """The new id, or the existing one when the bytes equal the newest backup of that target (d78)."""
        ...

    def save_set(self, members: Iterable[BackupId], kind: str, taken_at: datetime,
                 complete: bool = True) -> BackupSetId: ...
    def get(self, backup_id: BackupId) -> Backup | Corrupt | None: ...
    def list(self, target: BackupTarget | None = None) -> list[BackupInfo]: ...
    def sets(self) -> list[BackupSet]: ...

    def last_full_backup_at(self) -> datetime | None:
        """When the newest complete backup of slots 1–24 was taken (a session reuses one < 10 min old)."""
        ...

    def open_session(self, backup_id: BackupId) -> None: ...
    def close_session(self) -> None: ...

    def open_session_left(self) -> BackupId | None:
        """The session backup of a session that never ended cleanly (a8: a crash, an unplug), or None."""
        ...


# --- the library (s15) -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Stored:
    entry: LibraryEntry


@dataclass(frozen=True)
class NameTaken:
    existing: str

    def text(self) -> str:
        return f'name "{self.existing}" is already in the library'   # A59


@runtime_checkable
class LibraryStore(Protocol):
    def entries(self) -> list[LibraryEntry | Corrupt]: ...
    def get(self, name: str) -> LibraryEntry | Corrupt | None: ...
    def put(self, entry: LibraryEntry) -> Stored | NameTaken: ...

    def replace(self, entry: LibraryEntry) -> Stored | None:
        """Rewrites the entry of that name (a bulk edit of a library entry); None when there is none."""
        ...


# --- plugins (s17) ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DiscoveryError:
    """A plugin file that could not be loaded: it raised, or exposes neither GENERATOR nor SCHEME (s17.c2)."""
    message: str


@runtime_checkable
class GeneratorSource(Protocol):
    def discover(self) -> list[tuple[str, Any]]:
        """[(file, generator | scheme | DiscoveryError)] in file order, once at start (s17.c1)."""
        ...


# --- settings the lab remembers ---------------------------------------------------------------------------
@runtime_checkable
class LabSettingsStore(Protocol):
    """Small remembered choices (the harmony inputs, §2.7 q7)."""

    def get(self, key: str, default: Any = None) -> Any: ...
    def put(self, key: str, value: Any) -> None: ...


class MemorySettings:
    """LabSettingsStore kept in memory (tests, and a composition without a settings file)."""

    def __init__(self, values: dict | None = None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def put(self, key, value):
        self.values[key] = value


# --- the page --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class LabState:
    """The lab panel's state (GET /api/lab, §3.5), published on the ws 'lab' topic as kind 'lab'."""
    generators: tuple[dict, ...] = ()
    schemes: tuple[dict, ...] = ()
    active: dict | None = None
    message: str | None = None
    recovery: dict | None = None
    target: dict | None = None
    warnings: tuple[str, ...] = ()
    layouts: tuple[dict, ...] = ()     # the generated layouts: {layout, name, generator, valid} or {…, valid: false, error}
    kind: str = field(default="lab", init=False)

    def to_json(self) -> dict:
        return {"kind": self.kind, "generators": list(self.generators), "schemes": list(self.schemes),
                "active": self.active, "message": self.message, "recovery": self.recovery,
                "target": self.target, "warnings": list(self.warnings), "layouts": list(self.layouts)}


@runtime_checkable
class LabStatePublisher(Protocol):
    def publish(self, snapshot) -> None:
        """A LabState or HarmonyState snapshot (s23.c1), after each change."""
        ...

    def current(self) -> dict:
        """The latest snapshot of each kind (s23.c2)."""
        ...


class NullPublisher:
    def publish(self, snapshot) -> None:
        pass

    def current(self) -> dict:
        return {}


# --- the host, bound late ---------------------------------------------------------------------------------
class HostLink:
    """The host ports a lab service may call (HostPorts from HostModule.bind), and no-ops before bind.

    The engine and session are built after the gate, so their ports reach the lab late (through
    HostModule.bind). Every service shares one link; LabModule.bind fills it."""

    def __init__(self, ports: HostPorts | None = None):
        self.ports = ports or HostPorts()

    def bind(self, ports: HostPorts) -> None:
        self.ports = ports

    # the engine (ModuleDisplay, NoteEnder, LayoutLoader) and tweaks
    def resting(self, text: OledText | None) -> None:
        if self.ports.display is not None:
            self.ports.display.set_resting_oled(text)

    def warn(self, text: str | None) -> None:
        if self.ports.display is not None:
            self.ports.display.warn(text)

    def end_notes(self, notes) -> None:
        notes = tuple(notes)
        if notes and self.ports.notes is not None:
            self.ports.notes.end_notes(notes)

    def load(self, layout_id):
        return self.ports.loader.load(layout_id) if self.ports.loader is not None else None

    def tweak(self, layout_id, path: str, value, comment: str | None = None):
        if not self.ports.tweaks:
            return None
        if comment is None:
            return self.ports.tweaks.save_section_field(layout_id, path, value)
        return self.ports.tweaks.save_section_field(layout_id, path, value, comment=comment)

    # the session's SysEx tap and the gate (for the unit-memory adapter)
    @property
    def sysex(self):
        return self.ports.sysex

    @property
    def gate(self):
        return self.ports.gate

    @property
    def stream(self):
        return self.ports.stream

    @property
    def inputs(self):
        return self.ports.inputs

    @property
    def views(self):
        """The host's ViewRequester (the engine), or None before bind."""
        return getattr(self.ports, "views", None)

    # time and the loop
    def call_later(self, seconds: float, callback: Callable[[], None]):
        """A timer on the host clock, set from the loop (dispatch hops there from a worker thread)."""
        clock, dispatch = self.ports.clock, self.ports.dispatch
        if clock is None:
            return None
        if dispatch is None:
            return clock.call_later(seconds, callback)
        dispatch(lambda: clock.call_later(seconds, callback))
        return None

    def dispatch(self, fn: Callable[[], None]) -> None:
        if self.ports.dispatch is not None:
            self.ports.dispatch(fn)
        else:
            fn()
