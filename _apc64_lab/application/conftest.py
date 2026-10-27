"""Doubles for the lab application tests: in-memory fakes of every lab port and of the host ports a lab service
calls (all hermetic: no ALSA, no files outside tmp_path, nothing sent to a unit)."""
from collections import Counter
from datetime import datetime, timedelta

import pytest

from _apc64_host.application.conftest import ManualClock
from _apc64_host.application.ports import HostPorts
from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.outbound import WriteCapability
from _apc64_lab.application.ports import (
    BackupInfo, BackupSet, Corrupt, Gone, Interrupted, MalformedReply, NameTaken, NoReply, NotHeld, StorageError,
    Stored, WrongFirmware,
)
from _apc64_lab.domain.conftest import snapshot_frames
from _apc64_lab.domain.memory import Backup, BackupId, BackupSetId, target_name
from _apc64_lab.domain.memory_sysex import Malformed, parse_project_dump
from _apc64_lab.domain.pads import Rgb
from _apc64_lab.domain.records import GLOBAL_SIZE, PROJECT_SIZE, GlobalSettings, ProjectRecord

T0 = datetime(2026, 10, 24, 20, 15)


def snapshot_records() -> list[ProjectRecord]:
    return [parse_project_dump(frame)[1] for frame in snapshot_frames()]


def named(record: ProjectRecord, tag: int) -> ProjectRecord:
    """A recognisable project: the record with pad r1c6's rest colour set to (tag, tag, tag)."""
    return record.with_pad_records({5: record.pads[5].with_fields(rest=Rgb(tag, tag, tag))})


LOOPS_TAG, DRUMS_TAG = 7, 3


def globals_block(led_index: int = 2) -> GlobalSettings:
    """A63's block: bytes 0–19 = 01 00 … 0A, Ableton Live mode, CV channels 1, drums 36–51, LED 75 %."""
    raw = bytearray(GLOBAL_SIZE)
    raw[0], raw[19] = 0x01, 0x0A
    raw[31:39] = bytes([1] * 8)
    raw[39:55] = bytes(range(36, 52))
    raw[55] = led_index
    return GlobalSettings(bytes(raw))


class Events(list):
    """One ordered log shared by the doubles: ('read', 7), ('backup', 'slot7-…'), ('write', 7), …"""


class FakeMemory:
    """UnitMemory + UnitControl double. Faults per call kind; every call is logged in order."""

    def __init__(self, events: Events | None = None, held: bool = True, firmware: str = "1.2.1.6"):
        records = snapshot_records()
        self.slots: dict[int, ProjectRecord] = {n: records[n] for n in range(25)}
        self.slots[0] = named(self.slots[0], LOOPS_TAG)         # 'Loops' in the edit buffer
        self.slots[7] = named(self.slots[7], LOOPS_TAG)         # 'Loops' saved as project 7
        self.globals = globals_block()
        self.events = events if events is not None else Events()
        self.held, self.firmware = held, firmware
        self.no_reply: set = set()          # slots (or 'globals') whose reads are not answered
        self.short: dict = {}               # slot → raw length answered
        self.gone_on_write: set = set()     # slots whose write is cut off by an unplug
        self.mismatch: dict = {}            # slot → raw offset the next write of it stores flipped (one shot)
        self.views: list = []
        self.aborted = False
        self.on_write = None                # callback(slot, record) after a write (tests hook timing here)

    # UnitMemory -------------------------------------------------------------------------------------------
    def check_writable(self):
        if not self.held:
            raise NotHeld()
        if self.firmware != "1.2.1.6":
            raise WrongFirmware(self.firmware, "1.2.1.6")

    def _check_read(self, key):
        if self.aborted:
            raise Gone("released")
        if not self.held:
            raise NotHeld()
        if key in self.no_reply:
            raise NoReply("no answer within 2 s")

    def read_project(self, slot, interrupt=None):
        self.events.append(("read", int(slot)))
        self._check_read(int(slot))
        if interrupt is not None and interrupt():
            raise Interrupted("a newer write is due")
        if int(slot) in self.short:
            raise MalformedReply(Malformed(self.short[int(slot)], PROJECT_SIZE))
        return self.slots[int(slot)]

    def write_project(self, slot, record, capability):
        assert isinstance(capability, WriteCapability), "writes carry the capability"
        self.check_writable()
        self.events.append(("write", int(slot)))
        if int(slot) in self.gone_on_write:
            self.held = False
            raise Gone(f"unplugged while slot {int(slot)} was written")
        if int(slot) in self.mismatch:
            raw = bytearray(record.raw)
            raw[self.mismatch.pop(int(slot))] ^= 0x01
            record = ProjectRecord(bytes(raw))
        self.slots[int(slot)] = record
        if self.on_write is not None:
            self.on_write(int(slot), record)

    def read_globals(self, interrupt=None):
        self.events.append(("read", "globals"))
        self._check_read("globals")
        if "globals" in self.short:
            raise MalformedReply(Malformed(self.short["globals"], GLOBAL_SIZE))
        return self.globals

    def write_globals(self, settings, capability):
        assert isinstance(capability, WriteCapability)
        self.check_writable()
        self.events.append(("write", "globals"))
        if "globals" in self.gone_on_write:
            self.held = False
            raise Gone("unplugged while the global settings were written")
        if "globals" in self.mismatch:
            raw = bytearray(settings.raw)
            raw[self.mismatch.pop("globals")] ^= 0x01
            settings = GlobalSettings(bytes(raw))
        self.globals = settings

    def abort(self):
        self.aborted = True

    def resume(self):
        self.aborted = False

    # UnitControl ------------------------------------------------------------------------------------------
    def request_view(self, view=UnitView.CUSTOM):
        self.views.append(view)
        return self.held

    def writes(self, slot=None):
        return [e for e in self.events if e[0] == "write" and (slot is None or e[1] == slot)]


class FakeBackups:
    """BackupStore double: dated ids from a test clock, dedup against the newest of a target, sets, marker."""

    def __init__(self, events: Events | None = None):
        self.events = events if events is not None else Events()
        self.backups: dict[str, Backup] = {}
        self.order: list[str] = []
        self.set_list: list[BackupSet] = []
        self.marker: str | None = None
        self.corrupt: dict[str, Corrupt] = {}
        self.fail: str | None = None        # a StorageError reason for every save

    def save(self, backup):
        if self.fail:
            raise StorageError(f"backups/{target_name(backup.target)}.bin", self.fail)
        newest = next((self.backups[i] for i in reversed(self.order)
                       if self.backups[i].target == backup.target), None)
        if newest is not None and newest.data == backup.data:
            found = next(i for i in reversed(self.order) if self.backups[i] is newest)
            self.events.append(("backup", found))
            return BackupId(found)
        serial = 1
        while (bid := BackupId.of(backup.target, backup.taken_at, serial)) in self.backups:
            serial += 1
        self.backups[bid] = backup
        self.order.append(bid)
        self.events.append(("backup", bid))
        return bid

    def save_set(self, members, kind, taken_at, complete=True):
        members = tuple(members)
        serial = 1
        while (sid := BackupSetId.of(taken_at, serial)) in {s.id for s in self.set_list}:
            serial += 1
        self.set_list.append(BackupSet(sid, taken_at, kind,
                                       tuple((target_name(self.backups[m].target), m) for m in members), complete))
        self.events.append(("set", sid, kind))
        return sid

    def get(self, backup_id):
        if backup_id in self.corrupt:
            return self.corrupt[backup_id]
        return self.backups.get(backup_id)

    def list(self, target=None):
        found = []
        for i in self.order:
            b = self.backups[i]
            if target is None or b.target == target:
                found.append(BackupInfo(BackupId(i), b.target, b.taken_at, len(b.data), b.sha256))
        return found

    def sets(self):
        return list(self.set_list)

    def last_full_backup_at(self):
        full = [s.taken_at for s in self.set_list if s.covers_stored_slots]
        return max(full) if full else None

    def open_session(self, backup_id):
        self.marker = backup_id
        self.events.append(("open_session", backup_id))

    def close_session(self):
        self.marker = None
        self.events.append(("close_session",))

    def open_session_left(self):
        return self.marker


class FakeLibrary:
    def __init__(self):
        self.items: dict[str, object] = {}

    def entries(self):
        return list(self.items.values())

    def get(self, name):
        return next((e for k, e in self.items.items() if k.casefold() == str(name).casefold()), None)

    def put(self, entry):
        existing = self.get(entry.name)
        if existing is not None:
            return NameTaken(existing.name)
        self.items[entry.name] = entry
        return Stored(entry)

    def replace(self, entry):
        existing = self.get(entry.name)
        if existing is None:
            return None
        self.items[existing.name] = entry
        return Stored(entry)


class RecordingPublisher:
    def __init__(self):
        self.published = []

    def publish(self, snapshot):
        self.published.append(snapshot)

    def current(self):
        latest = {}
        for snapshot in self.published:
            latest[getattr(snapshot, "kind", "harmony")] = snapshot
        return latest

    def of_kind(self, kind):
        return [s for s in self.published if getattr(s, "kind", "harmony") == kind]


class EngineDouble:
    """ModuleDisplay + NoteEnder + LayoutLoader double: records every call."""

    def __init__(self):
        self.resting, self.warnings, self.ended, self.loads = [], [], [], []

    def set_resting_oled(self, text):
        self.resting.append(text)

    def warn(self, text):
        self.warnings.append(text)

    def end_notes(self, notes, role=None):
        self.ended.append(tuple(notes))

    def load(self, layout_id):
        self.loads.append(layout_id)
        return "ok"

    @property
    def oled(self):
        return self.resting[-1] if self.resting else None


class TweaksDouble:
    def __init__(self, answer="saved"):
        self.calls, self.answer = [], answer

    def save_section_field(self, layout_id, path, value, base_hash=None):
        self.calls.append((str(layout_id), path, value))
        return self.answer


def host_ports(engine=None, tweaks=None, clock=None, **more) -> HostPorts:
    engine = engine or EngineDouble()
    return HostPorts(display=engine, notes=engine, loader=engine, tweaks=tweaks, clock=clock or ManualClock(),
                     **more)


class Wall:
    """A wall clock for backup names: starts at T0 and moves only when the test says so."""

    def __init__(self, start: datetime = T0):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


@pytest.fixture
def events():
    return Events()


def counts(items) -> Counter:
    return Counter(items)
