"""LibraryStore over files in library/ (contract s15 supplier, s16; d81–d87; A58, A59).

One JSON file per captured or imported entry, named after the entry ('live-set-b.json'), holding the name, the
kind, where it came from and the 880-byte record as hex. Generated-layout definitions are not stored here: they
are the layout files in layouts/ (the lab lists them beside these entries). Names are unique without regard to
case (d82). Files are written atomically (s16.c1); an OSError becomes a StorageError naming the path (s16.c2). A
file that does not hold a whole entry is listed as Corrupt and never used.
"""
import json
import re
from datetime import datetime
from pathlib import Path

from _apc64_host.domain.issues import DomainInvariantError

from ..application.ports import Corrupt, NameTaken, Stored
from ..domain.memory import EntryKind, LibraryEntry
from ..domain.records import PROJECT_SIZE, ProjectRecord
from .backup_files import write_atomically

_SLUG = re.compile(r"[^a-z0-9]+")


def slug_of(name: str) -> str:
    return _SLUG.sub("-", str(name).casefold()).strip("-") or "entry"


class LibraryFiles:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _files(self) -> list[Path]:
        return sorted(self.root.glob("*.json")) if self.root.is_dir() else []

    def _load(self, path: Path) -> LibraryEntry | Corrupt:
        try:
            body = json.loads(path.read_text())
            name, kind = str(body["name"]), EntryKind(body["kind"])
            record = None
            if kind is not EntryKind.DEFINITION:
                data = bytes.fromhex(str(body["record"]))
                if len(data) != PROJECT_SIZE:
                    return Corrupt(name, f"holds {len(data)} bytes, expected {PROJECT_SIZE}")
                record = ProjectRecord(data)
            return LibraryEntry(name, kind, record, body.get("layout"), body.get("source"))
        except (OSError, ValueError, KeyError, TypeError, DomainInvariantError) as error:
            return Corrupt(path.name, f"is not a library entry ({error})")

    def _find(self, name: str) -> tuple[Path, LibraryEntry | Corrupt] | None:
        wanted = str(name).strip().casefold()
        for path in self._files():
            entry = self._load(path)
            if entry.name.casefold() == wanted:
                return path, entry
        return None

    # --- LibraryStore -----------------------------------------------------------------------------------
    def entries(self) -> list[LibraryEntry | Corrupt]:
        return sorted((self._load(p) for p in self._files()), key=lambda e: e.name.casefold())

    def get(self, name: str) -> LibraryEntry | Corrupt | None:
        found = self._find(name)
        return found[1] if found else None

    def put(self, entry: LibraryEntry) -> Stored | NameTaken:
        found = self._find(entry.name)
        if found is not None:
            return NameTaken(found[1].name)                                                  # A59
        stem, serial = slug_of(entry.name), 1
        while (self.root / f"{stem}{'' if serial == 1 else f'-{serial}'}.json").exists():
            serial += 1
        self._write(self.root / f"{stem}{'' if serial == 1 else f'-{serial}'}.json", entry)
        return Stored(entry)

    def replace(self, entry: LibraryEntry) -> Stored | None:
        found = self._find(entry.name)
        if found is None:
            return None
        self._write(found[0], entry)
        return Stored(entry)

    def _write(self, path: Path, entry: LibraryEntry) -> None:
        body = {"name": entry.name, "kind": str(entry.kind), "source": entry.source, "layout": entry.layout,
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "record": entry.record.raw.hex() if entry.record is not None else None}
        write_atomically(path, (json.dumps(body, indent=1) + "\n").encode())
