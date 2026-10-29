"""LabSession: the aggregate that owns slot 0 while a generated layout (or a library preview) is played
(contract §7.1: inv5, inv6, inv11; §2.7 a5/q9 and q4).

The session decides; the application does the I/O. Every call returns one decision:
  NeedBackup  — the first activation: read slot 0, store it as the session backup, then call started()
  Write       — write this record to slot 0 (OLED rows, notes to end at the target, whether a full backup of
                slots 1–24 is due right after this write)
  Unchanged   — nothing to write (d7: identical pads under a new name); show the OLED rows
  EdgeHit     — the step was refused at the edge of 0–127 (d29) or of the generator's window range
  Paused      — the unit is not in Custom view; nothing moves (d22)
  ShowOled    — only the OLED changes (Tempo cycled the interval)
  Ended       — the session is over: restore this record, or report the backup, or end quietly
  Ignored     — nothing to do (no session, a preview has no window, …)

Rules:
- One backup of slot 0 is taken before the session's first write; window shifts take no further backups (d75).
- Each session takes a full backup of slots 1–24 right after its first slot-0 write, unless one is younger than
  10 minutes (§2.7 a5/q9), so an on-unit save of the generated layout stays recoverable.
- A Project-view report or a slot-0 read that differs from the last record written means the user changed
  projects on the unit: the session ends quietly — nothing written, no restore over the new project, the
  pre-session backup kept (§2.7 a5/q9). Coming back to a generated layout starts a fresh session.
- Every activation asks for Custom view while the unit is not (known to be) in it, the first and each switch within
  a running session alike (amended 2026-10-27: the unit obeys the request; activation is explicit intent).
- At end, release, stop or SIGTERM, slot 0 is restored from the session backup only while it still holds the
  last record written (inv5, inv6); after an unplug the backup is named instead (d80, A43).
"""
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Callable

from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.layout import ControlEvent
from _apc64_host.domain.oled import OledText

from .lab_section import INTERVAL_CYCLE, WINDOW_SHIFT, LabDefinition
from .memory import full_backup_due
from .pads import NoteSpan, PadGrid
from .records import ProjectRecord, StripAssignment
from .window import Edge, LabWindow, StepWindow, WindowSpec, window_for

CUSTOM_VIEW_OFF = "Custom view off"   # the page's message (d22, A38)
CUSTOM_OFF_OLED = "Custom off"        # 'Custom view off' is 15 characters; the OLED shows 14 (a build decision)
PRESS_CUSTOM = "Press Custom"
RESTORED_MESSAGE = "slot 0 restored; the unit shows the project as unsaved, nothing was saved"


class EndReason(StrEnum):
    LEFT = "left"            # another (host) layout was loaded (A44)
    RELEASE = "release"      # the host released the unit (A42)
    STOP = "stop"
    SIGTERM = "sigterm"
    GONE = "gone"            # unplugged (A43)


class State(StrEnum):
    IDLE = "idle"
    STARTING = "starting"    # waiting for the session backup
    ACTIVE = "active"
    ENDED = "ended"


@dataclass(frozen=True)
class SessionLayout:
    """What a session plays: a generated layout (render + span) or a library preview (a whole record, q4)."""
    layout_id: str
    name: str
    definition: LabDefinition | None = None
    render: Callable[[int], PadGrid] | None = field(default=None, compare=False)
    span: NoteSpan | None = None
    preview: ProjectRecord | None = None
    window_spec: WindowSpec | None = None   # the generator's own window steps and range (None: Oct/5th/3rd)

    @property
    def generated(self) -> bool:
        return self.render is not None

    @classmethod
    def of_grid(cls, layout_id: str, name: str, render: Callable[[int], PadGrid],
                definition: LabDefinition | None = None, window_spec: WindowSpec | None = None) -> "SessionLayout":
        return cls(layout_id, name, definition, render, render(0).span(), window_spec=window_spec)

    def new_window(self) -> "LabWindow | StepWindow":
        """Where each activation starts (d38; a generator's own window at its start)."""
        return window_for(self.window_spec)

    @property
    def strips(self) -> dict[int, StripAssignment]:
        return dict(self.definition.strips) if self.definition else {}


# --- decisions -------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class NeedBackup:
    pass


@dataclass(frozen=True)
class Write:
    record: ProjectRecord
    oled: OledText
    end_notes: tuple[int, ...] = ()
    full_backup: bool = False
    prompt_custom: bool = False   # the unit is not (known to be) in Custom view: show 'Press Custom' if it stays so
    quiet: bool = False           # a repaint (the performer's control pads): the OLED and held notes stay as they are


@dataclass(frozen=True)
class Unchanged:
    oled: OledText
    prompt_custom: bool = False   # an activation while the unit is in another view: ask for Custom all the same


@dataclass(frozen=True)
class EdgeHit:
    oled: OledText
    flash: OledText | None = None   # shown briefly first ('Neck end'), then `oled` (2026-10-27)


@dataclass(frozen=True)
class Paused:
    oled: OledText
    message: str = CUSTOM_VIEW_OFF


@dataclass(frozen=True)
class ShowOled:
    oled: OledText
    flash: OledText | None = None   # shown briefly first ('Step: Page'), then `oled`


@dataclass(frozen=True)
class Ended:
    reason: str
    quiet: bool = False
    restore: ProjectRecord | None = None
    backup_id: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class Ignored:
    why: str


Decision = NeedBackup | Write | Unchanged | EdgeHit | Paused | ShowOled | Ended | Ignored


@dataclass
class LabSession:
    state: State = State.IDLE
    layout: SessionLayout | None = None
    window: LabWindow | StepWindow = field(default_factory=LabWindow)
    view: UnitView | None = None
    backup: ProjectRecord | None = None
    backup_id: str | None = None
    last_written: ProjectRecord | None = None

    # --- reading -------------------------------------------------------------------------------------
    @property
    def active(self) -> bool:
        return self.state is State.ACTIVE

    @property
    def expected(self) -> ProjectRecord | None:
        """What slot 0 should hold now: the last record this session wrote."""
        return self.last_written

    def oled(self, edge: bool = False) -> OledText:
        if self.layout is None:
            return OledText.blank()
        if not self.layout.generated:
            return OledText(self.layout.name, "preview")
        return self.window.oled(self.layout.name, edge)

    def may_overwrite(self, slot0_now: ProjectRecord | None) -> bool:
        """inv5: never write over a slot 0 that differs from the record written last."""
        return self.last_written is None or slot0_now == self.last_written

    @staticmethod
    def held_to_end(held) -> tuple[int, ...]:
        """The notes to end at the target at a shift or switch (d47): every held note, once, lowest first."""
        return tuple(sorted(set(held)))

    # --- starting and switching ----------------------------------------------------------------------
    def activate(self, layout: SessionLayout, held=()) -> Decision:
        """Start a session, or switch the active one to another layout at a fresh window (d38)."""
        if self.state in (State.IDLE, State.ENDED):
            self._fresh(layout)
            self.state = State.STARTING
            return NeedBackup()
        if self.state is State.STARTING:
            self.layout, self.window = layout, layout.new_window()
            return NeedBackup()
        self.layout, self.window = layout, layout.new_window()
        decision = self._write_current(held)
        if self.view is not UnitView.CUSTOM:   # activation is explicit intent: ask for Custom view again (d21)
            decision = replace(decision, prompt_custom=True)
        return decision

    def started(self, backup: ProjectRecord, backup_id: str, last_full_backup_at: float | None,
                now: float) -> Decision:
        """The session backup is stored: the first write, with the full-backup flag (§2.7 a5/q9)."""
        if self.state is not State.STARTING:
            return Ignored("no session is starting")
        self.backup, self.backup_id, self.state = backup, backup_id, State.ACTIVE
        record = self._record()
        self.last_written = record
        return Write(record, self.oled(), (), full_backup_due(last_full_backup_at, now),
                     self.view is not UnitView.CUSTOM)

    def reloaded(self, layout: SessionLayout, held=()) -> Decision:
        """The active layout's definition changed (d9, A15): rewrite at the current interval and offset."""
        if not self.active:
            return Ignored("no active session")
        span = layout.span
        if isinstance(self.window, StepWindow) or layout.window_spec is not None:
            # the generator's own window: kept while the new range holds it (a tweak of frets or tuning)
            kept = self.window.within(layout.window_spec) if isinstance(self.window, StepWindow) else None
            self.window = kept or layout.new_window()
        if layout.generated and span is not None and not span.fits(self.window.transposition()):
            self.window = layout.new_window()   # the new definition does not fit where the window was
        self.layout = layout
        return self._write_current(held)

    def repaint(self) -> Decision:
        """The same layout and window written again (what render gives has changed: the performer's selected chord
        type or pattern slot lights its pad); held notes are not ended and the OLED stays."""
        if not self.active or self.layout is None or not self.layout.generated:
            return Ignored("no active generated layout")
        record = self._record()
        if record == self.last_written:
            return Ignored("slot 0 holds it already")
        self.last_written = record
        return Write(record, self.oled(), (), quiet=True)

    def _fresh(self, layout: SessionLayout):
        self.layout, self.window = layout, layout.new_window()
        self.backup = self.backup_id = self.last_written = None

    # --- playing -------------------------------------------------------------------------------------
    def on_control(self, action: str, event: ControlEvent, held=()) -> Decision:
        """A ModuleAction from the encoder or Tempo (unit or replica, A37): the same path."""
        if action == WINDOW_SHIFT:
            return self.shift(event.steps, held)
        if action == INTERVAL_CYCLE:
            return self.cycle_interval()
        return Ignored(f"no lab action {action}")

    def shift(self, steps: int, held=()) -> Decision:
        if not self.active:
            return Ignored("no active session")
        if self.view is not None and self.view is not UnitView.CUSTOM:
            return Paused(OledText(self.layout.name, CUSTOM_OFF_OLED))
        if not self.layout.generated:
            return Ignored("a preview has no window")
        moved = self.window.shifted(steps, self.layout.span)
        if isinstance(moved, Edge):
            return EdgeHit(moved.oled(self.layout.name), moved.flash(self.layout.name))
        self.window = moved
        return self._write_current(held)

    def cycle_interval(self) -> Decision:
        if not self.active:
            return Ignored("no active session")
        if self.view is not None and self.view is not UnitView.CUSTOM:
            return Paused(OledText(self.layout.name, CUSTOM_OFF_OLED))
        if not self.layout.generated:
            return Ignored("a preview has no window")
        self.window = self.window.cycled()
        return ShowOled(self.oled(), self.window.flash_step(self.layout.name))

    def on_view(self, view: UnitView) -> Decision:
        """A pad-mode report: Custom resumes, Project ends quietly (§2.7), any other view pauses (d22)."""
        self.view = view
        if not self.active:
            return Ignored("no active session")
        if view is UnitView.PROJECT:
            return self._end_quietly("project view")
        if view is UnitView.CUSTOM:
            return ShowOled(self.oled())
        return Paused(OledText(self.layout.name, CUSTOM_OFF_OLED))

    def on_slot0(self, slot0_now: ProjectRecord) -> Decision:
        """Slot 0 as read back: a record other than the last written means another project was loaded."""
        if not self.active:
            return Ignored("no active session")
        if self.may_overwrite(slot0_now):
            return Ignored("slot 0 holds the lab's record")
        return self._end_quietly("slot 0 changed on the unit")

    # --- ending --------------------------------------------------------------------------------------
    def end(self, reason: EndReason, slot0_now: ProjectRecord | None = None) -> Decision:
        """Leaving the layout, release, stop, SIGTERM or unplug (inv6)."""
        if self.state is State.ENDED or self.state is State.IDLE:
            return Ended(str(reason), quiet=True, backup_id=self.backup_id)
        if self.state is State.STARTING or self.last_written is None:
            self.state = State.ENDED
            return Ended(str(reason), quiet=True)
        self.state = State.ENDED
        if reason is EndReason.GONE:
            return Ended(str(reason), backup_id=self.backup_id,
                         message=f"slot 0 could not be restored; restore {self.backup_id} after reconnecting")
        if slot0_now is not None and slot0_now != self.last_written:   # §2.7: never restore over a new project
            return Ended(str(reason), quiet=True, backup_id=self.backup_id)
        if self.backup == self.last_written:
            return Ended(str(reason), quiet=True, backup_id=self.backup_id)   # nothing to put back
        return Ended(str(reason), restore=self.backup, backup_id=self.backup_id, message=RESTORED_MESSAGE)

    def _end_quietly(self, why: str) -> Ended:
        self.state = State.ENDED
        return Ended(why, quiet=True, backup_id=self.backup_id)

    # --- records -------------------------------------------------------------------------------------
    def _record(self) -> ProjectRecord:
        if not self.layout.generated:
            return self.layout.preview
        record = self.backup.with_pads(self.layout.render(self.window.transposition()))
        strips = self.layout.strips
        return record.with_strips(strips) if strips else record

    def _write_current(self, held=()) -> Decision:
        record = self._record()
        if record == self.last_written:
            return Unchanged(self.oled())
        self.last_written = record
        return Write(record, self.oled(), self.held_to_end(held))
