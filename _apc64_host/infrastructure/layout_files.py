"""LayoutSource over the layouts directory (contract §7, s6/s57/s64/s83, inv18, inv19).

- list/read: *.yaml files whose stem is a LayoutId; read returns the exact text (no newline translation)
  and its ContentHash, or MISSING.
- write: <name>.yaml.tmp, fsync, one rename over <name>.yaml, so a reader never sees half a file.
- changes: inotify (CLOSE_WRITE | MOVED_TO → CHANGED, DELETE | MOVED_FROM → DELETED) on the directory; a stat
  poll every 2 s runs beside it as the fallback (a10, a35: a directory that is missing or loses its watch
  is still noticed). Other names (temp files, other suffixes, invalid stems) produce nothing (s6.c3).
  Callbacks go through `dispatch` (default: on the watch thread; the composition root passes
  loop.call_soon_threadsafe).
"""
import logging
import os
import select
import threading
from pathlib import Path
from typing import Callable

from ..application.ports import MISSING, ChangeKind
from ..domain.issues import DomainInvariantError
from ..domain.layout import ContentHash, LayoutId
from .inotify import Waker, IN_CLOSE_WRITE, IN_DELETE, IN_DELETE_SELF, IN_MOVE_SELF, IN_MOVED_FROM, IN_MOVED_TO, \
    IN_Q_OVERFLOW, Inotify

SUFFIX = ".yaml"
POLL_INTERVAL = 2.0
_WATCH_MASK = IN_CLOSE_WRITE | IN_MOVED_TO | IN_MOVED_FROM | IN_DELETE | IN_DELETE_SELF | IN_MOVE_SELF
_CHANGED_MASK = IN_CLOSE_WRITE | IN_MOVED_TO
_DELETED_MASK = IN_DELETE | IN_MOVED_FROM

log = logging.getLogger(__name__)


def layout_id_of(name: str) -> LayoutId | None:
    if not name.endswith(SUFFIX):
        return None
    try:
        return LayoutId(name[:-len(SUFFIX)])
    except DomainInvariantError:
        return None


def _direct(fn, *args):
    fn(*args)


class LayoutFiles:
    def __init__(self, directory, watch_factory=Inotify, poll_interval: float = POLL_INTERVAL,
                 dispatch: Callable = _direct):
        self._dir = Path(directory)
        self._watch_factory = watch_factory
        self._poll_interval = poll_interval
        self._dispatch = dispatch
        self._subscribers: list[Callable[[LayoutId, ChangeKind], None]] = []
        self._seen: dict[LayoutId, tuple[int, int]] = {}
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._waker: Waker | None = None

    # --- LayoutSource ------------------------------------------------------------------------------------
    def list(self) -> list[LayoutId]:
        try:
            names = os.listdir(self._dir)
        except OSError:
            return []
        return sorted(i for i in map(layout_id_of, names) if i is not None and (self._dir / names_of(i)).is_file())

    def read(self, layout: LayoutId) -> tuple[str, ContentHash] | None:
        try:
            text = (self._dir / names_of(LayoutId(layout))).read_bytes().decode("utf-8", "replace")
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            return MISSING
        return text, ContentHash.of(text)

    def write(self, layout: LayoutId, text: str) -> None:
        target = self._dir / names_of(LayoutId(layout))
        temporary = target.with_name(target.name + ".tmp")
        with open(temporary, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)

    def changes(self, callback: Callable[[LayoutId, ChangeKind], None]) -> None:
        self._subscribers.append(callback)

    # --- watching -------------------------------------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        with self._lock:
            self._seen = self._stat_all()
        self._stopped.clear()
        self._waker = Waker()
        watch = self._open_watch()   # before returning, so no write after start() is missed
        self._thread = threading.Thread(target=self._watch_loop, args=(watch,), name="apc64-layout-files",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._waker is not None:
            self._waker.wake()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._thread = None
        if self._waker is not None:
            self._waker.close()
            self._waker = None

    def handle_events(self, events) -> None:
        for event in events:
            if event.mask & IN_Q_OVERFLOW:
                self.poll()
                continue
            layout = layout_id_of(event.name)
            if layout is None:
                continue
            if event.mask & _CHANGED_MASK:
                with self._lock:
                    stat = self._stat(layout)
                    if stat is not None:
                        self._seen[layout] = stat
                self._emit(layout, ChangeKind.CHANGED)
            elif event.mask & _DELETED_MASK:
                with self._lock:
                    self._seen.pop(layout, None)
                self._emit(layout, ChangeKind.DELETED)

    def poll(self) -> None:
        """Compares the directory with what was last seen (the fallback beside inotify)."""
        with self._lock:
            now = self._stat_all()
            before, self._seen = self._seen, now
        for layout in sorted(now):
            if before.get(layout) != now[layout]:
                self._emit(layout, ChangeKind.CHANGED)
        for layout in sorted(set(before) - set(now)):
            self._emit(layout, ChangeKind.DELETED)

    def _emit(self, layout: LayoutId, kind: ChangeKind) -> None:
        for callback in list(self._subscribers):
            try:
                self._dispatch(callback, layout, kind)
            except Exception:
                log.exception("layout files: change callback failed")

    def _stat(self, layout: LayoutId) -> tuple[int, int] | None:
        try:
            stat = (self._dir / names_of(layout)).stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _stat_all(self) -> dict[LayoutId, tuple[int, int]]:
        found = {}
        for layout in self.list():
            stat = self._stat(layout)
            if stat is not None:
                found[layout] = stat
        return found

    def _open_watch(self):
        try:
            return self._watch_factory(self._dir, _WATCH_MASK)
        except OSError as error:
            log.info("layout files: no inotify on %s (%s); polling every %s s", self._dir, error,
                     self._poll_interval)
            return None

    def _watch_loop(self, watch) -> None:
        waker = self._waker
        try:
            while not self._stopped.is_set():
                if watch is None:
                    self._stopped.wait(self._poll_interval)
                    if self._stopped.is_set():
                        break
                    self._safely(self.poll)
                    watch = self._open_watch()
                    continue
                ready, _, _ = select.select([watch, waker], [], [], self._poll_interval)
                if self._stopped.is_set():
                    break
                if watch not in ready:
                    self._safely(self.poll)
                    continue
                events = watch.read()
                self._safely(self.handle_events, events)
                if any(e.mask & (IN_DELETE_SELF | IN_MOVE_SELF) for e in events):
                    watch.close()     # the directory itself went away: poll until it is back
                    watch = None
        finally:
            if watch is not None:
                watch.close()

    @staticmethod
    def _safely(fn, *args) -> None:
        try:
            fn(*args)
        except Exception:
            log.exception("layout files: watch step failed")


def names_of(layout: LayoutId) -> str:
    return f"{layout}{SUFFIX}"
