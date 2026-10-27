"""LayoutPipeline: a layout file write → live on the unit, or rejected with its errors (contract inv18–inv20).

change → settle (250 ms of quiet, restarted by every change) → read → content-hash dedupe → compile with
the current port catalog → register in the library → keep a version copy → swap it into the engine.
Invalid content never registers, never versions and never swaps: the last good layout keeps playing and
the errors show until a valid version is written (d116, d121). Identical content (our own tweak write
seen twice, a poll and an inotify edge, an unchanged save) does nothing (d76, a22). A deleted file stays
live from memory and is marked (d78). restore() writes a stored version back as the file; it then goes
live like any other write (d120).
"""
import logging
from dataclasses import dataclass

from ..domain.issues import LayoutIssue, Severity, SourceRef, in_line_order
from ..domain.layout import ContentHash, LayoutId, VersionId
from ..notation.compiler import compile_text
from .library import DuplicateName
from .ports import Cancellable, ChangeKind, Clock, LayoutSource, PortCatalog, VersionStore

log = logging.getLogger(__name__)
SETTLE = 0.25


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    issues: tuple[LayoutIssue, ...]
    warnings: tuple[LayoutIssue, ...]
    counts: object | None
    summary: str
    ports_checked: bool


@dataclass(frozen=True)
class Restored:
    version: VersionId


@dataclass(frozen=True)
class UnknownVersion:
    version: str


def _name_line(text: str) -> int:
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("name:"):
            return number
    return 1


class LayoutPipeline:
    def __init__(self, *, source: LayoutSource, versions: VersionStore, library, engine, clock: Clock,
                 catalog: PortCatalog | None = None, compile=compile_text, settle: float = SETTLE):
        self._source, self._versions, self._library = source, versions, library
        self._engine, self._clock, self._catalog = engine, clock, catalog
        self._compile, self._settle = compile, settle
        self._timers: dict[LayoutId, Cancellable] = {}
        self._hashes: dict[LayoutId, ContentHash] = {}
        self.compiles = 0

    def start(self) -> None:
        """Loads every layout file now, then follows changes."""
        self._source.changes(self.changed)
        for layout_id in self._source.list():
            self._load(layout_id)

    # --- changes ------------------------------------------------------------------------------------
    def changed(self, layout_id: LayoutId, kind: ChangeKind = ChangeKind.CHANGED) -> None:
        layout_id = LayoutId(layout_id)
        timer = self._timers.pop(layout_id, None)
        if timer is not None:
            timer.cancel()
        self._timers[layout_id] = self._clock.call_later(self._settle, lambda: self._settled(layout_id))

    def _settled(self, layout_id: LayoutId) -> None:
        self._timers.pop(layout_id, None)
        try:
            self._load(layout_id)
        except Exception:   # a bug here must not stop the next change from loading
            log.exception("pipeline: loading %s failed", layout_id)

    def _load(self, layout_id: LayoutId) -> None:
        read = self._source.read(layout_id)
        if read is None:
            self._hashes.pop(layout_id, None)
            self._library.mark_deleted(layout_id)
            return
        text, content_hash = read
        if self._hashes.get(layout_id) == content_hash:
            return
        self._hashes[layout_id] = content_hash
        file = f"{layout_id}.yaml"
        self.compiles += 1
        result = self._compile(text, file, self._ports())
        if not result.valid:
            self._library.set_issues(layout_id, result.issues)
            return
        answer = self._library.register(layout_id, result.layout, result.warnings)
        if isinstance(answer, DuplicateName):
            other = f"{answer.other}.yaml"
            self._library.set_issues(layout_id, [LayoutIssue(
                Severity.ERROR, SourceRef(file, _name_line(text)), None,
                f"layout name {answer.name} is already used by {other}",
                f"rename one of them; {other} stays loaded")])
            return
        newest = self._versions.list(layout_id)[:1]
        if not newest or newest[0].hash != content_hash:
            self._versions.save(layout_id, text, content_hash)
        self._engine.swap(layout_id, result.layout)

    def _ports(self) -> list[str] | None:
        return [p.name for p in self._catalog.list()] if self._catalog is not None else None

    # --- the API's side (s17) -------------------------------------------------------------------------
    def validate_text(self, text: str, file: str = "layout.yaml") -> ValidationReport:
        """Validates text without applying it (d124); the same issue text the page shows (d115)."""
        result = self._compile(text, file, self._ports())
        return ValidationReport(result.valid, tuple(in_line_order(result.issues)), tuple(result.warnings),
                                result.counts, result.summary(), result.ports_checked)

    def versions(self, layout_id) -> list[VersionId]:
        return self._versions.list(LayoutId(layout_id))

    def restore(self, layout_id, version) -> Restored | UnknownVersion:
        layout_id = LayoutId(layout_id)
        wanted = str(version)
        match = next((v for v in self._versions.list(layout_id) if v == version or str(v) == wanted), None)
        text = self._versions.read(layout_id, match) if match is not None else None
        if text is None:
            return UnknownVersion(wanted)
        self._source.write(layout_id, text)
        self.changed(layout_id)   # also without a file watch; a watch event for it lands in the same window
        return Restored(match)
