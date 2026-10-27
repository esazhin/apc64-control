import os

import pytest

from _apc64_host.application.ports import MISSING, ChangeKind, LayoutSource
from _apc64_host.domain.layout import ContentHash, LayoutId
from _apc64_host.infrastructure import layout_files
from _apc64_host.infrastructure.conftest import wait_for
from _apc64_host.infrastructure.inotify import IN_CLOSE_WRITE, IN_DELETE, IN_MOVED_FROM, IN_MOVED_TO, InotifyEvent
from _apc64_host.infrastructure.layout_files import LayoutFiles

JAM = "name: Jam\npages:\n  1:\n    pad r1c1: note 36   # kick\n"


def watching(directory, **kwargs):
    files = LayoutFiles(directory, **kwargs)
    events = []
    files.changes(lambda layout, kind: events.append((layout, kind)))
    files.start()
    return files, events


def test_writes_renames_deletes_become_one_event_per_layout_and_other_names_none(tmp_path):
    # T15, s6.c1–c3, s83: real inotify in a temp dir
    files, events = watching(tmp_path, poll_interval=60)
    try:
        assert isinstance(files, LayoutSource)
        (tmp_path / "jam.yaml").write_text(JAM)                                   # CLOSE_WRITE
        assert wait_for(lambda: len(events) == 1)
        (tmp_path / "jam.yaml.tmp").write_text(JAM + "    pad r1c2: note 38\n")   # a temp name: nothing
        os.rename(tmp_path / "jam.yaml.tmp", tmp_path / "jam.yaml")              # MOVED_TO
        assert wait_for(lambda: len(events) == 2)
        (tmp_path / "notes.txt").write_text("not a layout")                       # nothing
        (tmp_path / "jam.backup.yaml").write_text(JAM)                            # not a layout id: nothing
        (tmp_path / "jam.yaml").unlink()                                          # DELETE
        assert wait_for(lambda: len(events) == 3)
        wait_for(lambda: len(events) > 3, timeout=0.1)
        assert events == [("jam", ChangeKind.CHANGED), ("jam", ChangeKind.CHANGED), ("jam", ChangeKind.DELETED)]
        assert all(isinstance(layout, LayoutId) for layout, _ in events)
    finally:
        files.stop()


def test_event_mapping_for_each_inotify_kind(tmp_path):
    files = LayoutFiles(tmp_path)
    events = []
    files.changes(lambda layout, kind: events.append((layout, kind)))
    files.handle_events([InotifyEvent(IN_CLOSE_WRITE, "a.yaml"), InotifyEvent(IN_MOVED_TO, "b.yaml"),
                         InotifyEvent(IN_MOVED_FROM, "c.yaml"), InotifyEvent(IN_DELETE, "d.yaml"),
                         InotifyEvent(IN_CLOSE_WRITE, "e.yaml.tmp"), InotifyEvent(IN_CLOSE_WRITE, ".f.yaml.swp"),
                         InotifyEvent(IN_CLOSE_WRITE, "g.yml"), InotifyEvent(IN_DELETE, "bad name.yaml")])
    assert events == [("a", ChangeKind.CHANGED), ("b", ChangeKind.CHANGED), ("c", ChangeKind.DELETED),
                      ("d", ChangeKind.DELETED)]


def test_list_and_read_with_hash_and_missing(tmp_path):
    (tmp_path / "jam.yaml").write_bytes(JAM.replace("\n", "\r\n").encode())
    (tmp_path / "tonnetz.yaml").write_text("name: Tonnetz C\n")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "jam.yaml.tmp").write_text("x")
    files = LayoutFiles(tmp_path)
    assert files.list() == ["jam", "tonnetz"]
    text, content_hash = files.read(LayoutId("jam"))
    assert text == JAM.replace("\n", "\r\n")                        # bytes as written: no newline translation
    assert content_hash == ContentHash.of(text)
    assert files.read(LayoutId("gone")) is MISSING
    assert LayoutFiles(tmp_path / "not-mounted").list() == []      # a35: no directory reads as no layouts


def test_write_goes_through_a_synced_temp_file_and_one_rename(tmp_path, monkeypatch):
    # s83.c1: <name>.yaml.tmp, fsync, rename over <name>.yaml
    renames, syncs = [], []
    real_replace, real_fsync = os.replace, os.fsync
    monkeypatch.setattr(layout_files.os, "replace", lambda a, b: (renames.append((str(a), str(b))), real_replace(a, b)))
    monkeypatch.setattr(layout_files.os, "fsync", lambda fd: (syncs.append(fd), real_fsync(fd)))
    (tmp_path / "jam.yaml").write_text("old\n")
    files = LayoutFiles(tmp_path)
    files.write(LayoutId("jam"), JAM)
    assert renames == [(str(tmp_path / "jam.yaml.tmp"), str(tmp_path / "jam.yaml"))]
    assert syncs and (tmp_path / "jam.yaml").read_text() == JAM
    assert sorted(p.name for p in tmp_path.iterdir()) == ["jam.yaml"]
    assert files.read(LayoutId("jam")) == (JAM, ContentHash.of(JAM))


def test_our_own_write_is_seen_once_by_the_watch(tmp_path):
    # a22: a tweak's write reaches the pipeline exactly once
    files, events = watching(tmp_path, poll_interval=60)
    try:
        files.write(LayoutId("jam"), JAM)
        assert wait_for(lambda: events)
        wait_for(lambda: len(events) > 1, timeout=0.1)
        assert events == [("jam", ChangeKind.CHANGED)]
    finally:
        files.stop()


def test_without_inotify_a_stat_poll_reports_changes(tmp_path):
    def no_inotify(*args):
        raise OSError("no inotify on this mount")

    (tmp_path / "jam.yaml").write_text(JAM)
    files, events = watching(tmp_path, watch_factory=no_inotify, poll_interval=0.02)
    try:
        (tmp_path / "tonnetz.yaml").write_text("name: Tonnetz C\n")
        assert wait_for(lambda: ("tonnetz", ChangeKind.CHANGED) in events)
        stat = (tmp_path / "jam.yaml").stat()
        (tmp_path / "jam.yaml").write_text(JAM + "# more\n")
        os.utime(tmp_path / "jam.yaml", ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        assert wait_for(lambda: ("jam", ChangeKind.CHANGED) in events)
        (tmp_path / "tonnetz.yaml").unlink()
        assert wait_for(lambda: ("tonnetz", ChangeKind.DELETED) in events)
        assert sorted(set(events)) == sorted({("tonnetz", ChangeKind.CHANGED), ("jam", ChangeKind.CHANGED),
                                              ("tonnetz", ChangeKind.DELETED)})
        assert len(events) == 3
    finally:
        files.stop()


def test_the_poll_also_runs_beside_inotify_without_repeating_what_inotify_reported(tmp_path):
    files, events = watching(tmp_path, poll_interval=0.02)
    try:
        (tmp_path / "jam.yaml").write_text(JAM)
        assert wait_for(lambda: events)
        wait_for(lambda: len(events) > 1, timeout=0.15)    # several polls pass
        assert events == [("jam", ChangeKind.CHANGED)]
    finally:
        files.stop()


def test_a_directory_that_appears_later_is_picked_up(tmp_path):
    later = tmp_path / "layouts"
    files, events = watching(later, poll_interval=0.02)
    try:
        later.mkdir()
        (later / "jam.yaml").write_text(JAM)
        assert wait_for(lambda: ("jam", ChangeKind.CHANGED) in events)
    finally:
        files.stop()


def test_write_refuses_anything_but_a_layout_id(tmp_path):
    files = LayoutFiles(tmp_path)
    with pytest.raises(Exception):
        files.write("../escape", "x")
    assert list(tmp_path.iterdir()) == []
