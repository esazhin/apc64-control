"""T32: LibraryStore files on tmp_path (s15 supplier, s16; A58, A59; d81–d83)."""
from _apc64_lab.application.conftest import snapshot_records
from _apc64_lab.application.ports import Corrupt, LibraryStore, NameTaken, Stored
from _apc64_lab.domain.memory import EntryKind, LibraryEntry
from _apc64_lab.infrastructure.library_files import LibraryFiles, slug_of

RECORDS = snapshot_records()


def test_captured_and_imported_entries_round_trip(tmp_path):   # A58, s15.c2
    store = LibraryFiles(tmp_path / "library")
    assert isinstance(store, LibraryStore)
    live = LibraryEntry("Live set B", EntryKind.CAPTURED, RECORDS[12], source="slot 12")
    boss = LibraryEntry("Boss RC-600", EntryKind.IMPORTED, RECORDS[3], source="Boss RC-600.APC64")
    assert isinstance(store.put(live), Stored) and isinstance(store.put(boss), Stored)
    again = LibraryFiles(tmp_path / "library")
    assert again.get("live set b") == live and [e.name for e in again.entries()] == ["Boss RC-600", "Live set B"]
    assert (tmp_path / "library" / "live-set-b.json").exists()


def test_a_taken_name_is_refused_and_the_file_unchanged(tmp_path):   # A59, d82
    store = LibraryFiles(tmp_path)
    store.put(LibraryEntry("Live set B", EntryKind.CAPTURED, RECORDS[12], source="slot 12"))
    before = (tmp_path / "live-set-b.json").read_text()
    answer = store.put(LibraryEntry("LIVE SET B", EntryKind.CAPTURED, RECORDS[13], source="slot 13"))
    assert answer == NameTaken("Live set B") and answer.text() == 'name "Live set B" is already in the library'
    assert (tmp_path / "live-set-b.json").read_text() == before


def test_names_with_the_same_slug_get_their_own_files(tmp_path):
    store = LibraryFiles(tmp_path)
    store.put(LibraryEntry("Live set B", EntryKind.CAPTURED, RECORDS[1]))
    store.put(LibraryEntry("Live-set B!", EntryKind.CAPTURED, RECORDS[2]))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["live-set-b-2.json", "live-set-b.json"]
    assert slug_of("Boss RC-600") == "boss-rc-600"


def test_replace_rewrites_an_entry(tmp_path):
    store = LibraryFiles(tmp_path)
    store.put(LibraryEntry("Live set B", EntryKind.CAPTURED, RECORDS[1]))
    assert isinstance(store.replace(LibraryEntry("Live set B", EntryKind.CAPTURED, RECORDS[2])), Stored)
    assert store.get("Live set B").record == RECORDS[2]
    assert store.replace(LibraryEntry("Nope", EntryKind.CAPTURED, RECORDS[2])) is None


def test_a_damaged_file_is_listed_corrupt(tmp_path):   # s16
    (tmp_path / "broken.json").write_text("{not json")
    (tmp_path / "short.json").write_text('{"name": "Short", "kind": "captured", "record": "00ff"}')
    found = {e.name: e for e in LibraryFiles(tmp_path).entries()}
    assert isinstance(found["broken.json"], Corrupt) and found["Short"].reason == "holds 2 bytes, expected 880"
