"""SessionService and Slot0Writer: a generated layout (or a library preview) played in slot 0 (contract §7.1;
inv5, inv6, inv7, inv11; §2.7 a2, a5/q9, q3, q4; a8; d21, d22, d38, d47, d75, d80).

The LabSession aggregate decides; this service does the I/O and talks to the host:
- Activation backs slot 0 up once (the session backup, with an open-session marker beside it), then writes the
  layout at Oct +0. Right after that first write a full backup of slots 1–24 runs in the background (or a full
  backup younger than 10 minutes is reused), so an on-unit save of the generated layout stays recoverable. It
  steps aside for every slot-0 write, so it never delays an encoder shift (§2.7 a5/q9).
- Encoder and Tempo (unit or replica) shift the window or cycle the interval. Slot0Writer is latest-wins and
  paced on transmission only (§2.7 a2): a write waits for the previous write to be sent, never for a read-back;
  intermediate positions of a burst are skipped. The read-back runs once the burst settles.
- Slot-0 decision (inv4 vs §2.7 a5/q9): a read-back equal to any record this session sent is fine (an
  earlier one only means a later write is still on its way); slot 0 matching nothing the lab sent means the user
  changed projects — the session ends quietly: nothing written, no restore over their project, the session backup
  kept and listed. A Project-view report ends it the same way. Returning to a generated layout starts a fresh
  session.
- Ending (another layout loaded, leaving a preview, release, stop/SIGTERM, an engine fault) restores the session
  backup only while slot 0 still holds a record the lab wrote (inv5, inv6). After an unplug, nothing can be sent:
  the page names the backup to restore (A43), and the open-session marker stays so the next take offers it (a8).
- A marker left by a session that never ended (a crash, an unplug) is a pending recovery: the lab does not take
  slot 0 again until slot 0 is restored from that backup or the recovery is dismissed (a8).
- The key (2026-10-29): a layout's key is its scale overlay (scheme: scale, its scale and root). set_key changes it
  for the session, not the file: the layout's scheme played as 'scale' with that scale and tonic, or as 'fifths'
  (no key: chromatic), kept per layout while the service runs (a reload of the file keeps it; reset_key goes back
  to the file's). The pads are written again at the same window. Every publish hands the key of the layout playing
  to the performer (on_scale), which plays its chords in key from it.

Threads: hooks and actions arrive on the host's loop and never block (they decide and hand records to the
writer). The writer's own thread does the slot I/O. on_release runs inside the session's release and may block:
it stops the writer, reads slot 0 and restores. `_lock` (the session state) is always taken innermost, never
while waiting for the unit, so the writer's thread and the loop cannot deadlock.
"""
import hashlib
import logging
import threading
import time
from dataclasses import replace
from datetime import datetime
from typing import Callable, Iterable, Iterator

from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.layout import UnitPortRole
from _apc64_host.domain.oled import OledText
from _apc64_host.domain.unit_status import ReleaseReason

from ..domain.generators import describe_of
from ..domain.harmony.scales import closest_scale, find_scale
from ..domain.harmony.spelling import parse_pitch_class, pc_name
from ..domain.lab_section import LabDefinition
from ..domain.memory import (
    EDIT_BUFFER, BackupId, OutcomeCode, OutcomeKind, Slot, WriteOutcome,
)
from ..domain.note_target import NOT_ROUTED_TEXT, NoteTarget
from ..domain.performer_pads import with_controls
from ..domain.records import ProjectRecord
from ..domain.session import (
    CUSTOM_VIEW_OFF, PRESS_CUSTOM, RESTORED_MESSAGE, EdgeHit, Ended, EndReason, Ignored, LabSession, NeedBackup,
    Paused, SessionLayout, ShowOled, State, Unchanged, Write,
)
from .guarded_writer import GuardedWriter, refused
from .ports import (
    SET_SESSION, BackupStore, Gone, HostLink, Interrupted, LabState, LabStatePublisher, MalformedReply,
    MemoryFault, NoReply, NotHeld, NullPublisher, StorageError, UnitControl, WrongFirmware,
)
from .registry import DefinitionIndex, GeneratorRegistry

log = logging.getLogger(__name__)
SETTLE = 0.03          # the burst has settled when no write came for this long: then read back
POLL = 0.002           # how often a wait checks for a newer write (inv7)
FLASH_FOR = 1.0        # a brief OLED message ('Step: Page', 'Neck end') before row 2 shows the window again
CUSTOM_PROMPT_AFTER = 1.0   # d21: 'Press Custom' 1 s after an activation whose Custom request could not be sent
_RELEASE_TO_END = {ReleaseReason.RELEASE: EndReason.RELEASE, ReleaseReason.STOP: EndReason.STOP,
                   ReleaseReason.UNPLUG: EndReason.GONE, ReleaseReason.FAULT: EndReason.RELEASE}


def _digest(record: ProjectRecord) -> str:
    return hashlib.sha256(record.raw).hexdigest()


def recovery_text(backup_id: str) -> str:
    return (f"the last lab session did not end cleanly; slot 0 may still hold a generated layout: "
            f"restore {backup_id} to slot 0, or dismiss")


# --- the writer's thread -----------------------------------------------------------------------------------
class Slot0Writer:
    """Latest wins, paced on transmission, a settle read-back, background steps at the lowest priority.

    Priorities on each step: a control job (start, leave) → the pending slot-0 write → the read-back (once the
    burst settled) → one background step (a slot of the full backup). threaded=False runs nothing until drain()
    (deterministic tests); the thread does the same steps as work arrives."""

    def __init__(self, writer: GuardedWriter, on_written: Callable[[ProjectRecord], None],
                 on_read_back: Callable[[ProjectRecord], None], on_fault: Callable[[MemoryFault], None],
                 threaded: bool = True, settle: float = SETTLE, monotonic: Callable[[], float] = time.monotonic,
                 allow: Callable[[], bool] | None = None):
        self._writer = writer
        self._allow = allow
        self._on_written, self._on_read_back, self._on_fault = on_written, on_read_back, on_fault
        self._settle, self._now = settle, monotonic
        self._cond = threading.Condition()
        self._jobs: list[Callable[[], None]] = []
        self._pending: ProjectRecord | None = None
        self._read_due: float | None = None
        self._background: list[Iterator] = []
        self._stopped = False
        self.sent: list[ProjectRecord] = []          # every record transmitted (tests and the state)
        self.sent_at: list[float] = []
        self._thread = None
        if threaded:
            self._thread = threading.Thread(target=self._run, name="apc64-lab-slot0", daemon=True)
            self._thread.start()

    # --- what the service hands over --------------------------------------------------------------------
    def job(self, fn: Callable[[], None]) -> None:
        with self._cond:
            self._jobs.append(fn)
            self._cond.notify()

    def submit(self, record: ProjectRecord) -> None:
        """The newest record wins: an older one not yet sent is dropped (d28: intermediate positions skipped)."""
        with self._cond:
            self._pending = record
            self._cond.notify()

    def read_again(self, after: float | None = None) -> None:
        with self._cond:
            self._read_due = self._now() + (self._settle if after is None else after)
            self._cond.notify()

    def background(self, steps: Iterator) -> None:
        with self._cond:
            self._background.append(steps)
            self._cond.notify()

    def cancel(self, background: bool = False) -> None:
        """Drops the pending write and the read-back (and the background work): the session is ending."""
        with self._cond:
            self._pending, self._read_due = None, None
            self._jobs.clear()
            if background:
                self._background.clear()

    def interrupt(self) -> bool:
        """For waits on the unit: True when a newer write or a job is due, or the writer stops (inv7)."""
        return self._pending is not None or bool(self._jobs) or self._stopped

    @property
    def idle(self) -> bool:
        with self._cond:
            return not (self._jobs or self._pending is not None or self._read_due is not None or self._background)

    def close(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)

    # --- the steps --------------------------------------------------------------------------------------
    def drain(self, limit: int = 10_000) -> None:
        """Runs every step now, a settle counting as passed (threaded=False)."""
        for _ in range(limit):
            if not self._step(ignore_settle=True):
                return

    def _next(self, ignore_settle: bool):
        with self._cond:
            if self._jobs:
                return "job", self._jobs.pop(0)
            if self._pending is not None:
                record, self._pending = self._pending, None
                return "write", record
            if self._read_due is not None and (ignore_settle or self._now() >= self._read_due):
                self._read_due = None
                return "read", None
            if self._background and self._read_due is None:
                return "background", self._background[0]
            return None, None

    def _step(self, ignore_settle: bool = False) -> bool:
        kind, item = self._next(ignore_settle)
        if kind is None:
            return False
        try:
            if kind == "job":
                item()
            elif kind == "write":
                if not self._writer.session_write(item, self._allow):
                    return True
                with self._cond:
                    self.sent.append(item)
                    self.sent_at.append(self._now())
                    if self._pending is None:
                        self._read_due = self._now() + self._settle
                self._on_written(item)
            elif kind == "read":
                record = self._writer.session_read(self.interrupt)
                self._on_read_back(record)
            else:
                try:
                    next(item)
                except StopIteration:
                    with self._cond:
                        if self._background and self._background[0] is item:
                            self._background.pop(0)
        except Interrupted:
            if kind == "read":
                with self._cond:
                    if self._read_due is None:
                        self._read_due = self._now() + self._settle
        except MemoryFault as fault:
            self._on_fault(fault)
        except Exception:   # a bug in a job must not stop the writer's thread
            log.exception("lab: slot-0 writer step %s failed", kind)
        return True

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._stopped:
                    if self._jobs or self._pending is not None:
                        break
                    if self._read_due is not None:
                        wait = self._read_due - self._now()
                        if wait <= 0:
                            break
                        self._cond.wait(wait)
                        continue
                    if self._background:
                        break
                    self._cond.wait()
                if self._stopped:
                    return
            self._step()


# --- the service -------------------------------------------------------------------------------------------
class SessionService:
    def __init__(self, writer: GuardedWriter, backups: BackupStore, registry: GeneratorRegistry, link: HostLink,
                 publisher: LabStatePublisher | None = None, control: UnitControl | None = None,
                 held_notes: Callable[[], Iterable[int]] = tuple, index: DefinitionIndex | None = None,
                 target: NoteTarget | None = None, wall: Callable[[], datetime] = datetime.now,
                 threaded: bool = True, settle: float = SETTLE, on_key: Callable[[dict | None], None] | None = None,
                 on_end_notes: Callable[[tuple], None] | None = None, controls: Callable | None = None,
                 on_scale: Callable | None = None):
        self._writer, self._backups, self._registry, self._link = writer, backups, registry, link
        self._publisher = publisher or NullPublisher()
        self._control = control
        self._held_notes = held_notes
        self._index = index
        self.target = target
        self._wall = wall
        self._on_key = on_key                   # the harmony tracker's set_key: the active layout's key spelling
        self._on_end_notes = on_end_notes       # the performer's end_held: the notes a window shift ended (§2.10)
        self._controls = controls               # the performer's control pads: {pad index: (pad, its label)}
        self._on_scale = on_scale               # the performer's set_key(layout id, the key's ScaleOverlay or None)
        self._keys: dict[str, tuple] = {}       # layout id → (scheme, scheme params): the session's key (set_key)
        self._files: dict[str, LabDefinition] = {}   # layout id → its definition as the file says it
        self._lock = threading.RLock()
        self._session = LabSession()
        self._layout = None                     # the engine's layout (host or generated)
        self._wanted: SessionLayout | None = None
        self._held = False
        self._starting = False
        self._ending = False
        self._written: set[str] = set()
        self._last_sent: ProjectRecord | None = None
        self._earlier = 0
        self._message: str | None = None
        self._flash = 0                         # bumped by every OLED change: a newer one cancels a pending flash
        self._recovery: BackupId | None = None
        self._last_full: dict | None = None
        self.slot0 = Slot0Writer(writer, self._written_cb, self._read_back_cb, self._fault_cb, threaded, settle,
                                 allow=self._may_write)
        left = backups.open_session_left()
        if left is not None:
            self._recovery = left
            self._message = recovery_text(left)

    # === reading ===========================================================================================
    @property
    def session(self) -> LabSession:
        return self._session

    @property
    def running(self) -> bool:
        return self._session.state in (State.STARTING, State.ACTIVE)

    @property
    def message(self) -> str | None:
        return self._message

    @property
    def recovery(self) -> BackupId | None:
        return self._recovery

    def transposition_of(self, layout_id) -> int | None:
        """The window's transposition when that generated layout is the one playing (q3: push stores it)."""
        with self._lock:
            layout = self._session.layout
            if self._session.active and layout is not None and layout.generated \
                    and str(layout.layout_id) == str(layout_id):
                return self._session.window.transposition()
            return None

    def state(self) -> LabState:
        with self._lock:
            listing = self._registry.listing()
            return LabState(tuple(listing["generators"]), tuple(listing["schemes"]), self._active_json(),
                            self._message,
                            {"backup": self._recovery, "message": recovery_text(self._recovery)}
                            if self._recovery else None,
                            self._target_json(), tuple(listing["refusals"]),
                            tuple(self._index.listing()) if self._index is not None else ())

    def _active_json(self) -> dict | None:
        session = self._session
        layout = session.layout
        if layout is None or not self.running:
            return None
        window = session.window
        record = session.last_written
        return {"layout": str(layout.layout_id), "name": layout.name, "preview": not layout.generated,
                **window.to_json(),   # interval, offset, counts, transposition and the window's steps
                "unit_view": str(session.view) if session.view is not None else None,
                "session_backup": session.backup_id, "oled": list(session.oled().rows),
                "starting": session.state is State.STARTING,
                "definition": {"generator": layout.definition.generator, "params": layout.definition.parameters,
                               "scheme": layout.definition.scheme,
                               "scheme_params": dict(layout.definition.scheme_params)}
                if layout.definition is not None else None,
                "key": self._key_json(str(layout.layout_id), layout.definition) if layout.generated else None,
                **self._grid_extras(layout.definition, record, window.transposition())}

    def _grid_extras(self, definition: LabDefinition | None, record, transposition: int) -> dict:
        """What the harmony pad grid needs beyond the pads: the generator's row names (the modes explorer's) and
        the scheme's scale overlay, and each pad's name: the generator's own spelling (each modes row in its
        mode), else the overlay's scale where the note is in it, else the fixed table; and a fretboard generator's
        neck (its strings, frets and channels) with the fret the window puts in column 1 ('first')."""
        rows = overlay = own = neck = None
        if definition is not None:
            try:
                rows = definition.row_labels(self._registry.generators())
                overlay = definition.overlay(self._registry.schemes())
                own = definition.pad_names(self._registry.generators(), transposition)
                neck = definition.neck(self._registry.generators())
            except Exception:   # a nicety for the page: never in the way of the state
                log.exception("lab: the pad grid's labels failed")
        names = dict(overlay.names) if overlay is not None else {}
        controls = self._control_pads(definition, labels=True)

        def name(i, pad):
            if pad.silent:
                return None
            if i in controls:
                return controls[i]
            return (own[i] if own and own[i] else None) or names.get(pad.note % 12) or pc_name(pad.note)
        pads = [{"pad": str(pos).removeprefix("pad "), "note": pad.note, "rest": pad.rest.to_hex(), "silent": pad.silent,
                 "name": name(i, pad), **({"control": True} if i in controls else {})}
                for i, (pos, pad) in enumerate(_pads(record))] if record is not None else []
        return {"pads": pads, "rows": list(rows) if rows else None,
                "scale": overlay.to_json() if overlay is not None else None,
                "neck": {**neck.to_json(), "first": transposition} if neck is not None else None}

    def _target_json(self) -> dict:
        default = self.target.text() if self.target else None
        rule = getattr(self._layout, "routing", {}).get(UnitPortRole.CUSTOM) if self._layout is not None else None
        if self._wanted is None and not self.running:
            return {"default": default}
        if rule is None:
            return {"default": default, "routed": False, "text": NOT_ROUTED_TEXT}
        source = "default" if self.target is not None and str(rule.device) == self.target.device else "layout"
        port = self._layout.devices.get(rule.device)
        text = f"{port.pattern if port else rule.device} ch {int(rule.channel)} aftertouch {rule.aftertouch}"
        return {"default": default, "routed": True, "from": source, "text": text}

    def publish(self) -> None:
        try:
            self._publisher.publish(self.state())
        except Exception:
            log.exception("lab: publishing the lab state failed")
        if self._on_scale is not None:
            with self._lock:
                wanted = self._wanted
            try:
                if wanted is not None:
                    self._on_scale(wanted.layout_id, self._overlay(wanted.definition))
            except Exception:
                log.exception("lab: handing the layout's key to the performer failed")
        if self._on_key is not None:
            try:
                self._on_key(self.key())
            except Exception:
                log.exception("lab: handing the layout's key to the harmony views failed")

    def key(self) -> dict | None:
        """The playing layout's key spelling (its scale overlay's names, pitch class → name), or None: the harmony
        views spell held notes in it when they form no chord (2026-10-27)."""
        with self._lock:
            layout = self._session.layout if self.running else None
        definition = layout.definition if layout is not None else None
        if definition is None:
            return None
        try:
            overlay = definition.overlay(self._registry.schemes())
        except Exception:   # a nicety: never in the way of the state
            return None
        return dict(overlay.names) if overlay is not None and overlay.names else None

    # === the host's events (the loop; never blocking) ======================================================
    def on_held(self, unit=None) -> None:
        with self._lock:
            self._held = True
            self._ending = False
        self._writer.resume()
        left = self._backups.open_session_left()
        with self._lock:
            if left is not None and not self.running:
                self._recovery = left
                self._message = recovery_text(left)
            wanted = self._wanted
        if wanted is not None:
            self._activate(wanted)
        self.publish()

    def on_layout_loaded(self, layout, section) -> None:
        with self._lock:
            self._layout = layout
            if not isinstance(section, LabDefinition):
                self._wanted = None
                running = self.running
            else:
                running = None
        if running is not None:
            if running:
                self.slot0.cancel()
                self.slot0.job(lambda: self._finish_job(EndReason.LEFT))
            self.publish()
            return
        layout_id = str(getattr(layout, "id", "") or "")
        name = getattr(layout, "display_name", None) or layout_id
        if self._index is not None:
            self._index.record(layout_id, section)
            self._index.named(layout_id, name)
        try:
            playing = self._session_layout(layout_id, name, section)
        except Exception as error:   # a generator broken since compile: never written (d13)
            self._link.warn(f"{name}: the generator failed ({error}); nothing written")
            return
        with self._lock:
            previous, self._wanted = self._wanted, playing
            same = previous is not None and previous.layout_id == playing.layout_id
            if self._session.active and same and self._session.layout.layout_id == playing.layout_id:
                if previous.definition != playing.definition:
                    decision = self._session.reloaded(playing, self._held_notes())   # d9, A15: same window
                    self._handle(decision)
                    self.publish()
                    return
            elif same and previous.definition != playing.definition and not self.running:
                self.publish()   # an edit of a layout whose session ended: no new session from a file edit
                return
        self._activate(playing)
        self.publish()

    def on_view(self, view: UnitView) -> None:
        with self._lock:
            decision = self._session.on_view(view)
            if view is UnitView.CUSTOM and self._message in (PRESS_CUSTOM, CUSTOM_VIEW_OFF):
                self._message = None
        self._handle(decision)
        self.publish()

    def on_action(self, action: str, event) -> None:
        """A ModuleAction from the encoder or Tempo (unit or replica, A37)."""
        with self._lock:
            decision = self._session.on_control(action, event, self._held_notes())
        self._handle(decision)
        if not isinstance(decision, Ignored):
            self.publish()

    def led_suppressed(self) -> bool:
        """Pad LEDs are not drawn while a session plays in Custom view (§2.7 a4: cleanliness only)."""
        return self._session.active and self._session.view is UnitView.CUSTOM

    # === the session's release (blocking is allowed here) ==================================================
    def end(self, reason) -> None:
        """on_release: after DAW off, before detach. Restores or reports (inv6), then the unit is not held."""
        end_reason = _RELEASE_TO_END.get(reason, reason) if not isinstance(reason, EndReason) else reason
        with self._lock:
            self._held = False
            running = self.running
            self._ending = True
        self.slot0.cancel(background=True)
        if not running:
            return
        self._writer.abort()                     # waits in flight end at once
        with self._writer.exchange():
            self._writer.resume()
            self._finish(end_reason)
        self.publish()

    def leave(self) -> WriteOutcome:
        """Leave the generated layout or preview (the API's 'stop'): restore slot 0 as at a layout switch."""
        if not self.running:
            return WriteOutcome(OutcomeKind.UNCHANGED, "no lab session is running; nothing written")
        self.slot0.cancel()
        with self._writer.exchange():
            message = self._finish(EndReason.LEFT)
        self.publish()
        return WriteOutcome(OutcomeKind.RESTORED if message == RESTORED_MESSAGE else OutcomeKind.UNCHANGED,
                            message or "the lab session ended", self._session.backup_id)

    # === previews (q4) =====================================================================================
    def preview(self, name: str, record: ProjectRecord) -> WriteOutcome:
        if not self._held:
            return refused("take control of the APC64 first; nothing read or written", OutcomeCode.NOT_HELD)
        if self._recovery is not None:
            return refused(recovery_text(self._recovery), OutcomeCode.SESSION)
        self._activate(SessionLayout(f"library:{name}", name, preview=record))
        self.publish()
        return WriteOutcome(OutcomeKind.ACTIVATED, f"previewing {name} in slot 0; leave to restore slot 0")

    # === activation from the page, CLI or agent (s2.c2) ====================================================
    def activate(self, layout: str) -> WriteOutcome:
        """Loads a layout through the host's single load point; a generated one starts or switches the session."""
        found = self._index.resolve(layout) if self._index is not None else None
        layout_id = found.layout_id if found is not None else str(layout).strip()
        answer = self._link.load(layout_id)
        allowed = getattr(answer, "allowed", None)
        if allowed is not None:
            return refused(f"no layout {layout}", OutcomeCode.NOT_FOUND, "layout",
                           "layouts: " + ", ".join(map(str, allowed)))
        if answer is None:
            return refused("the host engine is not running; nothing loaded", OutcomeCode.NOT_HELD)
        name = found.name if found is not None else layout_id
        return WriteOutcome(OutcomeKind.ACTIVATED, f"activated {name}")

    # === recovery (a8) =====================================================================================
    def recovered(self, backup_id) -> None:
        """Slot 0 was restored from this backup: a pending recovery for it is done."""
        with self._lock:
            if self._recovery is None or str(backup_id) != str(self._recovery):
                return
            self._recovery, self._message = None, f"slot 0 restored from {backup_id}"
            wanted = self._wanted
        self._backups.close_session()
        if wanted is not None and self._held:
            self._activate(wanted)
        self.publish()

    def dismiss_recovery(self) -> WriteOutcome:
        with self._lock:
            backup, self._recovery = self._recovery, None
            if backup is None:
                return WriteOutcome(OutcomeKind.UNCHANGED, "no recovery is pending")
            self._message = f"recovery dismissed; {backup} stays listed"
            wanted = self._wanted
        self._backups.close_session()
        if wanted is not None and self._held:
            self._activate(wanted)
        self.publish()
        return WriteOutcome(OutcomeKind.UNCHANGED, self._message, backup)

    # === tweaks (d10, A16) =================================================================================
    def tweak(self, field: str, value, layout: str | None = None) -> object:
        """One 'lab:' field of the active generated layout, or of the named one (§3.5 POST /api/lab/tweak)."""
        if layout is not None and str(layout).strip():
            found = self._index.resolve(layout) if self._index is not None else None
            if found is None:
                names = sorted(i.name for i in self._index.all()) if self._index is not None else []
                return refused(f"no generated layout {layout}", OutcomeCode.NOT_FOUND, "layout",
                               "generated layouts: " + (", ".join(names) or "none"))
            layout_id, definition = found.layout_id, found.definition
        else:
            with self._lock:
                wanted = self._wanted
            if wanted is None:
                return refused("no generated layout is active; activate one first", OutcomeCode.SESSION)
            layout_id, definition = wanted.layout_id, wanted.definition
        path = field if str(field).startswith("lab.") else f"lab.{field}"
        generator = self._registry.generators().get(definition.generator) if definition is not None else None
        comment = describe_of(generator, path.split(".", 1)[1], value) if generator is not None else None
        return self._link.tweak(layout_id, path, value, comment)

    # === the key (2026-10-29) =============================================================================
    def set_key(self, tonic, scale=None) -> dict:
        """The key of the generated layout playing, for the session: `tonic` a note name and `scale` a scale of the
        library (default major), or tonic None for none (chromatic: the fifths scheme). The file is not changed;
        DomainInvariantError for a name it refuses or without a generated layout."""
        if tonic is None:
            override = ("fifths", ())
        else:
            pc = parse_pitch_class(str(tonic)) if str(tonic).strip() else None
            if pc is None:
                raise DomainInvariantError("tonic", f"'{tonic}' is not a note name",
                                           "write C, C♯ (or C#), D♭ (or Db) … B, without an octave")
            found = find_scale(scale or "major")
            if found is None:
                near = closest_scale(scale)
                raise DomainInvariantError("scale", f'no scale "{scale}"', (f"did you mean {near}? " if near else "")
                                           + "apc64 lab list shows the scales")
            override = ("scale", (("scale", found.key), ("root", pc)))
        return self._rekey(override)

    def reset_key(self) -> dict:
        """The layout's key as its file says it again."""
        return self._rekey(None)

    def _rekey(self, override) -> dict:
        with self._lock:
            wanted = self._wanted
            if wanted is None or wanted.definition is None:
                raise DomainInvariantError("layout", "no generated layout is active", "activate one first")
            layout_id = wanted.layout_id
            if override is None:
                self._keys.pop(layout_id, None)
            else:
                self._keys[layout_id] = override
            playing = self._session_layout(layout_id, wanted.name, self._files.get(layout_id, wanted.definition))
            self._wanted = playing
            decision = None
            if self._session.active and self._session.layout is not None \
                    and self._session.layout.layout_id == layout_id:
                decision = self._session.reloaded(playing, self._held_notes())   # the same window, repainted
            file_text = self._key_text(self._files.get(layout_id))
            now_text = self._key_text(playing.definition)
        if decision is not None:
            self._handle(decision)
        self.publish()
        if override is None:
            message = f"key {file_text}, as the layout's file says" if file_text else "no key, as the layout's file says"
        else:
            told = f"the layout's file says {file_text}" if file_text else "the layout's file has no key"
            message = (f"key {now_text} for the session ({told})" if now_text
                       else f"no key for the session: chromatic ({told})")
        return {**self.state().to_json(), "message": message}

    def _keyed(self, layout_id: str, definition: LabDefinition) -> LabDefinition:
        """The definition with the session's key, if one was set for that layout."""
        override = self._keys.get(layout_id)
        if override is None or definition is None:
            return definition
        return replace(definition, scheme=override[0], scheme_params=override[1])

    def _overlay(self, definition):
        try:
            return definition.overlay(self._registry.schemes()) if definition is not None else None
        except Exception:   # a nicety: never in the way of the state
            return None

    def _key_text(self, definition) -> str | None:
        """'C major', 'F♯ harmonic minor', or None (no key)."""
        overlay = self._overlay(definition)
        if overlay is None:
            return None
        return f"{dict(overlay.names).get(overlay.root) or pc_name(overlay.root)} {overlay.key.replace('-', ' ')}"

    def _key_json(self, layout_id: str, definition) -> dict:
        overlay = self._overlay(definition)
        return {"tonic": (dict(overlay.names).get(overlay.root) or pc_name(overlay.root)) if overlay else None,
                "scale": overlay.key if overlay else None, "session": layout_id in self._keys,
                "file": self._key_text(self._files.get(layout_id))}

    # === internals =========================================================================================
    def _session_layout(self, layout_id: str, name: str, definition: LabDefinition) -> SessionLayout:
        self._files[layout_id] = definition
        definition = self._keyed(layout_id, definition)
        generators, schemes = self._registry.generators(), self._registry.schemes()
        span = definition.grid(generators, schemes, 0).span()       # the notes the window moves (not the controls)

        def render(t):
            grid = definition.grid(generators, schemes, t)
            return with_controls(grid, self._control_pads(definition))
        return SessionLayout(layout_id, name, definition, render, span, window_spec=definition.window_spec(generators))

    def _control_pads(self, definition, labels: bool = False) -> dict:
        """{pad index: PadAssignment} of the performer's control pads ({pad index: label} with `labels`)."""
        if self._controls is None or definition is None:
            return {}
        try:
            found = self._controls(definition) or {}
        except Exception:   # the control pads are the performer's; never in the way of the layout
            log.exception("lab: the performer's control pads failed")
            return {}
        return {i: pair[1 if labels else 0] for i, pair in found.items()}

    def repaint(self) -> None:
        """The performer's selection changed: slot 0 written again at the same window (latest wins)."""
        with self._lock:
            decision = self._session.repaint()
        self._handle(decision)
        if not isinstance(decision, Ignored):
            self.publish()

    def _activate(self, playing: SessionLayout) -> None:
        with self._lock:
            if not self._held:
                return
            if self._recovery is not None:
                self._message = recovery_text(self._recovery)
                warn = True
            else:
                warn = False
                decision = self._session.activate(playing, self._held_notes())
        if warn:
            self._link.warn(f"restore {self._recovery} to slot 0 first")
            return
        self._handle(decision)

    def _handle(self, decision) -> None:
        match decision:
            case NeedBackup():
                with self._lock:
                    if self._starting:
                        return
                    self._starting = True
                self.slot0.job(self._start_job)
            case Write():
                self._submit(decision)
            case Unchanged(oled=oled, prompt_custom=prompt):
                self._rest(oled)
                if prompt:
                    self._ask_for_custom()
            case EdgeHit(oled=oled, flash=flash) | ShowOled(oled=oled, flash=flash):
                self._rest(oled, flash)
            case Paused(oled=oled, message=message):
                with self._lock:
                    self._message = message
                self._rest(oled)
            case Ended():
                self._quiet_end(decision)
            case _:
                pass

    def _rest(self, oled: OledText | None, flash: OledText | None = None) -> None:
        """The resting OLED text; with a flash, the flash first and `oled`'s window again after FLASH_FOR, unless a
        newer OLED change came in between (a newer step or toggle cancels a pending flash)."""
        with self._lock:
            self._flash += 1
            token = self._flash
        if flash is None:
            self._link.resting(oled)
            return
        self._link.resting(flash)
        self._link.call_later(FLASH_FOR, lambda: self._flash_over(token))

    def _flash_over(self, token: int) -> None:
        with self._lock:
            if token != self._flash or not self._session.active:
                return
            oled = self._session.oled()
        self._link.resting(oled)

    def flash(self, text: str) -> None:
        """A brief message on the OLED's row 2 (the performer's 'Latch on'), then the window again (FLASH_FOR)."""
        with self._lock:
            if not self._session.active:
                return
            oled = self._session.oled()
        self._rest(oled, OledText(oled.rows[0], str(text)))

    def _submit(self, write: Write) -> None:
        self._link.end_notes(write.end_notes)
        if self._on_end_notes is not None and write.end_notes:
            try:
                self._on_end_notes(tuple(write.end_notes))
            except Exception:
                log.exception("lab: the performer could not end the held notes")
        if not write.quiet:
            self._rest(write.oled)
        self.slot0.submit(write.record)
        if write.full_backup:
            self.slot0.background(self._full_backup())
        if write.prompt_custom:
            self._ask_for_custom()

    def _ask_for_custom(self) -> None:
        """d21 as amended (2026-10-27): the unit obeys the request and the host then takes Custom view as reported,
        so 'Press Custom' is due only when the request could not be sent."""
        sent = False
        if self._control is not None:
            try:
                sent = bool(self._control.request_view(UnitView.CUSTOM))
            except MemoryFault:
                sent = False
        if not sent:
            self._link.call_later(CUSTOM_PROMPT_AFTER, self._custom_timeout)

    def _custom_timeout(self) -> None:
        with self._lock:
            session = self._session
            if not session.active or session.view is UnitView.CUSTOM:
                return
            self._message = PRESS_CUSTOM
            name = session.layout.name
        self._rest(OledText(name, PRESS_CUSTOM))                                    # d21, A23
        self.publish()

    # --- on the writer's thread -------------------------------------------------------------------------
    def _start_job(self) -> None:
        """Read slot 0, keep it as the session backup, then the first write (A22)."""
        try:
            self._writer.check_writable()
            record = self._writer.session_read()
            backup_id = self._writer.save_backup(EDIT_BUFFER, record.raw)
        except (MemoryFault, StorageError) as error:
            self._start_failed(error)
            return
        self._backups.open_session(backup_id)
        last = self._backups.last_full_backup_at()
        with self._lock:
            self._starting = False
            if self._ending or self._session.state is not State.STARTING:
                decision = None
            else:
                self._written, self._last_sent, self._earlier = set(), None, 0
                decision = self._session.started(record, backup_id, last.timestamp() if last else None,
                                                 self._wall().timestamp())
                if self._message in (CUSTOM_VIEW_OFF,) or (self._message or "").startswith("lab session ended"):
                    self._message = None
        if decision is None:
            self._backups.close_session()
            return
        self._handle(decision)
        self.publish()

    def _start_failed(self, error) -> None:
        if isinstance(error, NotHeld):
            text = "take control of the APC64 first; nothing written"
        elif isinstance(error, WrongFirmware):
            text = f"{error}; nothing written"
        elif isinstance(error, MalformedReply):
            text = f"{error.text('slot 0')}; nothing written"
        elif isinstance(error, StorageError):
            text = f"could not save the backup of slot 0 ({error.path}: {error.reason}); nothing written"
        else:
            text = "could not back up slot 0; nothing written"
        with self._lock:
            self._starting = False
            ending = self._ending
            self._session.end(EndReason.LEFT)
            if not ending:
                self._message = text
        if not ending:
            self._link.warn(text)
        self.publish()

    def _may_write(self) -> bool:
        """Asked with the unit's memory held, right before a session write: only while the session plays."""
        with self._lock:
            return self._session.active and not self._ending

    def _written_cb(self, record: ProjectRecord) -> None:
        with self._lock:
            self._written.add(_digest(record))
            self._last_sent = record

    def _read_back_cb(self, record: ProjectRecord) -> None:
        """The settle read-back of slot 0 (the slot-0 decision above)."""
        with self._lock:
            if not self._session.active:
                return
            if record == self._last_sent:
                self._earlier = 0
                return
            if _digest(record) in self._written:             # an earlier write of ours: a later one is on its way
                self._earlier += 1
                resend = self._last_sent if self._earlier >= 2 else None
                if resend is not None:
                    self._earlier = 0
            else:
                decision = self._session.on_slot0(record)    # the user changed projects: end quietly
                resend = None
        if _digest(record) in self._written:
            if resend is not None:
                self.slot0.submit(resend)
            else:
                self.slot0.read_again()
            return
        self._handle(decision)
        self.publish()

    def _fault_cb(self, fault: MemoryFault) -> None:
        if isinstance(fault, (NotHeld, Gone)):
            return   # the release follows and decides
        log.warning("lab: slot-0 %s", fault)
        self._link.warn(f"slot 0: {fault}")

    def _finish_job(self, reason: EndReason) -> None:
        with self._writer.exchange():
            self._finish(reason)
        self.publish()

    def _finish(self, reason: EndReason) -> str | None:
        """The end of a session, holding the unit's memory: restore over the lab's own record, or report."""
        with self._lock:
            session = self._session
            if session.state not in (State.STARTING, State.ACTIVE):
                return None
            backup_id = session.backup_id
            starting = session.state is State.STARTING
        self._rest(None)
        if reason is EndReason.GONE:
            with self._lock:
                decision = session.end(EndReason.GONE)
                self._message = decision.message
                self._recovery = decision.backup_id
            return decision.message                                                    # A43: the marker stays
        slot0 = None
        if not starting:
            try:
                slot0 = self._writer.session_read()
            except MemoryFault:
                slot0 = None
        with self._lock:
            if starting:
                session.end(reason)
                return None
            if slot0 is None:
                session.end(EndReason.GONE)
                self._recovery = backup_id
                self._message = f"slot 0 could not be checked; restore {backup_id} if it still holds the lab layout"
                return self._message
            ours = _digest(slot0) in self._written
            decision = session.end(reason, session.last_written if ours else slot0)
            restore = decision.restore
            if restore is None and ours and session.backup is not None and slot0 != session.backup:
                restore = session.backup   # slot 0 holds an earlier record of ours, the last equals the backup
        if restore is None:
            self._backups.close_session()
            with self._lock:
                self._message = (f"lab session ended; nothing restored: slot 0 holds another project; "
                                 f"session backup {backup_id} kept") if not ours else None
            return self._message
        try:
            self._writer.session_write(restore)
            back = self._writer.session_read()
        except MemoryFault:
            back = None
        with self._lock:
            if back == restore:
                self._message = RESTORED_MESSAGE                                       # A42, d64
            else:
                self._recovery = backup_id
                self._message = f"slot 0 could not be restored; restore {backup_id}"
        if back == restore:
            self._backups.close_session()
        return self._message

    def _quiet_end(self, decision: Ended) -> None:
        """A Project-view report or a foreign slot 0: nothing written, the backup kept and listed (§2.7)."""
        self.slot0.cancel()
        self._backups.close_session()
        why = decision.reason
        with self._lock:
            self._message = (f"lab session ended quietly ({why}); nothing restored; "
                             f"session backup {decision.backup_id} kept")
        self._rest(None)

    def _full_backup(self) -> Iterator:
        """Slots 1–24 after the session's first write (§2.7 a5/q9), one slot per step, stepping aside for writes."""
        taken = self._wall()
        members, missing = [], []
        for n in range(1, 25):
            while True:
                try:
                    record = self._writer.read_project(Slot(n), self.slot0.interrupt)
                    break
                except Interrupted:
                    yield
                except (NotHeld, Gone):
                    return
                except (NoReply, MalformedReply):
                    record = None
                    break
            if record is None:
                missing.append(n)
            else:
                try:
                    members.append(self._writer.save_backup(Slot(n), record.raw))
                except StorageError:
                    missing.append(n)
            yield
        set_id = self._backups.save_set(members, SET_SESSION, taken, complete=not missing)
        with self._lock:
            self._last_full = {"set": str(set_id), "missing": missing}
        if missing:
            self._link.warn(f"full backup {set_id} is missing slots {', '.join(map(str, missing))}")
        self.publish()

    # --- tests ------------------------------------------------------------------------------------------
    def drain(self) -> None:
        self.slot0.drain()

    def close(self) -> None:
        self.slot0.close()


def _pads(record: ProjectRecord):
    from _apc64_host.domain.controls import PadPos
    return [(PadPos.from_index(i), pad) for i, pad in enumerate(record.pads)]
