"""ProjectMemory: backups, restore, push, the library, import and bulk edits of the unit's projects (contract
pi5; inv1, inv8, inv9, inv10; §2.7 q1, q3, q4, q5; d62–d87).

Every write goes through GuardedWriter's command path, so each backs up what it overwrites first and verifies by
read-back. Slots 1–24 change only through these commands (inv8). Slot 0 belongs to lab sessions: push refuses
it (A50), and restore takes slot 0 only from a slot-0 backup while no session runs (d63) — the way a pending
recovery (a8) is done. Restore is one slot at a time (§2.7 q5); 'back up all' is one command (d74).
Push stores a generated layout where it currently sits (§2.7 q3) unless an offset is given.
"""
from datetime import datetime
from typing import Callable, Iterable

from _apc64_host.domain.issues import DomainInvariantError

from ..domain.apc64_preset import PresetError, parse_preset, preset_name, summary
from ..domain.bulk_edit import BulkEdit, apply_all
from ..domain.memory import (
    EDIT_BUFFER, GLOBALS, BackupId, EntryKind, LibraryEntry, OutcomeCode, OutcomeKind, Slot, StoredSlot,
    WriteOutcome, pushed_message, target_name,
)
from ..domain.records import GLOBAL_SIZE, PROJECT_SIZE, GlobalSettings, ProjectRecord
from .guarded_writer import NOT_HELD_NOTHING, Busy, GuardedWriter, busy, failed, invalid, refused
from .ports import (
    SET_ALL, BackupStore, Corrupt, Gone, Interrupted, LibraryStore, MalformedReply, MemoryFault, NameTaken,
    NoReply, NotHeld, StorageError,
)
from .registry import DefinitionIndex, GeneratorRegistry

MAX_PRESET_BYTES = 1 << 20


def _taken(name: str) -> WriteOutcome:
    return refused(NameTaken(name).text(), OutcomeCode.TAKEN, "name", "choose another name")   # A59, d82


def _read_fault(fault: MemoryFault, what: str, verb: str = "nothing stored") -> WriteOutcome:
    if isinstance(fault, NotHeld):
        return refused(NOT_HELD_NOTHING, OutcomeCode.NOT_HELD)
    if isinstance(fault, MalformedReply):
        return failed(f"{fault.text(what)}; {verb}")
    return failed(f"{what} did not answer; {verb}")


class ProjectMemory:
    def __init__(self, writer: GuardedWriter, backups: BackupStore, library: LibraryStore,
                 registry: GeneratorRegistry, index: DefinitionIndex, session=None,
                 wall: Callable[[], datetime] = datetime.now):
        self._writer, self._backups, self._library = writer, backups, library
        self._registry, self._index, self._session = registry, index, session
        self._wall = wall

    # === backups (d74–d78) =================================================================================
    def backup_all(self) -> WriteOutcome:
        """Slots 0–24 and the global block as one dated set (d74, A45)."""
        try:
            with self._writer.command("backup all"):
                taken, members, missing = self._wall(), [], []
                for n in range(25):
                    try:
                        record = self._writer.read_project(Slot(n))
                    except NotHeld:
                        return refused(NOT_HELD_NOTHING, OutcomeCode.NOT_HELD)
                    except MemoryFault:
                        missing.append(f"slot {n}")
                        continue
                    members.append(self._writer.save_backup(Slot(n), record.raw))
                try:
                    members.append(self._writer.save_backup(GLOBALS, self._writer.read_globals().raw))
                except NotHeld:
                    return refused(NOT_HELD_NOTHING, OutcomeCode.NOT_HELD)
                except MemoryFault:
                    missing.append("the global settings")
                set_id = self._backups.save_set(members, SET_ALL, taken, complete=not missing)
        except Busy as error:
            return busy(error)
        except StorageError as error:
            return refused(f"could not save a backup ({error.path}: {error.reason})", OutcomeCode.STORAGE)
        if missing:
            return failed(f"backup set {set_id} is incomplete: {', '.join(missing)} did not answer")
        return WriteOutcome(OutcomeKind.BACKED_UP, f"backed up slots 0–24 and the global settings as {set_id}",
                            extra={"set": str(set_id)})

    def backup(self, target) -> WriteOutcome:
        """One slot (0–24) or 'globals'; a backup equal to the newest of that target is recorded once (A46)."""
        try:
            is_globals = str(target).strip().lower() == "globals"
            slot = None if is_globals else Slot(int(str(target).strip()) if str(target).strip().isdigit() else target)
        except DomainInvariantError as error:
            return invalid(error)
        what = "the global settings" if is_globals else f"slot {int(slot)}"
        before = {info.id for info in self._backups.list(GLOBALS if is_globals else slot)}
        try:
            with self._writer.command(f"backup of {what}"):
                data = (self._writer.read_globals() if is_globals else self._writer.read_project(slot)).raw
                backup_id = self._writer.save_backup(GLOBALS if is_globals else slot, data)
        except Busy as error:
            return busy(error)
        except MemoryFault as fault:
            return _read_fault(fault, what, "nothing backed up")
        except StorageError as error:
            return refused(f"could not save the backup of {what} ({error.path}: {error.reason})", OutcomeCode.STORAGE)
        if backup_id in before:
            return WriteOutcome(OutcomeKind.UNCHANGED, f"{what} unchanged since {backup_id}; no new backup",
                                backup_id)
        return WriteOutcome(OutcomeKind.BACKED_UP, f"backed up {what} as {backup_id}", backup_id)

    def backups(self, target=None) -> dict:
        """GET /api/lab/backups: every backup by date and slot (d76), and the sets."""
        return {"backups": [info.to_json() for info in self._backups.list(target)],
                "sets": [s.to_json() for s in self._backups.sets()]}

    # === restore (one slot at a time, §2.7 q5) =============================================================
    def restore(self, backup, slot) -> WriteOutcome:
        try:
            backup_id = BackupId(str(backup).strip())
        except DomainInvariantError as error:
            return invalid(error)
        found = self._backups.get(backup_id)
        if found is None:
            return refused(f"no backup {backup_id}", OutcomeCode.NOT_FOUND, "backup",
                           "list the backups with 'apc64 lab backups'")
        if isinstance(found, Corrupt):
            return refused(found.text(), OutcomeCode.CORRUPT, "backup")                       # A47, d77
        to_globals = str(slot).strip().lower() == "globals"
        if to_globals or found.target is GLOBALS:
            if not (to_globals and found.target is GLOBALS):
                return refused(f"{backup_id} holds {target_name(found.target)}; it restores only to "
                               f"{target_name(found.target)}", OutcomeCode.INVALID, "slot")
            return self._restore_globals(backup_id, found.data)
        text = str(slot).strip()
        if text == "0":
            return self._restore_slot0(backup_id, found)
        try:
            stored = StoredSlot.parse(slot)
        except DomainInvariantError as error:
            return invalid(error)
        data = found.data
        if len(data) != PROJECT_SIZE:
            return refused(Corrupt(backup_id, f"holds {len(data)} bytes, expected {PROJECT_SIZE}").text(),
                           OutcomeCode.CORRUPT, "backup")
        n = int(stored)
        return self._writer.write_project(
            stored, lambda current: ProjectRecord(data), what=f"restore of slot {n}", kind=OutcomeKind.RESTORED,
            success=lambda b: f"restored slot {n} from {backup_id}; takes effect when project {n} is next loaded")

    def _restore_slot0(self, backup_id: BackupId, found) -> WriteOutcome:
        if found.target != EDIT_BUFFER:
            return refused(f"slot 0 is restored only from a slot-0 backup, not {backup_id}", OutcomeCode.INVALID,
                           "slot", "pick a backup named slot0-…, or restore this one to a slot 1–24")   # d63
        if self._session is not None and self._session.running:
            return refused("slot 0 belongs to the running lab session; leave it first, it restores slot 0 itself",
                           OutcomeCode.SESSION)
        data = found.data
        outcome = self._writer.write_project(
            EDIT_BUFFER, lambda current: ProjectRecord(data), what="restore of slot 0", kind=OutcomeKind.RESTORED,
            success=lambda b: f"restored slot 0 from {backup_id}; the unit shows the project as unsaved, "
                              "nothing was saved")
        if outcome.ok and self._session is not None:
            self._session.recovered(backup_id)
        return outcome

    def _restore_globals(self, backup_id: BackupId, data: bytes) -> WriteOutcome:
        if len(data) != GLOBAL_SIZE:
            return refused(Corrupt(backup_id, f"holds {len(data)} bytes, expected {GLOBAL_SIZE}").text(),
                           OutcomeCode.CORRUPT, "backup")
        return self._writer.write_globals(lambda current: GlobalSettings(data), what="restore of the global settings",
                                          success=lambda b: f"restored the global settings from {backup_id}",
                                          unchanged="the global settings unchanged; nothing written")

    # === push (d62, d68, d69; §2.7 q3) =====================================================================
    def push(self, entry: str, slot, offset: int | None = None) -> WriteOutcome:
        try:
            stored = StoredSlot.parse(slot)                                                   # A49, A50
        except DomainInvariantError as error:
            return invalid(error)
        change = self._push_change(entry, offset)
        if isinstance(change, WriteOutcome):
            return change
        return self._writer.write_project(stored, change, what=f"push to slot {int(stored)}",
                                          success=lambda b: pushed_message(stored))           # A1, A60

    def _push_change(self, entry: str, offset: int | None):
        definition = self._index.resolve(entry)
        if definition is not None:
            transposition = offset if offset is not None else (
                self._session.transposition_of(definition.layout_id) if self._session is not None else None) or 0
            try:
                generators, schemes = self._registry.generators(), self._registry.schemes()
                span = definition.definition.grid(generators, schemes, 0).span()
                if span is not None and not span.fits(transposition):
                    raise DomainInvariantError(
                        "offset", f"offset {transposition:+d} puts the pads outside 0–127",
                        f"offsets from {-span.lowest:+d} to {127 - span.highest:+d} fit")
                grid = definition.definition.grid(generators, schemes, transposition)
            except DomainInvariantError as error:
                return invalid(error)
            except Exception as error:   # a generator broken since compile: never written (d13)
                return refused(f"{definition.name}: the generator failed ({error}); nothing written",
                               OutcomeCode.INVALID, "generator")
            strips = dict(definition.definition.strips)

            def generated(current: ProjectRecord) -> ProjectRecord:
                record = current.with_pads(grid)
                return record.with_strips(strips) if strips else record
            return generated
        found = self._library.get(entry)
        if isinstance(found, Corrupt):
            return refused(found.text("not pushed"), OutcomeCode.CORRUPT, "entry")
        if found is None:
            names = sorted({i.name for i in self._index.all()} | {e.name for e in self._entries()})
            return refused(f'no layout or library entry "{entry}"', OutcomeCode.NOT_FOUND, "entry",
                           "available: " + (", ".join(names) or "none"))
        record = found.record
        return lambda current: current.with_known_from(record)

    # === the library (d81–d87) =============================================================================
    def _entries(self) -> list[LibraryEntry]:
        return [e for e in self._library.entries() if isinstance(e, LibraryEntry)]

    def _name_taken(self, name: str) -> str | None:
        found = self._library.get(name)
        if found is not None:
            return found.name if isinstance(found, LibraryEntry) else name
        indexed = self._index.resolve(name)
        return indexed.name if indexed is not None and indexed.name.casefold() == name.casefold() else None

    def library(self) -> list[dict]:
        listed = [{"name": i.name, "kind": str(EntryKind.DEFINITION), "layout": i.layout_id,
                   "generator": i.definition.generator} for i in self._index.all()]
        for entry in self._library.entries():
            if isinstance(entry, Corrupt):
                listed.append({"name": entry.name, "kind": "corrupt", "error": entry.reason})
            else:
                listed.append({"name": entry.name, "kind": str(entry.kind), "source": entry.source,
                               **summary(entry.record)})
        return listed

    def capture(self, slot, name: str) -> WriteOutcome:
        """Any slot 0–24 saved to the library under a new name (d83, A58)."""
        name = str(name or "").strip()
        try:
            slot = Slot(int(str(slot).strip()) if str(slot).strip().isdigit() else slot)
            LibraryEntry(name, EntryKind.CAPTURED, record=b"")   # validates the name
        except DomainInvariantError as error:
            return invalid(error)
        taken = self._name_taken(name)
        if taken is not None:
            return _taken(taken)
        try:
            with self._writer.command(f"capture of slot {int(slot)}"):
                record = self._writer.read_project(slot)
        except Busy as error:
            return busy(error)
        except MemoryFault as fault:
            return _read_fault(fault, f"slot {int(slot)}")
        return self._store(LibraryEntry(name, EntryKind.CAPTURED, record, source=f"slot {int(slot)}"),
                           f'saved slot {int(slot)} to the library as "{name}"')

    def import_preset(self, name: str | None, data: bytes, filename: str | None = None) -> WriteOutcome:
        """An Akai .APC64 preset into the library; nothing is written to the unit (A55–A57, d84–d87)."""
        data = bytes(data or b"")
        if len(data) > MAX_PRESET_BYTES:
            return refused(f"the file holds {len(data)} bytes; a preset is a few kilobytes", OutcomeCode.INVALID,
                           "data")
        name = str(name or (preset_name(filename) if filename else "")).strip()
        if not name:
            return refused("the import has no name", OutcomeCode.INVALID, "name",
                           "give a name, or the file name it came from")
        try:
            record = parse_preset(data)
        except PresetError as error:
            return refused(error.message, OutcomeCode.INVALID, "data")
        taken = self._name_taken(name)
        if taken is not None:
            return _taken(taken)
        parts = summary(record)
        return self._store(LibraryEntry(name, EntryKind.IMPORTED, record, source=filename or "import"),
                           f'imported "{name}" ({parts["pads"]} pads, {parts["strips"]} strips); '
                           "nothing written to the unit", parts)

    def _store(self, entry: LibraryEntry, message: str, extra: dict | None = None) -> WriteOutcome:
        try:
            answer = self._library.put(entry)
        except StorageError as error:
            return refused(f"could not save the library entry ({error.path}: {error.reason})", OutcomeCode.STORAGE)
        if isinstance(answer, NameTaken):
            return _taken(answer.existing)
        return WriteOutcome(OutcomeKind.STORED, message, extra=extra)

    # === bulk edits (§2.7 q1) ==============================================================================
    def bulk_edit(self, target, edits: Iterable[str] | str) -> WriteOutcome:
        """A validated edit of a stored project (through the guarded write path) or of a captured or imported
        library entry (stored back; nothing written to the unit)."""
        texts = [edits] if isinstance(edits, str) else list(edits)
        try:
            parsed = [BulkEdit.parse(text) for text in texts]
        except DomainInvariantError as error:
            return invalid(error)
        if not parsed:
            return refused("no edit given", OutcomeCode.INVALID, "edits", "write e.g. 'all pads channel 3'")
        described = "; ".join(" ".join(t.split()) for t in texts)
        text = str(target).strip()
        if text.isdigit():
            try:
                stored = StoredSlot.parse(text)
            except DomainInvariantError as error:
                return invalid(error)
            n = int(stored)
            return self._writer.write_project(
                stored, lambda current: apply_all(current, parsed), what=f"bulk edit of slot {n}",
                success=lambda b: f"edited slot {n} ({described}); takes effect when project {n} is next loaded")
        found = self._library.get(text)
        if isinstance(found, Corrupt):
            return refused(found.text("not edited"), OutcomeCode.CORRUPT, "entry")
        if found is None:
            if self._index.resolve(text) is not None:
                return refused(f'"{text}" is a generated layout', OutcomeCode.INVALID, "target",
                               "edit its lab section, or push it to a slot and edit the slot")
            return refused(f'no slot or library entry "{text}"', OutcomeCode.NOT_FOUND, "target",
                           "give a slot 1–24 or a captured or imported entry")
        try:
            record = apply_all(found.record, parsed)
        except DomainInvariantError as error:
            return invalid(error)
        if record == found.record:
            return WriteOutcome(OutcomeKind.UNCHANGED, f'library entry "{found.name}" unchanged; nothing stored')
        try:
            self._library.replace(LibraryEntry(found.name, found.kind, record, source=found.source))
        except StorageError as error:
            return refused(f"could not save the library entry ({error.path}: {error.reason})", OutcomeCode.STORAGE)
        return WriteOutcome(OutcomeKind.STORED,
                            f'edited library entry "{found.name}" ({described}); nothing written to the unit')

    # === reading a slot (GET /api/lab/slots/{n}) and previews (§2.7 q4) ====================================
    def slot(self, n) -> dict | WriteOutcome:
        try:
            slot = Slot(int(str(n).strip()) if str(n).strip().isdigit() else n)
        except DomainInvariantError as error:
            return invalid(error)
        try:
            record = self._writer.read_project(slot)
        except MemoryFault as fault:
            return _read_fault(fault, f"slot {int(slot)}", "nothing read")
        return {"slot": int(slot), "pads": [p.describe() for p in record.pads],
                "strips": [s.describe() for s in record.strips], "raw": record.raw.hex(" ")}

    def preview(self, entry: str) -> WriteOutcome:
        """A captured or imported entry live in slot 0 through a lab session; a generated layout is activated."""
        if self._session is None:
            return refused("no lab session service", OutcomeCode.SESSION)
        indexed = self._index.resolve(entry)
        if indexed is not None:
            return self._session.activate(indexed.layout_id)
        found = self._library.get(entry)
        if isinstance(found, Corrupt):
            return refused(found.text("not previewed"), OutcomeCode.CORRUPT, "entry")
        if found is None:
            return refused(f'no layout or library entry "{entry}"', OutcomeCode.NOT_FOUND, "entry")
        return self._session.preview(found.name, found.record)
