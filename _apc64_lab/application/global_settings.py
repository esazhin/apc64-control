"""GlobalSettingsService: read and change the unit's global block (contract pi6; inv8, inv9, inv10; d88–d94).

One command may change several fields with one backup and one write (d92). Fields already at the asked value
are left out; a change of nothing writes nothing and says so (d94, A67). Device-mode and sync changes need an
explicit confirmation (inv8, d91, A64); a field already at its value needs none. Every write goes through
GuardedWriter's command path: read → backup → merge (bytes 0–19 kept, inv3) → write → read-back → rollback.

[TBD, bounded by a17] Whether 0x18 is accepted while the host holds the unit in DAW mode is checked only in the
attended live gate; a refusal there shows as a failed read-back with the block restored from its backup.
"""
from typing import Mapping

from _apc64_host.domain.issues import DomainInvariantError

from ..domain.memory import OutcomeCode, WriteOutcome
from ..domain.records import Confirmation, GlobalChange, GlobalSettings
from .guarded_writer import GuardedWriter, invalid, refused
from .ports import MemoryFault
from .project_memory import _read_fault


def _joined(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


class GlobalSettingsService:
    def __init__(self, writer: GuardedWriter):
        self._writer = writer

    def read(self) -> dict | WriteOutcome:
        """GET /api/lab/globals: every named field with its shown value (A62), and the raw block."""
        try:
            settings = self._writer.read_globals()
        except MemoryFault as fault:
            return _read_fault(fault, "the global settings", "nothing read")
        return {"fields": settings.fields(), "raw": settings.raw.hex(" ")}

    def change(self, changes: Mapping, confirm: bool = False) -> WriteOutcome:
        try:
            change = GlobalChange.parse(dict(changes or {}))                                 # A66, d93
        except DomainInvariantError as error:
            return invalid(error)
        if not change:
            return refused("no setting given", OutcomeCode.INVALID, "changes",
                           "give field=value pairs, e.g. led_level=100")
        confirmation = Confirmation() if confirm is True else None
        written: dict = {}

        def merge(current: GlobalSettings) -> GlobalSettings:
            differing = current.changed_by(change)
            differing.check(confirmation)                                                   # A64, d91
            after = current.with_change(differing)
            written["text"] = _joined([after.describe(key) for key in differing.fields]) if differing else ""
            return after

        return self._writer.write_globals(merge, what="change of the global settings",
                                          success=lambda backup: f"set {written['text']}",
                                          unchanged=f"{change.labels()} unchanged; nothing written")   # A67
