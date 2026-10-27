"""StateView: what the page, the CLI and the API read (contract §3.5 /api/state, s22, s26, s68–s72, s90).

Everything is derived from the one read model (domain/resolver.py) applied to the engine's live layout and
nav, plus the session's unit status, the library's issues, learn and calibration (inv1). snapshot() gives
the whole state; card(), overview() and surface() the per-control card, the overview of every page and
bank, and the catalog of physical controls. subscribe() hands a subscriber the snapshot at once and then a
StateDiff after every change (only what changed: top-level fields and the controls whose look or meaning
changed). Shaping into JSON is the presentation layer's job (view_model.py).
"""
from dataclasses import dataclass, field, fields
from typing import Any, Callable

from ..domain.calibration import UNKNOWN_POSITION, Calibration
from ..domain.controls import SURFACE, ControlId, ControlRole, Geometry, LedKind, Reachability, Strip, parse_control
from ..domain.effects import UnitView
from ..domain.issues import DomainInvariantError, LayoutIssue
from ..domain.layout import LayoutId
from ..domain.leds import LedState, StripBarState
from ..domain.midi import note_label
from ..domain.palette import APPROXIMATION_NOTE, PaletteEntry, palette
from ..domain.resolver import ControlCard, NavSlot, Overview, card as resolve_card, overview as resolve_overview, resolve
from ..domain.unit_status import Busy, Held
from .engine import RoutingStatus
from .library import LayoutSummary


# --- values ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class UnitInfo:
    status: str
    text: str
    held: bool
    holder: str | None
    taken_by: str | None
    firmware: str | None
    warnings: tuple[str, ...]
    notices: tuple[str, ...]
    view: UnitView


@dataclass(frozen=True)
class ControlState:
    label_base: str
    label_shift: str
    empty: bool                      # nothing bound in the current layer (inv2)
    missing: tuple[str, ...]         # devices of the current binding whose port is absent
    toggle: bool | None              # latch state of a toggle binding, None for momentary or unbound
    led: LedState | None
    bar: StripBarState | None
    role: ControlRole
    selected: bool = False           # learn's selection
    module_action: str | None = None   # contract 2: 'lab.window_shift' when a module action binds it now


@dataclass(frozen=True)
class PlayedNoteView:
    role: str
    note: int
    label: str                       # 'F2 (53)'
    velocity: int
    aftertouch: int
    routed: bool
    pad: Any | None                  # PadPos from the calibration, else None
    position: str                    # 'calibrated 14:02 (assumed)' or 'pad position unknown' (inv9)


@dataclass(frozen=True)
class ModulePanel:
    """A registered module's page panel (contract 2, a13): the page loads `entry` into a side panel `title`."""
    name: str
    title: str
    entry: str

    @classmethod
    def of(cls, name: str) -> "ModulePanel":
        return cls(name, name.replace("-", " ").replace("_", " ").title(), f"/modules/{name}/{name}.js")


@dataclass(frozen=True)
class StateSnapshot:
    unit: UnitInfo
    layout: LayoutId | None
    layout_name: str | None
    file_deleted: bool
    page: NavSlot | None
    bank: NavSlot | None
    shift: bool
    pages: tuple[NavSlot, ...]
    banks: tuple[NavSlot, ...]
    controls: dict[ControlId, ControlState]
    oled: tuple[str, str]
    errors: tuple[LayoutIssue, ...]
    warnings: tuple[str, ...]
    routing: RoutingStatus
    calibration: Calibration | None
    calibration_label: str
    calibration_step: str
    learn: Any
    played: tuple[PlayedNoteView, ...]
    layouts: tuple[LayoutSummary, ...]
    modules: tuple[ModulePanel, ...] = ()     # contract 2: registered module panels (none in contract 1)


@dataclass(frozen=True)
class StateDiff:
    changed: dict[str, Any] = field(default_factory=dict)            # top-level fields that changed
    controls: dict[ControlId, ControlState] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.changed or self.controls)


@dataclass(frozen=True)
class CardView:
    card: ControlCard
    toggle: bool | None
    led: LedState | None
    selected: bool
    lines: tuple[str, ...]


@dataclass(frozen=True)
class UnknownControl:
    name: str
    problem: str


@dataclass(frozen=True)
class OverviewView:
    overview: Overview
    page: int | None
    bank: int | None


@dataclass(frozen=True)
class SurfaceEntryView:
    id: ControlId
    name: str
    role: ControlRole
    display: str
    geometry: Geometry
    led: LedKind
    shift_reach: Reachability


@dataclass(frozen=True)
class SurfaceCatalogView:
    controls: tuple[SurfaceEntryView, ...]
    palette: tuple[PaletteEntry, ...]
    palette_note: str = APPROXIMATION_NOTE
    approximate: bool = True


class StateView:
    def __init__(self, *, engine, session, library, calibration, learn, panels=()):
        self._engine, self._session, self._library = engine, session, library
        self._panels = tuple(ModulePanel.of(name) for name, _ in panels)
        self._calibration, self._learn = calibration, learn
        self._subscribers: dict[int, Callable[[StateSnapshot | StateDiff], None]] = {}
        self._next_token = 1
        self._last: StateSnapshot | None = None
        engine.subscribe(self._changed)
        session.subscribe(lambda status: self._changed())
        library.subscribe(self._changed)
        calibration.subscribe(lambda status: self._changed())
        learn.subscribe(lambda status: self._changed())

    # --- reads (s22) ----------------------------------------------------------------------------------
    def snapshot(self) -> StateSnapshot:
        engine = self._engine.snapshot()
        layout, nav = engine.layout, engine.nav
        meaning = resolve(layout, nav, engine.missing)
        learn = self._learn.status()
        controls = {}
        for control, item in meaning.controls.items():
            current = item.current
            toggle = engine.toggles.get(control) if item.toggle else None
            module_action = getattr(current.binding, "module_action", None)
            controls[control] = ControlState(
                item.base.label, item.shift.label, item.empty, current.missing, toggle,
                engine.frame.leds.get(control), engine.frame.bars.get(control) if isinstance(control, Strip) else None,
                item.role, learn.selected == control, None if module_action is None else str(module_action))
        status = self._session.status()
        page = next((s for s in meaning.pages if s.current), None)
        bank = next((s for s in meaning.banks if s.current), None)
        calibration = self._calibration.current()
        warnings = tuple(w.message() for w in self._library.warnings(layout.id)) if layout else ()
        if isinstance(status, Held) and status.firmware_warning:
            warnings = (status.firmware_warning,) + warnings
        warnings += tuple(getattr(engine, "warnings", ()))     # module warnings (contract 2 ModuleDisplay)
        return StateSnapshot(
            unit=UnitInfo(status.status, status.text, status.held,
                          status.holder.name if isinstance(status, Busy) and status.holder else None,
                          str(status.by) if isinstance(status, Held) else None, self._session.firmware,
                          (status.firmware_warning,) if isinstance(status, Held) and status.firmware_warning else (),
                          status.notices, engine.view),
            layout=layout.id if layout else None, layout_name=meaning.layout_name,
            file_deleted=bool(layout and self._library.deleted(layout.id)),
            page=page, bank=bank, shift=nav.shift, pages=meaning.pages, banks=meaning.banks,
            controls=controls, oled=engine.oled.rows, errors=tuple(self._library.all_issues()),
            warnings=warnings, routing=engine.routing, calibration=calibration,
            calibration_label=self._calibration.label(), calibration_step=str(self._calibration.status().step),
            learn=learn, played=tuple(self._played(engine.played)),
            layouts=tuple(self._library.summaries()), modules=self._panels)

    def _played(self, played):
        for note in played:
            position = self._calibration.position_of(note.note)
            yield PlayedNoteView(str(note.role), note.note, note_label(note.note), note.velocity, note.aftertouch,
                                 note.routed, position.pad if position else None,
                                 self._calibration.label() if position else UNKNOWN_POSITION)

    def card(self, control) -> CardView | UnknownControl:
        if not isinstance(control, (str,)):
            control_id = control
        else:
            try:
                control_id = parse_control(control)
            except DomainInvariantError as error:
                return UnknownControl(control, f"{error.problem}; {error.fix}")
        engine = self._engine.snapshot()
        layout, nav = engine.layout, engine.nav
        try:
            found = resolve_card(layout, nav, control_id, engine.missing)
        except KeyError:
            return UnknownControl(str(control), f"no such control: {control}")
        toggle = None
        page = layout.page(nav.page) if layout else None
        binding = page.binding(nav.layer, control_id) if page and not isinstance(control_id, Strip) else None
        if binding is not None and binding.toggle:
            toggle = engine.toggles.get(control_id, False)
        lines = list(found.lines())
        if toggle is not None:
            lines.insert(2, f"toggle {'on' if toggle else 'off'}")
        if found.reachable is not Reachability.VERIFIED and found.role is ControlRole.BINDABLE:
            lines.append(f"Shift layer: {found.reachable}")
        return CardView(found, toggle, engine.frame.leds.get(control_id),
                        self._learn.status().selected == control_id, tuple(lines))

    def overview(self) -> OverviewView:
        engine = self._engine.snapshot()
        return OverviewView(resolve_overview(engine.layout), engine.nav.page if engine.layout else None,
                            engine.nav.bank if engine.layout else None)

    def surface(self) -> SurfaceCatalogView:
        return SurfaceCatalogView(
            tuple(SurfaceEntryView(e.id, e.name, e.role, e.display, e.geometry, e.led, e.shift_reach)
                  for e in SURFACE),
            palette())

    # --- subscriptions (s26) --------------------------------------------------------------------------
    def subscribe(self, callback: Callable[[StateSnapshot | StateDiff], None]) -> int:
        """The snapshot now, then a diff after every change."""
        token, self._next_token = self._next_token, self._next_token + 1
        self._subscribers[token] = callback
        snapshot = self.snapshot()
        if self._last is None:
            self._last = snapshot
        callback(snapshot)
        return token

    def unsubscribe(self, token: int) -> None:
        self._subscribers.pop(token, None)

    def _changed(self, *_) -> None:
        if not self._subscribers:
            self._last = None
            return
        snapshot = self.snapshot()
        diff = diff_states(self._last, snapshot) if self._last is not None else None
        self._last = snapshot
        if diff is not None and not diff:
            return
        for callback in list(self._subscribers.values()):
            callback(diff if diff is not None else snapshot)


def diff_states(before: StateSnapshot, after: StateSnapshot) -> StateDiff:
    changed = {f.name: getattr(after, f.name) for f in fields(StateSnapshot)
               if f.name != "controls" and getattr(before, f.name) != getattr(after, f.name)}
    controls = {c: s for c, s in after.controls.items() if before.controls.get(c) != s}
    return StateDiff(changed, controls)
