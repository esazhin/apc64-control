"""The Layout aggregate: devices named once, up to 8 pages of pad/button bindings on base and Shift layers,
up to 6 banks of strip bindings, and one expressive routing rule per unit port (contract §7 value objects).

Every constructor checks its own invariant and raises DomainInvariantError(field, problem, fix); the
notation compiler turns those into LayoutIssues at the right file and line.
"""
import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, Protocol, runtime_checkable

from .controls import (
    ControlId, ControlRole, DeviceLocal, Encoder, EncoderPress, SceneButton, Shift, Strip, StripModeButton,
    StripTouch, role_of,
)
from .issues import DomainInvariantError, LayoutIssue
from .leds import StripBarStyle
from .midi import Channel, CcNumber, Note, Program, Value7
from .palette import WHITE, Colour

APC64_PORT_STEM = "APC64"
MAX_PAGES, MAX_BANKS = 8, 6
_LAYOUT_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_DEVICE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


class LayoutId(str):
    """A layout's identity: its file stem ([A-Za-z0-9_-]+), never a path (contract q11, §7.1)."""

    def __new__(cls, value):
        value = str(value)
        if not _LAYOUT_ID.match(value):
            raise DomainInvariantError("layout", f"'{value}' is not a layout file name",
                                       "name layout files with letters, digits, '-' or '_' and end them in .yaml")
        return super().__new__(cls, value)


class Layer(StrEnum):
    BASE = "base"
    SHIFT = "shift"


class PageNo(int):
    def __new__(cls, value):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PAGES:
            raise DomainInvariantError("page", "the APC64 has 8 scene buttons", "so pages are 1–8", joiner=", ")
        return super().__new__(cls, value)


class BankNo(int):
    def __new__(cls, value):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_BANKS:
            raise DomainInvariantError("bank", "the APC64 has 6 strip-mode buttons", "so banks are 1–6", joiner=", ")
        return super().__new__(cls, value)


class DeviceName(str):
    def __new__(cls, value):
        value = str(value)
        if not _DEVICE_NAME.match(value):
            raise DomainInvariantError("device", f"'{value}' is not a device name",
                                       "start device names with a letter and use letters, digits, '-' or '_'")
        return super().__new__(cls, value)


PortName = str


class PortPattern(str):
    """An ALSA port name, or a unique part of one (contract d59); matched without regard to case."""

    def __new__(cls, value):
        value = " ".join(str(value).split())
        if not value:
            raise DomainInvariantError("device", "the port name is empty", "write the ALSA port name")
        return super().__new__(cls, value)

    def matches(self, port: str) -> bool:
        return self.casefold() == port.casefold() or self.casefold() in port.casefold()

    def names_apc64(self) -> bool:
        return APC64_PORT_STEM.casefold() in self.casefold()


@dataclass(frozen=True)
class DeviceDecl:
    """A device declared once by name: the ALSA port it means and an optional default channel (q3)."""
    name: DeviceName
    pattern: PortPattern
    default_channel: Channel | None = None

    def __post_init__(self):
        object.__setattr__(self, "name", DeviceName(self.name))
        object.__setattr__(self, "pattern", PortPattern(self.pattern))
        if self.default_channel is not None:
            object.__setattr__(self, "default_channel", Channel(self.default_channel))
        if self.pattern.names_apc64():
            raise DomainInvariantError(
                "device", f"device {self.name} targets an APC64 port",
                "the host never sends to the APC64's own ports, choose another port")


class UnitPortRole(StrEnum):
    DAW = "daw"
    NOTES = "notes"
    CUSTOM = "custom"


class MessageKind(StrEnum):
    NOTE = "note"
    CC = "cc"
    CC14 = "cc14"
    PROGRAM = "program"
    PITCHBEND = "pitchbend"


class BindingMode(StrEnum):
    MOMENTARY = "momentary"
    TOGGLE = "toggle"


@dataclass(frozen=True)
class ToggleValues:
    on: Value7 = 127
    off: Value7 = 0

    def __post_init__(self):
        object.__setattr__(self, "on", Value7(self.on))
        object.__setattr__(self, "off", Value7(self.off))


@dataclass(frozen=True)
class Fixed:
    value: Value7

    def __post_init__(self):
        object.__setattr__(self, "value", Value7(self.value))


@dataclass(frozen=True)
class PressVelocity:
    """The velocity the unit reported (127 for Session pads, contract q4)."""


@dataclass(frozen=True)
class StripPosition:
    """The strip's 14-bit position, scaled to the target message (contract d54)."""


@dataclass(frozen=True)
class EncoderValue:
    """The absolute 0–127 value the host keeps for an encoder binding (contract q2)."""


@dataclass(frozen=True)
class ToggleState:
    values: ToggleValues = ToggleValues()


ValueSource = Fixed | PressVelocity | StripPosition | EncoderValue | ToggleState

_KIND_NUMBER = {MessageKind.NOTE: Note, MessageKind.CC: CcNumber, MessageKind.CC14: CcNumber,
                MessageKind.PROGRAM: Program}


@dataclass(frozen=True)
class Action:
    """One MIDI message a binding sends to a declared device."""
    device: DeviceName
    kind: MessageKind
    channel: Channel
    number: int | None
    value: ValueSource | None = None
    lsb: int | None = None   # the LSB controller of a 14-bit CC pair

    def __post_init__(self):
        object.__setattr__(self, "device", DeviceName(self.device))
        object.__setattr__(self, "channel", Channel(self.channel))
        if self.kind is MessageKind.PITCHBEND:
            if self.number is not None:
                raise DomainInvariantError("action", "pitch bend has no number", "write just 'pitchbend'")
        else:
            object.__setattr__(self, "number", _KIND_NUMBER[self.kind](self.number))
        if self.kind is MessageKind.CC14:
            lsb = self.number + 32 if self.lsb is None else self.lsb
            if lsb > 127:
                raise DomainInvariantError("action", f"cc14 {self.number} has no LSB controller above 127",
                                           "write the pair explicitly, e.g. cc14 100/101")
            object.__setattr__(self, "lsb", CcNumber(lsb))


@dataclass(frozen=True)
class FeedbackRule:
    """Incoming note/CC on a device's input port that drives a control's LED or a strip's bar (d97–d103).

    channel None matches any channel. Value 0 shows the off look (off_colour at full, or the binding's
    idle look), any other value the on look (on_colour, or the binding's colour), unless colours lists
    a colour for that exact value.
    """
    device: DeviceName
    kind: MessageKind
    number: int
    channel: Channel | None = None
    on_colour: Colour | None = None
    off_colour: Colour | None = None
    colours: tuple[tuple[int, Colour], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "device", DeviceName(self.device))
        if self.kind not in (MessageKind.NOTE, MessageKind.CC):
            raise DomainInvariantError("feedback", f"feedback cannot follow {self.kind}",
                                       "use 'feedback note <n>' or 'feedback cc <n>'")
        object.__setattr__(self, "number", _KIND_NUMBER[self.kind](self.number))
        if self.channel is not None:
            object.__setattr__(self, "channel", Channel(self.channel))


_MODULE_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class ModuleAction:
    """A binding kind that calls a registered module's action instead of sending MIDI (contract 2, s2.c7):
    e.g. ModuleAction('lab', 'window_shift') on the base-layer encoder. Never on the Shift layer."""
    module: str
    action: str

    def __post_init__(self):
        for what, value in (("module", self.module), ("action", self.action)):
            if not isinstance(value, str) or not _MODULE_NAME.match(value):
                raise DomainInvariantError("binding", f"'{value}' is not a {what} name",
                                           "use lower-case letters, digits, '-' or '_'")

    def __str__(self) -> str:
        return f"{self.module}.{self.action}"


@dataclass(frozen=True)
class ControlEvent:
    """What a ModuleAction handler is called with: an encoder turn of ±steps, or a press (s2.c7)."""
    steps: int = 0
    press: bool = False

    @classmethod
    def turn(cls, steps: int) -> "ControlEvent":
        return cls(int(steps), False)

    @classmethod
    def pressed(cls) -> "ControlEvent":
        return cls(0, True)


@dataclass(frozen=True)
class Binding:
    """What a pad, button or the encoder does on one page and layer: MIDI actions, or one ModuleAction."""
    actions: tuple[Action, ...]
    mode: BindingMode = BindingMode.MOMENTARY
    label: str | None = None
    colour: Colour | None = None
    feedback: FeedbackRule | None = None
    module_action: ModuleAction | None = None

    def __post_init__(self):
        object.__setattr__(self, "actions", tuple(self.actions))
        if self.module_action is not None:
            if self.actions or self.mode is not BindingMode.MOMENTARY or self.feedback is not None:
                raise DomainInvariantError("binding", f"{self.module_action} is a module action",
                                           "a module action binding sends no MIDI, has no toggle and no feedback")
            return
        if not self.actions:
            raise DomainInvariantError("binding", "a binding needs at least one message",
                                       "write e.g. 'note 36' or 'cc 20'")
        for action in self.actions:
            if action.kind in (MessageKind.PITCHBEND, MessageKind.CC14):
                raise DomainInvariantError(
                    "action", f"{action.kind} is for strips",
                    "on pads and buttons use note, cc or program")

    @property
    def toggle(self) -> bool:
        return self.mode is BindingMode.TOGGLE

    @property
    def is_module_action(self) -> bool:
        return self.module_action is not None

    @property
    def look_colour(self) -> Colour:
        return self.colour or WHITE


@dataclass(frozen=True)
class StripBinding:
    """A strip in a bank: its position message, an optional touch message, bar look and feedback."""
    position: Action
    touch: Action | None = None
    colour: Colour = WHITE
    style: StripBarStyle = StripBarStyle.BAR
    feedback: FeedbackRule | None = None
    label: str | None = None
    mode: BindingMode = BindingMode.MOMENTARY

    def __post_init__(self):
        if self.mode is BindingMode.TOGGLE:
            raise DomainInvariantError("mode", "a strip position cannot be a toggle", 'remove "toggle"')
        if self.position.kind not in (MessageKind.CC, MessageKind.CC14, MessageKind.PITCHBEND):
            raise DomainInvariantError("strip", f"a strip position cannot send {self.position.kind}",
                                       "use cc, cc14 or pitchbend for strips")
        if self.touch is not None and self.touch.kind not in (MessageKind.NOTE, MessageKind.CC):
            raise DomainInvariantError("touch", f"a strip touch cannot send {self.touch.kind}",
                                       "use 'touch note <n>' or 'touch cc <n>'")


def check_page_binding(control: ControlId, layer: Layer, binding: Binding):
    """Refuses controls a page cannot bind: navigation, Shift, the unit's own, strips, Shift + encoder."""
    role = role_of(control)
    if isinstance(control, SceneButton):
        raise DomainInvariantError("control", f"{control} selects page {control.n} and cannot be bound",
                                   "bind another control; scene buttons are navigation")
    if isinstance(control, StripModeButton):
        raise DomainInvariantError("control", f"{control} selects bank {control.n} and cannot be bound",
                                   "bind another control; strip-mode buttons are navigation")
    if isinstance(control, (Strip, StripTouch)):
        raise DomainInvariantError("control", "strips are bound in banks", "move it under banks:")
    if isinstance(control, Shift) or isinstance(control, DeviceLocal) or role is not ControlRole.BINDABLE:
        raise DomainInvariantError("control", f"{control} is not bindable",
                                   "Shift selects the Shift layer and the view buttons belong to the unit")
    if layer is Layer.SHIFT and isinstance(control, (Encoder, EncoderPress)):
        raise DomainInvariantError("control", "Shift + encoder browses layouts and cannot be bound",
                                   "bind the encoder on the base layer")
    if binding.is_module_action:
        if layer is Layer.SHIFT:
            raise DomainInvariantError("control", f"{binding.module_action} binds the base layer only",
                                       "move it out of 'shift:'")
        return
    if isinstance(control, Encoder):
        if len(binding.actions) != 1 or binding.actions[0].kind is not MessageKind.CC or binding.toggle:
            raise DomainInvariantError("encoder", "the encoder turn sends one CC with the value the host keeps",
                                       "write 'encoder: cc <n>'")


@dataclass(frozen=True)
class Page:
    number: PageNo
    name: str | None = None
    layers: dict[Layer, dict[ControlId, Binding]] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "number", PageNo(self.number))
        layers = {Layer.BASE: dict(self.layers.get(Layer.BASE, {})), Layer.SHIFT: dict(self.layers.get(Layer.SHIFT, {}))}
        for layer, bindings in layers.items():
            for control, binding in bindings.items():
                check_page_binding(control, layer, binding)
        object.__setattr__(self, "layers", layers)

    @property
    def display_name(self) -> str:
        return self.name or f"Page {self.number}"

    @property
    def encoder(self) -> Binding | None:
        return self.layers[Layer.BASE].get(Encoder())

    def binding(self, layer: Layer, control: ControlId) -> Binding | None:
        return self.layers[layer].get(control)

    @property
    def empty(self) -> bool:
        return not any(self.layers.values())


@dataclass(frozen=True)
class Bank:
    number: BankNo
    name: str | None = None
    layers: dict[Layer, dict[Strip, StripBinding]] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "number", BankNo(self.number))
        layers = {Layer.BASE: dict(self.layers.get(Layer.BASE, {})), Layer.SHIFT: dict(self.layers.get(Layer.SHIFT, {}))}
        for bindings in layers.values():
            for control in bindings:
                if not isinstance(control, Strip):
                    raise DomainInvariantError("control", f"{control} is not a strip",
                                               "banks hold strips 1–8; bind pads and buttons in pages")
        object.__setattr__(self, "layers", layers)

    @property
    def display_name(self) -> str:
        return self.name or f"Bank {self.number}"

    def binding(self, layer: Layer, strip: Strip) -> StripBinding | None:
        return self.layers[layer].get(strip)


class AftertouchPolicy(StrEnum):
    PASS = "pass"
    CHANNEL_PRESSURE = "pressure"
    DROP = "drop"


@dataclass(frozen=True)
class RoutingRule:
    """How notes played in the unit's own views reach a target (contract d139–d146)."""
    role: UnitPortRole
    device: DeviceName
    channel: Channel
    aftertouch: AftertouchPolicy = AftertouchPolicy.PASS
    transpose: int = 0
    remap: tuple[tuple[int, int], ...] = ()

    def __post_init__(self):
        if self.role is UnitPortRole.DAW:
            raise DomainInvariantError("routing", "the DAW port carries the surface, not played notes",
                                       "route 'notes' or 'custom'")
        object.__setattr__(self, "device", DeviceName(self.device))
        object.__setattr__(self, "channel", Channel(self.channel))
        if isinstance(self.transpose, bool) or not isinstance(self.transpose, int) or not -127 <= self.transpose <= 127:
            raise DomainInvariantError("transpose", "transpose must be −127 to 127", "write e.g. 'transpose 12'")
        remap = tuple(sorted((int(Note(a)), int(Note(b))) for a, b in dict(self.remap).items()))
        object.__setattr__(self, "remap", remap)

    def remap_of(self, note: int) -> int:
        return dict(self.remap).get(note, note)


@dataclass(frozen=True)
class PageLocation:
    page: PageNo
    layer: Layer
    control: ControlId


@dataclass(frozen=True)
class BankLocation:
    bank: BankNo
    layer: Layer
    strip: Strip


Location = PageLocation | BankLocation


@dataclass(frozen=True)
class FeedbackIndex:
    """Incoming (device, kind, number) → the rules and the places they drive."""
    entries: dict[tuple[DeviceName, MessageKind, int], tuple[tuple[FeedbackRule, Location], ...]]

    def lookup(self, device: str, kind: MessageKind, number: int, channel: int):
        for rule, location in self.entries.get((device, kind, number), ()):
            if rule.channel is None or rule.channel == channel:
                yield rule, location


@dataclass(frozen=True)
class Layout:
    id: LayoutId
    name: str | None
    devices: dict[DeviceName, DeviceDecl]
    pages: dict[PageNo, Page] = field(default_factory=dict)
    banks: dict[BankNo, Bank] = field(default_factory=dict)
    routing: dict[UnitPortRole, RoutingRule] = field(default_factory=dict)
    sections: dict[str, object] = field(default_factory=dict)   # module-owned top-level sections, compiled

    def section(self, name: str) -> object | None:
        return self.sections.get(name)

    def __post_init__(self):
        object.__setattr__(self, "id", LayoutId(self.id))
        for key, page in self.pages.items():
            if PageNo(key) != page.number:
                raise DomainInvariantError("page", f"page {key} holds page {page.number}", "number pages once")
        for key, bank in self.banks.items():
            if BankNo(key) != bank.number:
                raise DomainInvariantError("bank", f"bank {key} holds bank {bank.number}", "number banks once")
        for role, rule in self.routing.items():
            if rule.role is not role:
                raise DomainInvariantError("routing", f"the {role} rule is for {rule.role}", "route each port once")
        for device in self.referenced_devices():
            if device not in self.devices:
                raise DomainInvariantError("device", f"unknown device {device}",
                                           f"declared devices: {', '.join(self.devices) or 'none'}", joiner=", ")

    @property
    def display_name(self) -> str:
        return self.name or str(self.id)

    def referenced_devices(self) -> list[DeviceName]:
        found = []
        for page in self.pages.values():
            for bindings in page.layers.values():
                for binding in bindings.values():
                    found += [a.device for a in binding.actions]
                    found += [binding.feedback.device] if binding.feedback else []
        for bank in self.banks.values():
            for bindings in bank.layers.values():
                for strip in bindings.values():
                    found += [strip.position.device] + ([strip.touch.device] if strip.touch else [])
                    found += [strip.feedback.device] if strip.feedback else []
        found += [rule.device for rule in self.routing.values()]
        return list(dict.fromkeys(found))

    def page(self, number: int) -> Page | None:
        return self.pages.get(number)

    def bank(self, number: int) -> Bank | None:
        return self.banks.get(number)

    def feedback_index(self) -> FeedbackIndex:
        entries: dict = {}
        for page in self.pages.values():
            for layer, bindings in page.layers.items():
                for control, binding in bindings.items():
                    if binding.feedback:
                        rule = binding.feedback
                        entries.setdefault((rule.device, rule.kind, rule.number), []).append(
                            (rule, PageLocation(page.number, layer, control)))
        for bank in self.banks.values():
            for layer, bindings in bank.layers.items():
                for strip, binding in bindings.items():
                    if binding.feedback:
                        rule = binding.feedback
                        entries.setdefault((rule.device, rule.kind, rule.number), []).append(
                            (rule, BankLocation(bank.number, layer, strip)))
        return FeedbackIndex({key: tuple(value) for key, value in entries.items()})


@dataclass(frozen=True)
class NavState:
    """Where the surface is: layout, page, bank and whether Shift is held."""
    layout: LayoutId | None
    page: PageNo = PageNo(1)
    bank: BankNo = BankNo(1)
    shift: bool = False

    @property
    def layer(self) -> Layer:
        return Layer.SHIFT if self.shift else Layer.BASE


class ContentHash(str):
    """sha256 of a layout file's text (hex), used for dedupe, versions and stale-tweak checks."""

    @classmethod
    def of(cls, text: str) -> "ContentHash":
        return cls(hashlib.sha256(text.encode()).hexdigest())


@dataclass(frozen=True, order=True)
class VersionId:
    timestamp: str   # sortable UTC stamp, e.g. 20261023T104200.123Z
    hash: ContentHash

    def __str__(self) -> str:
        return f"{self.timestamp}-{self.hash[:12]}"



@dataclass(frozen=True)
class LayoutCatalog:
    """The layouts that can be browsed and loaded, in alphabetical order of display name (contract d106)."""
    entries: tuple[tuple[LayoutId, str], ...] = ()

    @classmethod
    def of(cls, pairs) -> "LayoutCatalog":
        return cls(tuple(sorted(((LayoutId(i), n) for i, n in pairs), key=lambda p: (p[1].casefold(), p[0]))))

    @property
    def ids(self) -> tuple[LayoutId, ...]:
        return tuple(i for i, _ in self.entries)

    def name_of(self, layout: LayoutId) -> str | None:
        return next((n for i, n in self.entries if i == layout), None)

    def step(self, layout: LayoutId | None, steps: int) -> LayoutId | None:
        """The layout `steps` places from `layout`, wrapping at the ends."""
        if not self.entries:
            return None
        ids = self.ids
        if layout in ids:
            start = ids.index(layout)
        else:   # not in the catalog: the first step forwards lands on the first entry, backwards on the last
            start = -1 if steps > 0 else 0
        return ids[(start + steps) % len(ids)]


class TweakField(StrEnum):
    ASSIGNMENT = "assignment"   # a binding phrase ('cc 74 on mpc ch 1'), or 'none' to unbind
    LABEL = "label"
    COLOUR = "colour"
    MODE = "mode"               # 'toggle' or 'momentary'


@dataclass(frozen=True)
class TweakRequest:
    """One control's change from the page, on one page (or bank) and layer, against the file it was read from."""
    layout: LayoutId
    layer: Layer
    control: ControlId
    field: TweakField
    value: str | None
    base_hash: ContentHash
    page: PageNo | None = None
    bank: BankNo | None = None

    def __post_init__(self):
        object.__setattr__(self, "layout", LayoutId(self.layout))
        object.__setattr__(self, "layer", Layer(self.layer))
        object.__setattr__(self, "field", TweakField(self.field))
        if (self.page is None) == (self.bank is None):
            raise DomainInvariantError("tweak", "a tweak names a page or a bank", "send page or bank, not both")
        if self.page is not None:
            object.__setattr__(self, "page", PageNo(self.page))
        if self.bank is not None:
            object.__setattr__(self, "bank", BankNo(self.bank))
        if self.field is TweakField.MODE and self.value not in ("toggle", "momentary"):
            raise DomainInvariantError("mode", f"mode '{self.value}' is not a choice", "send toggle or momentary")


# --- module-owned layout sections (contract 2, s4) -------------------------------------------------------
@dataclass(frozen=True)
class SectionScalar:
    value: object
    line: int


@dataclass(frozen=True)
class SectionEntry:
    key: str
    line: int
    value: "SectionNode"


@dataclass(frozen=True)
class SectionMap:
    entries: tuple[SectionEntry, ...]
    line: int

    def get(self, key: str) -> SectionEntry | None:
        return next((e for e in self.entries if e.key.lower() == key.lower()), None)


@dataclass(frozen=True)
class SectionList:
    items: tuple["SectionNode", ...]
    line: int


SectionNode = SectionScalar | SectionMap | SectionList


@dataclass(frozen=True)
class ExistingBinding:
    """An explicit base-layer binding the layout already has, where it is written (s4.c1)."""
    page: PageNo
    line: int
    binding: Binding


@dataclass(frozen=True)
class SectionResult:
    """What a module's section compiler gives back (s4.c2): its compiled value, the base-layer bindings it
    implies (joined to every page), and its issues — any error makes the layout invalid.

    Contract 2 (§2.7 q2): a section may also imply a default routing rule per unit port and the devices that
    rule names. They are defaults: the layout's own routing line for that port, and its own declaration of a
    device by that name, win (the per-layout override)."""
    value: object | None
    bindings: dict = field(default_factory=dict)          # ControlId → Binding (base layer)
    issues: tuple[LayoutIssue, ...] = ()
    warnings: tuple[LayoutIssue, ...] = ()
    routing: dict = field(default_factory=dict)           # UnitPortRole → RoutingRule (default only)
    devices: dict = field(default_factory=dict)           # DeviceName → DeviceDecl (default only)


@runtime_checkable
class SectionCompiler(Protocol):
    """Compiles one module-owned top-level section of a layout file (e.g. 'lab:')."""

    def compile(self, section: SectionEntry, file: str,
                existing: Mapping[object, tuple[ExistingBinding, ...]]) -> SectionResult:
        """`section`: the top-level key, its line and its value as SectionNodes; `existing`: the layout's
        explicit base-layer bindings by control."""
        ...
