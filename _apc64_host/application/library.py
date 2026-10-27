"""LayoutLibrary: every layout file's last good compile, its issues and warnings (contract d65, d75, d78, d116).

The library holds no limit on the number of layouts (inv4). A layout whose display name another loaded
layout already uses is refused with DuplicateName naming that layout; the one already loaded stays. A
file that fails to compile keeps its last good layout and shows its errors until a valid version is
registered. A deleted file's layout stays compiled from memory (it may be live) and is marked deleted.
"""
import threading
from dataclasses import dataclass
from typing import Callable

from ..domain.issues import LayoutIssue, in_line_order
from ..domain.layout import Layout, LayoutCatalog, LayoutId


@dataclass(frozen=True)
class Registered:
    pass


@dataclass(frozen=True)
class DuplicateName:
    other: LayoutId
    name: str


@dataclass(frozen=True)
class LayoutSummary:
    id: LayoutId
    name: str
    valid: bool
    pages: int
    banks: int
    errors: int = 0
    warnings: int = 0
    deleted: bool = False

    @property
    def file(self) -> str:
        return f"{self.id}.yaml"


@dataclass
class _Entry:
    layout: Layout | None = None
    warnings: tuple[LayoutIssue, ...] = ()
    issues: tuple[LayoutIssue, ...] = ()
    deleted: bool = False


class LayoutLibrary:
    def __init__(self):
        self._entries: dict[LayoutId, _Entry] = {}
        self._subscribers: list[Callable[[], None]] = []
        self._lock = threading.RLock()

    # --- the pipeline's side --------------------------------------------------------------------------
    def register(self, layout_id: LayoutId, layout: Layout, warnings=()) -> Registered | DuplicateName:
        layout_id = LayoutId(layout_id)
        with self._lock:
            name = layout.display_name.casefold()
            for other, entry in self._entries.items():
                if other != layout_id and entry.layout is not None and not entry.deleted \
                        and entry.layout.display_name.casefold() == name:
                    return DuplicateName(other, layout.display_name)
            self._entries[layout_id] = _Entry(layout, tuple(warnings))
        self._notify()
        return Registered()

    def set_issues(self, layout_id: LayoutId, issues) -> None:
        """The file's current content is invalid: its errors show, its last good layout stays."""
        layout_id = LayoutId(layout_id)
        with self._lock:
            entry = self._entries.setdefault(layout_id, _Entry())
            entry.issues = tuple(in_line_order(issues))
            entry.deleted = False
        self._notify()

    def mark_deleted(self, layout_id: LayoutId) -> None:
        layout_id = LayoutId(layout_id)
        with self._lock:
            entry = self._entries.get(layout_id)
            if entry is None:
                return
            if entry.layout is None:   # nothing was ever loaded from it: forget it
                del self._entries[layout_id]
            else:
                entry.deleted, entry.issues = True, ()
        self._notify()

    # --- readers --------------------------------------------------------------------------------------
    def compiled(self, layout_id) -> Layout | None:
        entry = self._entries.get(str(layout_id))
        return entry.layout if entry else None

    def deleted(self, layout_id) -> bool:
        entry = self._entries.get(str(layout_id))
        return bool(entry and entry.deleted)

    def ids(self) -> list[LayoutId]:
        return sorted(self._entries)

    def catalog(self) -> LayoutCatalog:
        """The browsable layouts (loaded and with a file), alphabetical by display name."""
        with self._lock:
            return LayoutCatalog.of((i, e.layout.display_name) for i, e in self._entries.items()
                                    if e.layout is not None and not e.deleted)

    def summaries(self) -> list[LayoutSummary]:
        """Browse order first, then files with nothing loaded, by file name."""
        with self._lock:
            order = {i: n for n, i in enumerate(self.catalog().ids)}
            rows = []
            for layout_id, entry in self._entries.items():
                layout = entry.layout
                rows.append(LayoutSummary(
                    layout_id, layout.display_name if layout else str(layout_id),
                    layout is not None and not entry.issues, len(layout.pages) if layout else 0,
                    len(layout.banks) if layout else 0, len(entry.issues), len(entry.warnings), entry.deleted))
        return sorted(rows, key=lambda s: (s.id not in order, order.get(s.id, 0), s.id))

    def issues(self, layout_id) -> tuple[LayoutIssue, ...]:
        entry = self._entries.get(str(layout_id))
        return entry.issues if entry else ()

    def warnings(self, layout_id) -> tuple[LayoutIssue, ...]:
        entry = self._entries.get(str(layout_id))
        return entry.warnings if entry else ()

    def all_issues(self) -> list[LayoutIssue]:
        with self._lock:
            return in_line_order(i for e in self._entries.values() for i in e.issues)

    def subscribe(self, callback: Callable[[], None]) -> None:
        self._subscribers.append(callback)

    def _notify(self) -> None:
        for callback in list(self._subscribers):
            callback()
