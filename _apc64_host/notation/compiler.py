"""Syntax tree (+ an optional snapshot of port names) → Layout, or every issue in line order with its fix.

Range forms expand in reading order; a single-control entry overrides the range covering it on the same
page and layer (d73), while two ranges or two singles on one control are refused naming both lines (d74).
Devices are declared once; a binding names one with 'on <device>', or uses the 'device:' default, or the
only declared device. Channels default to the device's 'ch', then 1. Note names use C3 = 60.

Port checks run only with a port list: a device matching two ports is an error (A84), one matching none
is a warning (the layout loads with '(missing)' labels, d58). Without one the result says 'ports not checked'.

Module-owned sections (contract 2, s4): a registered SectionCompiler gets its top-level section (e.g. 'lab:')
with line positions and the layout's explicit base-layer bindings. Its issues join the layout's, its value is
kept in Layout.sections, and the base-layer bindings it implies join every page (page 1 is made when the
layout has none). Without a registered compiler the key is unknown, exactly as before.
"""
import re
from dataclasses import dataclass, field
from pathlib import PurePath

from ..domain.controls import ControlId, Encoder, PadPos, Strip, format_controls, parse_controls
from ..domain.issues import DomainInvariantError, LayoutIssue, Severity, SourceRef, in_line_order
from ..domain.layout import (
    Action, AftertouchPolicy, Bank, Binding, BindingMode, DeviceDecl, DeviceName, EncoderValue, ExistingBinding,
    FeedbackRule, Fixed, Layer, Layout, LayoutId, MessageKind, Page, PressVelocity, RoutingRule, SectionEntry,
    SectionList, SectionMap, SectionScalar, StripBinding, StripPosition, ToggleState, ToggleValues, UnitPortRole,
    check_page_binding, BankNo, PageNo,
)
from ..domain.leds import StripBarStyle
from ..domain.midi import Channel, parse_note
from ..domain.oled import name_warning
from ..domain.palette import WHITE, parse_colour
from .grammar import (
    BANK_KEY, BINDING_KEYS, DEVICE_KEYS, PAGE_KEY, ROUTING_KEYS, TOP_KEYS, BindingSpec, MessageSpec,
    PhraseError, RoutingSpec, normalise_key, parse_options, parse_phrase, parse_routing,
)
from .parser import Entry, MapNode, Node, Parsed, Scalar, SeqNode, parse

PORTS_NOT_CHECKED = "ports not checked"


@dataclass(frozen=True)
class Counts:
    pages: int = 0
    banks: int = 0
    pads: int = 0
    buttons: int = 0
    strips: int = 0
    encoders: int = 0
    routes: int = 0

    def text(self) -> str:
        def n(count, word):
            return f"{count} {word}{'' if count == 1 else 's'}"
        bound = [n(c, w) for c, w in ((self.pads, "pad"), (self.buttons, "button"), (self.strips, "strip"),
                                      (self.encoders, "encoder")) if c]
        parts = [n(self.pages, "page"), n(self.banks, "bank")] + bound
        return ", ".join(parts) + (" bound" if bound else "")


@dataclass(frozen=True)
class EntrySource:
    line: int
    column: int
    key: str
    controls: tuple[ControlId, ...]
    is_range: bool
    end_line: int


@dataclass(frozen=True)
class BlockSource:
    """Where one page/bank layer is written: its key line, its entries and where it ends."""
    scope: str            # 'page' or 'bank'
    number: int
    layer: Layer
    line: int
    column: int
    entry_column: int | None
    end_line: int
    flow: bool
    entries: tuple[EntrySource, ...]


@dataclass(frozen=True)
class SourceMap:
    winners: dict = field(default_factory=dict)       # (scope, n, layer, control) → EntrySource that binds it
    singles: dict = field(default_factory=dict)       # (scope, n, layer, control) → single-control EntrySource
    from_ranges: dict = field(default_factory=dict)   # (scope, n, layer, control) → what the range alone binds
    blocks: dict = field(default_factory=dict)        # (scope, n, layer) → BlockSource


@dataclass(frozen=True)
class CompileResult:
    file: str
    layout: Layout | None
    issues: tuple[LayoutIssue, ...]
    warnings: tuple[LayoutIssue, ...] = ()
    counts: Counts | None = None
    ports_checked: bool = False
    sources: SourceMap | None = None

    @property
    def valid(self) -> bool:
        return not self.issues and self.layout is not None

    def summary(self) -> str:
        """'valid: 1 page, 1 bank, 16 pads, 8 strips bound' (A34), or the error count."""
        checked = "" if self.ports_checked else f" ({PORTS_NOT_CHECKED})"
        if self.valid:
            return f"valid: {self.counts.text()}{checked}"
        return f"invalid: {len(self.issues)} error{'' if len(self.issues) == 1 else 's'}"


def layout_id_of(file: str) -> str:
    return PurePath(file).stem


def compile_text(text: str, file: str, ports=None, sections=None) -> CompileResult:
    """Compile layout text named `file` (its stem is the LayoutId). `ports`: current port names, or None.
    `sections`: {top-level key: SectionCompiler} registered by modules, or None (contract 1: none)."""
    parsed = parse(text, PurePath(file).name)
    return _Compiler(parsed, ports, sections).run()


class _Compiler:
    def __init__(self, parsed: Parsed, ports, sections=None):
        self.parsed = parsed
        self.section_compilers = dict(sections or {})
        self.file = parsed.file
        self.ports = list(ports) if ports is not None else None
        self.issues: list[LayoutIssue] = list(parsed.issues)
        self.warnings: list[LayoutIssue] = []
        self.devices: dict[DeviceName, DeviceDecl] = {}
        self.refused: set[str] = set()     # devices whose declaration failed: already reported once
        self.default_device: DeviceName | None = None
        self.sources = SourceMap()
        self.lines = parsed.text.splitlines()

    # --- issue helpers --------------------------------------------------------------------------------
    def error(self, line: int, control, problem: str, fix: str | None, joiner: str = "; "):
        self.issues.append(LayoutIssue(Severity.ERROR, SourceRef(self.file, line), control, problem, fix, joiner))

    def warn(self, line: int, control, problem: str, fix: str | None = None):
        self.warnings.append(LayoutIssue(Severity.WARNING, SourceRef(self.file, line), control, problem, fix))

    def invariant(self, line: int, control, error: DomainInvariantError):
        self.error(line, control, error.problem, error.fix, error.joiner)

    # --- the document ---------------------------------------------------------------------------------
    def run(self) -> CompileResult:
        root = self.parsed.root
        stem = layout_id_of(self.file)
        try:
            layout_id = LayoutId(stem)
        except DomainInvariantError as error:
            self.invariant(1, None, error)
            layout_id = LayoutId("layout")
        if root is None:
            return self._result(None)
        if not isinstance(root, MapNode):
            self.error(root.line, None, "a layout is a mapping of keys", "start with 'name:', 'devices:' and 'pages:'")
            return self._result(None)
        for entry in root.entries:
            key = normalise_key(entry.key)
            if key not in TOP_KEYS and key not in self.section_compilers:
                self._unknown_top_key(entry)
        name = self._name(root.get("name"), "layout")
        self._devices(root.get("devices"))
        self._default_device(root.get("device"))
        pages = self._numbered(root.get("pages"), "page")
        banks = self._numbered(root.get("banks"), "bank")
        routing = self._routing(root.get("routing"))
        module_sections = self._module_sections(root, pages, routing)
        if self.issues:
            return self._result(None)
        try:
            layout = Layout(layout_id, name, self.devices, pages, banks, routing, module_sections)
        except DomainInvariantError as error:
            self.invariant(1, None, error)
            return self._result(None)
        return self._result(layout)

    # --- module-owned sections (contract 2) ------------------------------------------------------------
    def _module_sections(self, root: MapNode, pages: dict, routing: dict | None = None) -> dict:
        values = {}
        for name, compiler in self.section_compilers.items():
            entry = root.get(name)
            if entry is None:
                continue
            existing = self._existing(pages)
            result = compiler.compile(SectionEntry(name, entry.line, _section_node(entry.value)), self.file, existing)
            self.issues += [issue for issue in result.issues if issue.is_error]
            self.warnings += [issue for issue in result.issues if not issue.is_error] + list(result.warnings)
            values[name] = result.value
            failed = any(issue.is_error for issue in result.issues)
            if result.bindings and not failed:
                self._join(name, result.bindings, pages, existing)
            if not failed and routing is not None:
                self._default_routing(result, routing)
        return values

    def _default_routing(self, result, routing: dict):
        """A section's implied routing (contract 2, §2.7 q2): only for a port the layout does not route itself,
        with the devices it names declared unless the layout declares that name itself."""
        for role, rule in dict(getattr(result, "routing", None) or {}).items():
            if role in routing:
                continue
            routing[role] = rule
            decl = dict(getattr(result, "devices", None) or {}).get(rule.device)
            if rule.device not in self.devices and decl is not None:
                self.devices[DeviceName(rule.device)] = decl

    def _existing(self, pages: dict) -> dict:
        """Explicit base-layer bindings by control, with the page and line that bind them (s4.c1)."""
        existing: dict = {}
        for number, page in sorted(pages.items()):
            for control, binding in page.layers[Layer.BASE].items():
                source = self.sources.winners.get(("page", number, Layer.BASE, control))
                existing.setdefault(control, []).append(
                    ExistingBinding(PageNo(number), source.line if source else 1, binding))
        return {control: tuple(found) for control, found in existing.items()}

    def _join(self, name: str, bindings: dict, pages: dict, existing: dict):
        """Implied base-layer bindings join every page; an explicit binding of the same control is refused."""
        clashes = [(control, found) for control in bindings for found in existing.get(control, ())]
        for control, found in clashes:
            self.error(found.line, str(control), f"{control} is also bound by the '{name}:' section",
                       f"remove this binding or the '{name}:' section")
        if clashes:
            return
        if not pages:
            pages[PageNo(1)] = Page(1)
        for number, page in list(pages.items()):
            base = dict(page.layers[Layer.BASE])
            base.update(bindings)
            try:
                pages[number] = Page(page.number, page.name, {Layer.BASE: base, Layer.SHIFT: page.layers[Layer.SHIFT]})
            except DomainInvariantError as error:
                self.invariant(1, f"page {number}", error)

    def _result(self, layout: Layout | None) -> CompileResult:
        counts = _count(layout) if layout else None
        return CompileResult(self.file, layout if not self.issues else None, tuple(in_line_order(self.issues)),
                             tuple(in_line_order(self.warnings)), counts, self.ports is not None, self.sources)

    def _unknown_top_key(self, entry: Entry):
        key = normalise_key(entry.key)
        hint = {"page": "pages", "bank": "banks", "device_list": "devices", "layout": "name"}.get(key)
        if CONTROL_LIKE.match(key):
            fix = "put control entries under a page, e.g. 'pages:' → '1 Main:' → '" + key + ": …'"
        else:
            fix = f"did you mean '{hint}:'? " if hint else ""
            fix += "the top-level keys are " + ", ".join(TOP_KEYS)
        self.error(entry.line, None, f"unknown key '{entry.key}'", fix)

    def _name(self, entry: Entry | None, what: str, number: int | None = None) -> str | None:
        if entry is None:
            return None
        if not isinstance(entry.value, Scalar) or entry.value.value is None:
            self.error(entry.line, None, f"the {what} name must be text", f"write e.g. 'name: Jam'")
            return None
        name = str(entry.value.value).strip()
        warning = name_warning(what, name)
        if warning:
            self.warn(entry.line, f"{what} {number}" if number else None, warning)
        return name

    # --- devices --------------------------------------------------------------------------------------
    def _devices(self, entry: Entry | None):
        if entry is None:
            return
        if not isinstance(entry.value, MapNode):
            self.error(entry.line, "devices", "devices is a list of name: port lines",
                       "write e.g. 'devices:' then '  mpc: MPC Live III MIDI 1'")
            return
        for item in entry.value.entries:
            control = f"device {item.key}"
            pattern, channel = self._device_value(item)
            if pattern is None:
                continue
            try:
                decl = DeviceDecl(str(item.key).lower(), pattern, channel)
            except DomainInvariantError as error:
                self.invariant(item.line, control, error)
                self.refused.add(str(item.key).lower())
                continue
            self.devices[decl.name] = decl
            self._check_port(decl, item.line)

    def _device_value(self, item: Entry):
        value = item.value
        control = f"device {item.key}"
        if isinstance(value, Scalar) and value.value is not None:
            return str(value.value), None
        if isinstance(value, MapNode):
            for sub in value.entries:
                if normalise_key(sub.key) not in DEVICE_KEYS:
                    self.error(sub.line, control, f"unknown device key '{sub.key}'",
                               "a device takes 'port:' and optionally 'ch:'")
            port = value.get("port")
            channel_entry = value.get("ch") or value.get("channel")
            if port is None or not isinstance(port.value, Scalar):
                self.error(item.line, control, "the device has no port", "write 'port: <ALSA port name>'")
                return None, None
            channel = None
            if channel_entry is not None:
                try:
                    channel = Channel(_as_int(channel_entry.value))
                except DomainInvariantError as error:
                    self.invariant(channel_entry.line, control, error)
            return str(port.value.value), channel
        self.error(item.line, control, "the device has no port", "write 'mpc: MPC Live III MIDI 1'")
        return None, None

    def _check_port(self, decl: DeviceDecl, line: int):
        if self.ports is None:
            return
        exact = [p for p in self.ports if p.casefold() == decl.pattern.casefold()]
        matches = exact or [p for p in self.ports if decl.pattern.matches(p)]
        if len(matches) > 1:
            listed = ", ".join(matches[:-1]) + " and " + matches[-1]
            self.error(line, f"device {decl.name}", f'"{decl.pattern}" matches {listed}', "write the full name")
        elif not matches:
            self.warn(line, f"device {decl.name}", f'no port matches "{decl.pattern}" now',
                      "its bindings show (missing) until the port appears")

    def _default_device(self, entry: Entry | None):
        if entry is None:
            if len(self.devices) + len(self.refused) == 1:
                self.default_device = next(iter(self.devices), None)
            return
        name = str(getattr(entry.value, "value", "")).lower()
        if name not in self.devices:
            self.error(entry.line, f"device {name}", f"unknown device {name}",
                       f"declared devices: {', '.join(self.devices) or 'none'}", ", ")
        else:
            self.default_device = DeviceName(name)

    def _device(self, written: str | None, line: int, control: str | None = None) -> DeviceName | None:
        if written in self.refused or (written is None and self.default_device is None and len(self.refused) == 1
                                       and not self.devices):
            return None   # its declaration was refused and reported already
        if written is None:
            if self.default_device is None:
                self.error(line, control, "which device? no 'on <device>' and no default device",
                           f"add 'on <device>' (declared devices: {', '.join(self.devices) or 'none'}) "
                           "or a top-level 'device: <name>'")
                return None
            return self.default_device
        if written not in self.devices:
            self.error(line, f"device {written}", f"unknown device {written}",
                       f"declared devices: {', '.join(self.devices) or 'none'}", ", ")
            return None
        return DeviceName(written)

    def _channel(self, written: int | None, device: DeviceName, line: int, control: str) -> Channel | None:
        try:
            if written is not None:
                return Channel(written)
            default = self.devices[device].default_channel
            return default if default is not None else Channel(1)
        except DomainInvariantError as error:
            self.invariant(line, control, error)
            return None

    # --- pages and banks ------------------------------------------------------------------------------
    def _numbered(self, entry: Entry | None, scope: str) -> dict:
        if entry is None:
            return {}
        if not isinstance(entry.value, MapNode):
            self.error(entry.line, None, f"{scope}s is a list of numbered {scope}s",
                       f"write '{scope}s:' then '  1 Main:' with the entries under it")
            return {}
        built, first_line = {}, {}
        for item in entry.value.entries:
            number, name = self._numbered_key(item, scope)
            if number is None:
                continue
            if number in first_line:
                self.error(item.line, f"{scope} {number}",
                           f"lines {first_line[number]} and {item.line} are both {scope} {number}", "renumber one")
                continue
            first_line[number] = item.line
            result = self._page(item, number, name) if scope == "page" else self._bank(item, number, name)
            if result is not None:
                built[number] = result
        return built

    def _numbered_key(self, item: Entry, scope: str):
        key = str(item.key).strip()
        match = (PAGE_KEY if scope == "page" else BANK_KEY).match(key)
        if not match:
            self.error(item.line, None, f"{scope} '{key}' has no number",
                       f'write "1 {key}:" ({scope}s are numbered 1–{8 if scope == "page" else 6})')
            return None, None
        number = int(match["n"])
        try:
            number = PageNo(number) if scope == "page" else BankNo(number)
        except DomainInvariantError as error:
            self.invariant(item.line, f"{scope} {number}", error)
            return None, None
        return number, match["name"].strip() if match["name"] else None

    def _block_entries(self, item: Entry, scope: str, number: int):
        """(name, base entries, shift block entry) of a page or bank body."""
        body = item.value
        if isinstance(body, Scalar) and body.value is None:
            return None, [], None
        if not isinstance(body, MapNode):
            self.error(item.line, f"{scope} {number}", f"{scope} {number} holds no entries",
                       f"put '<control>: <binding>' lines under it, indented")
            return None, [], None
        name, entries, shift = None, [], None
        for sub in body.entries:
            key = normalise_key(sub.key)
            if key == "name":
                name = self._name(sub, scope, number)
            elif key == "shift":
                shift = sub
            else:
                entries.append(sub)
        return name, entries, shift

    def _page(self, item: Entry, number: PageNo, key_name: str | None) -> Page | None:
        name, entries, shift = self._block_entries(item, "page", number)
        name = key_name or name
        if key_name:
            warning = name_warning("page", key_name)
            if warning:
                self.warn(item.line, f"page {number}", warning)
        layers = {Layer.BASE: self._layer(entries, "page", number, Layer.BASE, item)}
        layers[Layer.SHIFT] = self._shift_layer(shift, "page", number, item)
        try:
            return Page(number, name, layers)
        except DomainInvariantError as error:
            self.invariant(item.line, f"page {number}", error)
            return None

    def _bank(self, item: Entry, number: BankNo, key_name: str | None) -> Bank | None:
        name, entries, shift = self._block_entries(item, "bank", number)
        name = key_name or name
        if key_name:
            warning = name_warning("bank", key_name)
            if warning:
                self.warn(item.line, f"bank {number}", warning)
        layers = {Layer.BASE: self._layer(entries, "bank", number, Layer.BASE, item)}
        layers[Layer.SHIFT] = self._shift_layer(shift, "bank", number, item)
        try:
            return Bank(number, name, layers)
        except DomainInvariantError as error:
            self.invariant(item.line, f"bank {number}", error)
            return None

    def _shift_layer(self, shift: Entry | None, scope: str, number: int, parent: Entry) -> dict:
        if shift is None:
            return {}
        if isinstance(shift.value, Scalar) and shift.value.value is None:   # an empty 'shift:' block
            return self._layer([], scope, number, Layer.SHIFT, shift)
        if not isinstance(shift.value, MapNode):
            self.error(shift.line, None, "shift holds the Shift layer's entries",
                       "put '<control>: <binding>' lines under 'shift:', indented")
            return {}
        return self._layer(list(shift.value.entries), scope, number, Layer.SHIFT, shift)

    def _layer(self, entries: list[Entry], scope: str, number: int, layer: Layer, parent: Entry) -> dict:
        """Compile one page/bank layer: expand every entry, then apply the precedence rule."""
        compiled = []   # (EntrySource, {control: binding})
        for entry in entries:
            key = normalise_key(entry.key)
            try:
                controls = parse_controls(key)
            except DomainInvariantError as error:
                self.invariant(entry.line, str(entry.key), error)
                continue
            is_range = len(controls) > 1 or bool(re.search(r"\d\s*-\s*[r\d]", key))
            source = EntrySource(entry.line, entry.column, str(entry.key), controls, is_range,
                                 self._end_line(entry.line, entry.column))
            bindings = (self._page_bindings(entry, controls, layer) if scope == "page"
                        else self._bank_bindings(entry, controls))
            if bindings is not None:
                compiled.append((source, bindings))
        flow = isinstance(parent.value, MapNode) and parent.value.flow
        column = min((s.column for s, _ in compiled), default=None)
        end = max([parent.line] + [s.end_line for s, _ in compiled])
        self.sources.blocks[(scope, number, layer)] = BlockSource(
            scope, number, layer, parent.line, parent.column, column, end, flow, tuple(s for s, _ in compiled))
        return self._precedence(compiled, scope, number, layer)

    def _precedence(self, compiled, scope: str, number: int, layer: Layer) -> dict:
        ranges = [(s, b) for s, b in compiled if s.is_range]
        singles = [(s, b) for s, b in compiled if not s.is_range]
        result: dict = {}
        for group in (ranges, singles):
            claimed: dict[ControlId, EntrySource] = {}
            clashes: dict[tuple, list] = {}
            for source, bindings in group:
                for control, binding in bindings.items():
                    if control in claimed:
                        clashes.setdefault((claimed[control], source), []).append(control)
                    else:
                        claimed[control] = source
                        result[control] = binding
                        key = (scope, number, layer, control)
                        self.sources.winners[key] = source
                        if group is ranges:
                            self.sources.from_ranges[key] = binding
                        else:
                            self.sources.singles[key] = source
            for (first, second), controls in clashes.items():
                both = format_controls(controls)
                self.error(second.line, both,
                           f"lines {first.line} and {second.line} both bind {both} on {scope} {number} {layer} layer",
                           "keep one")
        return {control: binding for control, binding in result.items() if binding is not None}   # 'none' unbinds

    def _end_line(self, line: int, column: int) -> int:
        """The last content line of an entry that starts at (line, column)."""
        end = line
        for number in range(line + 1, len(self.lines) + 1):
            text = self.lines[number - 1]
            stripped = text.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if len(text) - len(text.lstrip()) <= column:
                break
            end = number
        return end

    # --- bindings -------------------------------------------------------------------------------------
    def _spec(self, entry: Entry) -> BindingSpec | None:
        """The binding as written, from a phrase, a list of phrases or a mapping."""
        value, control = entry.value, str(entry.key)
        try:
            if isinstance(value, Scalar):
                if value.value is None or str(value.value).strip() == "":
                    self.error(entry.line, control, "the binding is empty", "write e.g. 'note 36' or 'cc 20'")
                    return None
                return parse_phrase(str(value.value))
            if isinstance(value, SeqNode):
                return _merge_list([parse_phrase(_scalar_text(item)) for item in value.items])
            if isinstance(value, MapNode):
                return self._mapping_spec(value, control)
        except PhraseError as error:
            self.error(entry.line, control, error.problem, error.fix)
            return None
        self.error(entry.line, control, "the binding is not a phrase", "write e.g. 'note 36 on mpc ch 10'")
        return None

    def _mapping_spec(self, node: MapNode, control: str) -> BindingSpec:
        """{send: <phrase or list>, <option>: <value>, …}: the same words as the phrase, as keys."""
        for sub in node.entries:
            if normalise_key(sub.key) not in BINDING_KEYS:
                raise PhraseError(f"unknown binding key '{sub.key}'",
                                  "a binding mapping takes " + ", ".join(BINDING_KEYS))
        send = node.get("send")
        if send is None:
            raise PhraseError("the binding has no 'send'", "write e.g. '{send: note 36, colour: red}'")
        spec = (_merge_list([parse_phrase(_scalar_text(i)) for i in send.value.items])
                if isinstance(send.value, SeqNode) else parse_phrase(_scalar_text(send.value)))
        words = []
        for sub in node.entries:
            key, text = normalise_key(sub.key), _scalar_text(sub.value)
            truthy = text.lower() in ("true", "yes", "on")
            if key == "send":
                continue
            if key in ("toggle", "feedback") and (truthy or text.lower() in ("false", "no", "off")):
                words.append(key if truthy else "")
            elif key in ("mode", "style"):
                words.append(text)
            elif key == "bar":
                words.append("bar" if truthy else text)
            elif key == "label":
                words.append('label "' + text.replace('"', '\\"') + '"')
            elif key in ("colour", "color", "off"):
                words.append(f"{key} {text.replace(' ', '')}")
            else:
                words.append(f"{key} {text}")
        return parse_options(" ".join(w for w in words if w), spec)

    def _actions(self, spec: BindingSpec, count: int, line: int, control: str, value_for) -> list[list[Action]] | None:
        """Per control index, the Actions of the binding (ranges expanded across `count` controls)."""
        per_control: list[list[Action]] = [[] for _ in range(count)]
        for message in spec.messages:
            device = self._device(message.device, line, control)
            if device is None:
                return None
            channel = self._channel(message.channel, device, line, control)
            if channel is None:
                return None
            numbers = self._numbers(message, count, line, control)
            if numbers is None:
                return None
            for i in range(count):
                try:
                    lsb = None if message.lsb is None else message.lsb + numbers[i] - numbers[0]   # ranges shift both
                    per_control[i].append(Action(device, message.kind, channel, numbers[i], value_for(message), lsb))
                except DomainInvariantError as error:
                    self.invariant(line, control, error)
                    return None
        return per_control

    def _numbers(self, message: MessageSpec, count: int, line: int, control: str) -> list | None:
        if message.kind is MessageKind.PITCHBEND:
            return [None] * count
        word = {MessageKind.NOTE: "notes", MessageKind.CC: "cc"}.get(message.kind, str(message.kind))
        try:
            first = self._number(message.kind, message.first)
            if message.ascending:
                numbers = [first + i for i in range(count)]
            elif message.last is not None:
                last = self._number(message.kind, message.last)
                if last - first + 1 != count:
                    self.error(line, control,
                               f"{word} {message.first}-{message.last} is {last - first + 1} values for {count} "
                               f"control{'s' if count != 1 else ''}",
                               f"write {word} {message.first}-{first + count - 1} or {word} from {message.first}")
                    return None
                numbers = list(range(first, last + 1))
            else:
                numbers = [first] * count
        except DomainInvariantError as error:
            self.invariant(line, control, error)
            return None
        if any(n > 127 for n in numbers):
            self.error(line, control, f"{word} from {message.first} runs past 127 over {count} controls",
                       "start lower or bind fewer controls")
            return None
        return numbers

    @staticmethod
    def _number(kind: MessageKind, text) -> int:
        if kind is MessageKind.NOTE:
            return int(parse_note(text))
        if not re.fullmatch(r"\d+", str(text)):
            raise DomainInvariantError(str(kind), f"'{text}' is not a {kind} number", f"write e.g. '{kind} 20'")
        return int(text)

    def _feedback(self, spec: BindingSpec, actions: list[Action], line: int, control: str) -> FeedbackRule | None:
        fb = spec.feedback
        if fb is None:
            if spec.off_colour is not None:
                self.error(line, control, "'off' sets the colour shown when feedback is off",
                           "add 'feedback' or remove 'off'")
            return None
        try:
            colours = tuple((int(v), parse_colour(c)) for v, c in fb.colours)
            off = parse_colour(spec.off_colour) if spec.off_colour is not None else None
            if fb.kind is None:
                first = actions[0]
                if first.kind not in (MessageKind.NOTE, MessageKind.CC):
                    raise DomainInvariantError("feedback", f"plain 'feedback' cannot follow {first.kind}",
                                               "write 'feedback cc <n> from <device>'")
                return FeedbackRule(first.device, first.kind, first.number, first.channel, None, off, colours)
            device = self._device(fb.device or actions[0].device, line, control)
            if device is None:
                return None
            channel = Channel(fb.channel) if fb.channel is not None else None
            return FeedbackRule(device, fb.kind, self._number(fb.kind, fb.number), channel, None, off, colours)
        except DomainInvariantError as error:
            self.invariant(line, control, error)
            return None

    def _page_bindings(self, entry: Entry, controls, layer: Layer) -> dict | None:
        spec = self._spec(entry)
        if spec is None:
            return None
        if spec.none:
            return {control: None for control in controls}
        control_text = str(entry.key)
        if spec.touch is not None or spec.style is not None:
            self.error(entry.line, control_text, "touch, bar and bipolar are strip options",
                       "remove them, or bind strips under banks:")
            return None
        if any(isinstance(c, Strip) for c in controls):
            self.error(entry.line, control_text, "strips are bound in banks", "move it under banks:")
            return None
        mode = BindingMode.TOGGLE if spec.toggle else BindingMode.MOMENTARY
        toggle_values = spec.toggle_values

        def value_for(message: MessageSpec):
            if any(isinstance(c, Encoder) for c in controls):
                return EncoderValue()
            if spec.toggle:
                values = toggle_values or ((message.value if message.value is not None else 127), 0)
                return ToggleState(ToggleValues(*values)) if message.kind in (MessageKind.CC, MessageKind.NOTE) \
                    else None
            if message.kind is MessageKind.NOTE:
                return Fixed(spec.velocity) if spec.velocity is not None else PressVelocity()
            if message.kind is MessageKind.CC:
                return Fixed(message.value if message.value is not None else 127)
            return None

        try:
            per_control = self._actions(spec, len(controls), entry.line, control_text, value_for)
            if per_control is None:
                return None
            colour = parse_colour(spec.colour) if spec.colour is not None else None
            bindings = {}
            for control, actions in zip(controls, per_control):
                feedback = self._feedback(spec, actions, entry.line, control_text)
                if spec.feedback is not None and feedback is None:
                    return None
                binding = Binding(tuple(actions), mode, spec.label, colour, feedback)
                check_page_binding(control, layer, binding)
                bindings[control] = binding
            return bindings
        except DomainInvariantError as error:
            self.invariant(entry.line, control_text, error)
            return None

    def _bank_bindings(self, entry: Entry, controls) -> dict | None:
        control_text = str(entry.key)
        if not all(isinstance(c, Strip) for c in controls):
            self.error(entry.line, control_text, f"{control_text} is not a strip",
                       "banks hold strips 1–8; bind pads and buttons in pages")
            return None
        spec = self._spec(entry)
        if spec is None:
            return None
        if spec.none:
            return {control: None for control in controls}
        if len(spec.messages) != 1:
            self.error(entry.line, control_text, "a strip sends one position message",
                       "write one of cc <n>, cc14 <n> or pitchbend; add 'touch note <n>' for the touch")
            return None

        def position_value(message):
            return StripPosition()

        def touch_value(message):
            return PressVelocity() if message.kind is MessageKind.NOTE else Fixed(127)

        try:
            per_control = self._actions(spec, len(controls), entry.line, control_text, position_value)
            if per_control is None:
                return None
            touches = None
            if spec.touch is not None:
                touch = spec.touch
                if touch.device is None:
                    touch.device = spec.messages[0].device
                if touch.channel is None:
                    touch.channel = spec.messages[0].channel
                touches = self._actions(BindingSpec([touch]), len(controls), entry.line, control_text, touch_value)
                if touches is None:
                    return None
            colour = parse_colour(spec.colour) if spec.colour is not None else WHITE
            style = StripBarStyle.BIPOLAR if spec.style == "bipolar" else StripBarStyle.BAR
            mode = BindingMode.TOGGLE if spec.toggle else BindingMode.MOMENTARY
            bindings = {}
            for i, control in enumerate(controls):
                actions = per_control[i]
                feedback = self._feedback(spec, actions, entry.line, control_text)
                if spec.feedback is not None and feedback is None:
                    return None
                bindings[control] = StripBinding(actions[0], touches[i][0] if touches else None, colour, style,
                                                 feedback, spec.label, mode)
            return bindings
        except DomainInvariantError as error:
            self.invariant(entry.line, control_text, error)
            return None

    # --- routing --------------------------------------------------------------------------------------
    def _routing(self, entry: Entry | None) -> dict:
        if entry is None:
            return {}
        if not isinstance(entry.value, MapNode):
            self.error(entry.line, "routing", "routing has a 'notes:' and/or a 'custom:' line",
                       "write 'routing:' then '  notes: mpc ch 2'")
            return {}
        rules = {}
        for item in entry.value.entries:
            key = normalise_key(item.key)
            if key not in ROUTING_KEYS:
                self.error(item.line, f"routing {item.key}", f"unknown routing port '{item.key}'",
                           "route 'notes' (Note/Chord/Step/Drum views) or 'custom' (Custom view)")
                continue
            role = UnitPortRole(key)
            try:
                spec = self._routing_spec(item.value)
                device = self._device(spec.device, item.line, f"routing {key}")
                if device is None:
                    continue
                channel = self._channel(spec.channel, device, item.line, f"routing {key}")
                if channel is None:
                    continue
                remap = tuple((int(parse_note(a)), int(parse_note(b))) for a, b in spec.remap)
                rules[role] = RoutingRule(role, device, channel, AftertouchPolicy(spec.aftertouch), spec.transpose,
                                          remap)
            except PhraseError as error:
                self.error(item.line, f"routing {key}", error.problem, error.fix)
            except DomainInvariantError as error:
                self.invariant(item.line, f"routing {key}", error)
        return rules

    def _routing_spec(self, value: Node) -> RoutingSpec:
        if isinstance(value, Scalar):
            return parse_routing(str(value.value or ""))
        if isinstance(value, MapNode):
            words = []
            for sub in value.entries:
                key, text = normalise_key(sub.key), sub.value
                if key in ("device", "to", "on"):
                    words.insert(0, _scalar_text(text))
                elif key == "remap" and isinstance(text, MapNode):
                    words.append("remap " + " ".join(f"{e.key}>{_scalar_text(e.value)}" for e in text.entries))
                else:
                    words.append(f"{key} {_scalar_text(text)}")
            return parse_routing(" ".join(words))
        raise PhraseError("routing is a phrase", "write e.g. 'notes: mpc ch 2 aftertouch pass'")


CONTROL_LIKE = re.compile(r"^(pads?|tracks?|trackctls?|strips?|scenes?|play|rec|stop|encoder)\b")


def _section_node(node: Node):
    """The parser's node as the domain's section value types (plain values with their lines)."""
    if isinstance(node, MapNode):
        return SectionMap(tuple(SectionEntry(str(e.key), e.line, _section_node(e.value)) for e in node.entries),
                          node.line)
    if isinstance(node, SeqNode):
        return SectionList(tuple(_section_node(item) for item in node.items), node.line)
    return SectionScalar(node.value, node.line)


def _scalar_text(node: Node) -> str:
    if isinstance(node, Scalar):
        return "" if node.value is None else str(node.value)
    raise PhraseError("expected a phrase here", "write the message as text, e.g. 'note 36'")


def _as_int(node: Node) -> int:
    if isinstance(node, Scalar) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, Scalar) and re.fullmatch(r"\d+", str(node.value)):
        return int(node.value)
    raise DomainInvariantError("channel", "channel must be 1–16", "write a whole number from 1 to 16")


def _merge_list(specs: list[BindingSpec]) -> BindingSpec:
    """A YAML list of phrases is several messages sent in order; their options merge."""
    merged = BindingSpec([m for s in specs for m in s.messages])
    for spec in specs:
        for name in ("toggle", "toggle_values", "colour", "label", "velocity", "feedback", "off_colour", "touch",
                     "style"):
            value = getattr(spec, name)
            if value not in (None, False):
                setattr(merged, name, value)
    return merged


def _count(layout: Layout) -> Counts:
    pads = buttons = encoders = strips = 0
    for page in layout.pages.values():
        for bindings in page.layers.values():
            for control in bindings:
                if isinstance(control, PadPos):
                    pads += 1
                elif isinstance(control, Encoder):
                    encoders += 1
                else:
                    buttons += 1
    for bank in layout.banks.values():
        for bindings in bank.layers.values():
            strips += len(bindings)
    return Counts(len(layout.pages), len(layout.banks), pads, buttons, strips, encoders, len(layout.routing))
