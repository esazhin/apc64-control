"""Deterministic JSON shaping of every view and stream message (contract s13, s14; docs/api.md).

Pure functions from application views to JSON-safe dicts and lists. The page, the CLI and agents all read
these shapes, so their field names are the API (inv22). Control ids are their names ('pad r1c1', 'track 1',
'strip 3', 'play'); colours carry the palette index and an approximate RGB that is always marked as such
(the APC64's exact colours are not known). Times (`at`) are seconds since the epoch.
"""
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime
from enum import Enum

from ..domain.controls import ControlId
from ..domain.effects import ActivityEntry, ActivityResult, PlayEvent
from ..domain.issues import LayoutIssue
from ..domain.leds import LedBehaviour, LedState, StripBarState
from ..domain.palette import APPROXIMATION_NOTE, Colour

# How bright each LED behaviour is drawn in the replica (PROTOCOL-SPEC §6 LedBehavior); pulses and blinks
# are drawn full and animated.
_BRIGHTNESS = {0: 0.10, 1: 0.25, 2: 0.50, 3: 0.60, 4: 0.75, 5: 0.90, 6: 1.0}


# --- small values -------------------------------------------------------------------------------------
def control_name(control: ControlId | None) -> str | None:
    return None if control is None else str(control)


def rgb_hex(colour: Colour) -> str:
    r, g, b = colour.rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def colour_json(colour: Colour | None) -> dict | None:
    if colour is None:
        return None
    return {"index": colour.index, "name": str(colour) if not str(colour).isdigit() else None, "rgb": rgb_hex(colour)}


def led_json(led: LedState | None) -> dict | None:
    """{colour, behaviour, rgb, brightness, animation, off}: colour is the palette index, rgb approximate."""
    if led is None:
        return None
    behaviour = int(led.behaviour)
    animation = None if behaviour <= LedBehaviour.FULL else (
        "pulse" if behaviour <= LedBehaviour.PULSE_1_2 else "blink")
    return {"colour": led.colour.index, "behaviour": behaviour, "rgb": rgb_hex(led.colour),
            "brightness": 0.0 if led.is_off else _BRIGHTNESS.get(behaviour, 1.0), "animation": animation,
            "off": led.is_off}


def bar_json(bar: StripBarState | None) -> dict | None:
    if bar is None:
        return None
    return {"value": int(bar.value), "colour": bar.colour.index, "rgb": rgb_hex(bar.colour), "style": str(bar.style),
            "lit": bool(bar.lit)}


def issue_json(issue: LayoutIssue) -> dict:
    """{file, line, control, problem, fix, severity, text}; text is the one rendering everywhere (d115, A57)."""
    return {"file": issue.source.file, "line": issue.source.line, "control": issue.control, "problem": issue.problem,
            "fix": issue.fix, "severity": str(issue.severity), "text": issue.message()}


def _plain(value):
    """Enums, value objects and dataclasses → JSON-safe values (used for the small leftovers)."""
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, bool):
        return value
    for base in (int, float, str):     # value objects such as LayoutId(str) or PageNo(int) → the plain value
        if isinstance(value, base):
            return base(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(v) for v in value]
    return str(value)


# --- the state (s13, s14) -----------------------------------------------------------------------------
def unit_json(unit) -> dict:
    return {"status": unit.status, "text": unit.text, "held": unit.held, "holder": unit.holder,
            "taken_by": unit.taken_by, "firmware": unit.firmware, "warnings": list(unit.warnings),
            "notices": list(unit.notices), "view": str(unit.view)}


def slot_json(slot) -> dict | None:
    if slot is None:
        return None
    return {"n": slot.number, "name": slot.name, "display": slot.display, "defined": slot.defined,
            "current": slot.current}


def control_state_json(state) -> dict:
    out = {"label_base": state.label_base, "label_shift": state.label_shift, "empty": state.empty,
           "missing": list(state.missing), "toggle": state.toggle, "led": led_json(state.led),
           "bar": bar_json(state.bar), "role": str(state.role), "selected": state.selected}
    if getattr(state, "module_action", None):   # contract 2 only: a module action binds the control now
        out["module_action"] = state.module_action
    return out


def controls_json(controls: dict) -> dict:
    return {str(c): control_state_json(s) for c, s in controls.items()}


def routing_json(routing) -> dict:
    return {"notes": routing.notes, "custom": routing.custom, "status": routing.text}


def calibration_json(calibration) -> dict | None:
    if calibration is None:
        return None
    return {"at": calibration.at.isoformat(timespec="seconds"), "label": calibration.label,
            "bottom_left": int(calibration.bottom_left), "top_right": int(calibration.top_right)}


def learn_json(learn) -> dict:
    return {"mode": str(learn.mode), "selected": control_name(learn.selected), "port": learn.port,
            "device": learn.device, "last": learn.last}


def played_json(note) -> dict:
    text = f"{note.label} vel {note.velocity}"
    if note.aftertouch:
        text += f" at {note.aftertouch}"
    text += f" · {note.position}"
    return {"role": note.role, "note": note.note, "label": note.label, "velocity": note.velocity,
            "aftertouch": note.aftertouch, "routed": note.routed, "pad": control_name(note.pad),
            "position": note.position, "text": text}


def layout_summary_json(summary) -> dict:
    return {"id": str(summary.id), "name": summary.name, "file": summary.file, "valid": summary.valid,
            "pages": summary.pages, "banks": summary.banks, "errors": summary.errors, "warnings": summary.warnings,
            "deleted": summary.deleted}


# snapshot field → (JSON key, shaping); the order is the order of the JSON object
_STATE_FIELDS = {
    "unit": ("unit", unit_json),
    "layout": ("layout", lambda v: None if v is None else str(v)),
    "layout_name": ("layout_name", lambda v: v),
    "file_deleted": ("file_deleted", bool),
    "page": ("page", slot_json),
    "bank": ("bank", slot_json),
    "shift": ("shift", bool),
    "pages": ("pages", lambda v: [slot_json(s) for s in v]),
    "banks": ("banks", lambda v: [slot_json(s) for s in v]),
    "controls": ("controls", controls_json),
    "oled": ("oled", lambda v: list(v)),
    "errors": ("errors", lambda v: [issue_json(i) for i in v]),
    "warnings": ("warnings", lambda v: list(v)),
    "routing": ("routing", routing_json),
    "calibration": ("calibration", calibration_json),
    "calibration_label": ("calibration_label", lambda v: v),
    "calibration_step": ("calibration_step", lambda v: str(v)),
    "learn": ("learn", learn_json),
    "played": ("played", lambda v: [played_json(n) for n in v]),
    "layouts": ("layouts", lambda v: [layout_summary_json(s) for s in v]),
}


def state_json(snapshot) -> dict:
    """GET /api/state: the whole state (contract §3.5)."""
    out = {key: shape(getattr(snapshot, name)) for name, (key, shape) in _STATE_FIELDS.items()}
    out["palette_note"] = APPROXIMATION_NOTE
    modules = getattr(snapshot, "modules", ())
    if modules:   # contract 2: only when a module registers a panel, so contract 1's state is unchanged
        out["modules"] = [{"name": m.name, "title": m.title, "entry": m.entry} for m in modules]
    return out


def diff_json(diff) -> dict:
    """A StateDiff: only the top-level fields that changed, and only the controls whose state changed."""
    changed = {}
    for name, value in diff.changed.items():
        key, shape = _STATE_FIELDS.get(name, (name, _plain))
        changed[key] = shape(value)
    return {"changed": changed, "controls": controls_json(diff.controls)}


# --- card, overview, surface ---------------------------------------------------------------------------
def _assignment(binding) -> str | None:
    """The binding's messages in layout notation ('note 36 on mpc ch 10'), for the tweak form."""
    if binding is None:
        return None
    if getattr(binding, "module_action", None) is not None:   # contract 2: set by the module's layout section
        return None
    from ..notation.grammar import render_message
    from ..notation.splice import spec_of
    return " + ".join(render_message(m) for m in spec_of(binding).messages)


def _layer_form(binding) -> dict | None:
    if binding is None:
        return None
    colour = getattr(binding, "colour", None)
    return {"assignment": _assignment(binding), "label": binding.label,
            "colour": colour_json(colour), "mode": "toggle" if getattr(binding, "toggle", False) else "momentary"}


def elsewhere_json(item) -> dict:
    return {"page": item.page, "bank": item.bank, "layer": str(item.layer), "binding": item.text.split(": ", 1)[-1],
            "text": item.text}


def card_json(view, *, layout=None, page=None, bank=None, layer=None, base_hash=None) -> dict:
    """GET /api/controls/{id}: everything about one control (contract §3.5, A129)."""
    card = view.card
    mode = None
    current = card.shift_binding if str(layer) == "shift" else card.base_binding
    if current is not None:
        mode = "toggle" if getattr(current, "toggle", False) else (
            f"{current.style} bar" if hasattr(current, "style") else "momentary")
    return {"control": str(card.control), "display": card.display, "role": str(card.role),
            "base": card.base, "shift": card.shift, "mode": mode, "toggle": view.toggle,
            "feedback": card.feedback, "port_status": list(card.port_status),
            "elsewhere": [elsewhere_json(e) for e in card.elsewhere], "reachable": str(card.reachable),
            "lines": list(view.lines), "led": led_json(view.led), "selected": view.selected,
            "forms": {"base": _layer_form(card.base_binding), "shift": _layer_form(card.shift_binding)},
            "layout": None if layout is None else str(layout), "page": None if page is None else int(page),
            "bank": None if bank is None else int(bank), "layer": None if layer is None else str(layer),
            "base_hash": base_hash}


def _cells(cells: dict) -> dict:
    return {str(c): {"label": cell.label, "colour": cell.colour,
                     "rgb": rgb_hex(Colour(cell.colour)) if cell.colour is not None else None}
            for c, cell in cells.items()}


def overview_json(view) -> dict:
    """GET /api/overview: every page as a grid of labels and colours, every bank as a strip set, both layers."""
    o = view.overview
    return {"layout_name": o.layout_name, "page": view.page, "bank": view.bank,
            "pages": [{"n": p.number, "name": p.name, "defined": p.defined, "base": _cells(p.base),
                       "shift": _cells(p.shift)} for p in o.pages],
            "banks": [{"n": b.number, "name": b.name, "defined": b.defined, "base": _cells(b.base),
                       "shift": _cells(b.shift)} for b in o.banks],
            "palette_note": APPROXIMATION_NOTE}


def surface_json(view) -> dict:
    """GET /api/surface: every physical control (name, role, display, panel geometry, LED kind) and the palette."""
    return {"controls": [{"id": str(e.id), "name": e.name, "role": str(e.role), "display": e.display,
                          "geometry": {"x": e.geometry.x, "y": e.geometry.y, "w": e.geometry.w, "h": e.geometry.h},
                          "led": str(e.led), "shift_reach": str(e.shift_reach)} for e in view.controls],
            "palette": [{"index": p.index, "name": p.name, "rgb": "#%02x%02x%02x" % p.rgb} for p in view.palette],
            "palette_note": view.palette_note, "approximate": view.approximate}


# --- validation, layouts, ports, versions, device log ---------------------------------------------------
def validation_json(report) -> dict:
    """POST /api/validate: {valid, summary, errors, warnings, counts, ports_checked}."""
    counts = asdict(report.counts) if report.counts is not None and is_dataclass(report.counts) else report.counts
    return {"valid": report.valid, "summary": report.summary, "errors": [issue_json(i) for i in report.issues],
            "warnings": [issue_json(i) for i in report.warnings], "counts": counts,
            "ports_checked": report.ports_checked}


def ports_json(ports, declared_missing=()) -> list:
    """GET /api/ports: present ports, then the live layout's declared devices whose port is missing."""
    out = [{"name": p.name, "direction": str(p.direction), "present": bool(p.present), "device": None}
           for p in ports]
    for item in declared_missing:          # (device, port pattern) pairs, or bare names
        device, pattern = item if isinstance(item, tuple) else (None, item)
        out.append({"name": str(pattern), "direction": "declared", "present": False,
                    "device": None if device is None else str(device)})
    return out


def stamp_iso(timestamp: str) -> str:
    """'20261023T104200.123Z' → '2026-10-23T10:42:00.123Z' (the version store's sortable UTC stamp)."""
    try:
        moment = datetime.strptime(timestamp, "%Y%m%dT%H%M%S.%fZ")
    except ValueError:
        return timestamp
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def versions_json(versions) -> list:
    """GET /api/layouts/{id}/versions: [{id, at, hash}] newest first."""
    return [{"id": str(v), "at": stamp_iso(v.timestamp), "hash": str(v.hash)} for v in versions]


def device_log_json(entries) -> list:
    """GET /api/device-log: frames offered to the APC64 in send order; refused ones are hazards."""
    return [{"at": round(e.at, 3), "hex": e.frame.hex(" ").upper(), "command": str(e.command),
             "outcome": str(e.outcome), "hazard": e.hazard,
             "text": e.refusal_text() if e.hazard else str(e.command)} for e in entries]


# --- activity and play (s14) -----------------------------------------------------------------------------
def activity_text(entry: ActivityEntry) -> str:
    """The list line: 'pad r1c1 → note 36 ch 10 → mpc: sent'; a refused frame reads 'refused: project write (0x14)'."""
    if entry.result is ActivityResult.REFUSED:
        return f"refused: {entry.message}" if entry.message else "refused"
    text = entry.text()
    if entry.aftertouch is not None:
        text += f" (aftertouch {entry.aftertouch})"
    return text


def activity_json(item) -> dict:
    """An ActivityRecord (with its id, for in-place updates of a folded note) or a bare ActivityEntry."""
    record_id, folded = getattr(item, "id", None), getattr(item, "folded", False)
    entry = getattr(item, "entry", item)
    return {"id": record_id, "folded": folded, "at": None if entry.at is None else round(entry.at, 3),
            "control": entry.subject, "message": entry.message, "port": entry.port, "result": str(entry.result),
            "reason": entry.reason, "note": entry.note, "aftertouch": entry.aftertouch, "text": activity_text(entry)}


def play_json(event: PlayEvent) -> dict:
    """One play-stream event {at, kind, source, view, control, note, value, velocity, aftertouch, sent, reason}."""
    return {"at": None if event.at is None else round(event.at, 3), "kind": event.kind, "source": str(event.source),
            "view": None if event.view is None else str(event.view), "control": control_name(event.control),
            "note": event.note, "value": event.value, "velocity": event.velocity, "aftertouch": event.aftertouch,
            "sent": list(event.sent), "reason": event.reason}


# --- WebSocket messages {type, data} (s14.c2) ------------------------------------------------------------
def snapshot_message(snapshot) -> dict:
    return {"type": "snapshot", "data": state_json(snapshot)}


def diff_message(diff) -> dict:
    return {"type": "diff", "data": diff_json(diff)}


def activity_message(record) -> dict:
    return {"type": "activity", "data": activity_json(record)}


def activity_list_message(records) -> dict:
    return {"type": "activity_list", "data": [activity_json(r) for r in records]}


def play_message(event: PlayEvent) -> dict:
    return {"type": "event", "data": play_json(event)}


def topic_message(topic: str, payload) -> dict:
    """A module's topic message on /ws (contract 2 s25): {type: 'topic', topic, data}."""
    return {"type": "topic", "topic": topic, "data": _plain(payload)}


def closed_message(reason: str) -> dict:
    """The play stream's last message before the socket closes (s31.c2)."""
    return {"type": "closed", "reason": reason, "data": {"reason": reason, "text": f"stream closed: {reason}"}}


def state_message(item) -> dict:
    """A StateView subscription item: the snapshot first, then diffs."""
    return snapshot_message(item) if hasattr(item, "unit") else diff_message(item)


# --- answers ------------------------------------------------------------------------------------------
def take_json(answer, status) -> dict:
    return {"result": str(answer.result), "text": answer.text, "status": status.status, "status_text": status.text,
            "by": None if answer.by is None else str(answer.by)}


def problem(message: str, /, **extra) -> dict:
    return {"problem": message, **{k: _plain(v) for k, v in extra.items() if k != "problem"}}
