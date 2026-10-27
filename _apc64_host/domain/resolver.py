"""The single read model (contract §7.1): what every control means for a layout and a NavState.

Replica labels, the Shift preview, the detail card, the overview, the nav bar and the OLED idle text are
all derived here, so they cannot disagree (contract inv1).
"""
from dataclasses import dataclass

from .controls import (
    SURFACE, ControlId, ControlRole, DeviceLocal, Reachability, SceneButton, Shift, Strip, StripModeButton,
    StripTouch, entry,
)
from .layout import (
    MAX_BANKS, MAX_PAGES, Action, Bank, BankLocation, Binding, DeviceName, Layer, Layout, MessageKind, NavState,
    Page, PageLocation, StripBinding,
)
from .oled import OledText


# --- labels -------------------------------------------------------------------------------------------
def message_text(action: Action) -> str:
    """The message part of a label: 'Note 36', 'CC118', 'CC20/52', 'Prog 5', 'Bend'."""
    match action.kind:
        case MessageKind.NOTE:
            return f"Note {action.number}"
        case MessageKind.CC:
            return f"CC{action.number}"
        case MessageKind.CC14:
            return f"CC{action.number}/{action.lsb}"
        case MessageKind.PROGRAM:
            return f"Prog {action.number}"
    return "Bend"


def _main_action(binding: Binding | StripBinding) -> Action:
    return binding.position if isinstance(binding, StripBinding) else binding.actions[0]


def _actions(binding: Binding | StripBinding) -> tuple[Action, ...]:
    if isinstance(binding, StripBinding):
        return (binding.position,) + ((binding.touch,) if binding.touch else ())
    return binding.actions


def binding_label(binding: Binding | StripBinding | None, missing: frozenset = frozenset()) -> str:
    """The label a control shows: its own, or generated ('Note 36 → mpc'), with '(missing)' when a target
    device is not present (contract d58, A83). Empty for an unbound control."""
    if binding is None:
        return ""
    if getattr(binding, "module_action", None) is not None:   # contract 2: a module's action, no MIDI
        return binding.label or str(binding.module_action)
    action = _main_action(binding)
    label = binding.label or f"{message_text(action)} → {action.device}"
    extra = len(binding.actions) - 1 if isinstance(binding, Binding) else 0
    if extra and not binding.label:
        label += f" +{extra}"
    if any(a.device in missing for a in _actions(binding)):
        label += " (missing)"
    return label


def binding_detail(binding: Binding | StripBinding) -> str:
    """The card's full description: 'Note 36 → mpc ch 10, momentary' (contract A129)."""
    if getattr(binding, "module_action", None) is not None:
        return f"{binding.module_action} (module action), momentary"
    parts = []
    for action in _actions(binding):
        prefix = "touch " if isinstance(binding, StripBinding) and action is binding.touch else ""
        parts.append(f"{prefix}{message_text(action)} → {action.device} ch {action.channel}")
    mode = "toggle" if isinstance(binding, Binding) and binding.toggle else "momentary"
    if isinstance(binding, StripBinding):
        mode = f"{binding.style} bar"
    return ", then ".join(parts) + f", {mode}"


# --- per-control meaning --------------------------------------------------------------------------------
@dataclass(frozen=True)
class Slot:
    """One layer of one control on the current page or bank."""
    binding: Binding | StripBinding | None
    label: str
    missing: tuple[DeviceName, ...] = ()

    @property
    def empty(self) -> bool:
        return self.binding is None


EMPTY = Slot(None, "")


@dataclass(frozen=True)
class ControlMeaning:
    control: ControlId
    role: ControlRole
    display: str
    base: Slot
    shift: Slot
    layer: Layer
    reachable: Reachability

    @property
    def current(self) -> Slot:
        return self.shift if self.layer is Layer.SHIFT else self.base

    @property
    def label(self) -> str:
        return self.current.label

    @property
    def empty(self) -> bool:
        return self.current.empty

    @property
    def toggle(self) -> bool:
        binding = self.current.binding
        return isinstance(binding, Binding) and binding.toggle


@dataclass(frozen=True)
class NavSlot:
    number: int
    name: str | None
    defined: bool
    current: bool
    word: str = "Page"

    @property
    def display(self) -> str:
        """The name, 'Page N' for an unnamed defined slot (d80), '' for an empty one."""
        return self.name or (f"{self.word} {self.number}" if self.defined else "")


@dataclass(frozen=True)
class SurfaceMeaning:
    nav: NavState
    layout_name: str | None
    controls: dict[ControlId, ControlMeaning]
    pages: tuple[NavSlot, ...]
    banks: tuple[NavSlot, ...]
    oled_idle: OledText

    def __getitem__(self, control: ControlId) -> ControlMeaning:
        return self.controls[control]


def _slot(binding, missing: frozenset) -> Slot:
    if binding is None:
        return EMPTY
    absent = tuple(dict.fromkeys(a.device for a in _actions(binding) if a.device in missing))
    return Slot(binding, binding_label(binding, missing), absent)


def _nav_pages(layout: Layout | None, nav: NavState) -> tuple[NavSlot, ...]:
    pages = layout.pages if layout else {}
    return tuple(NavSlot(n, pages[n].name if n in pages else None, n in pages and not pages[n].empty,
                         n == nav.page and n in pages) for n in range(1, MAX_PAGES + 1))


def _nav_banks(layout: Layout | None, nav: NavState) -> tuple[NavSlot, ...]:
    banks = layout.banks if layout else {}
    return tuple(NavSlot(n, banks[n].name if n in banks else None, n in banks and any(banks[n].layers.values()),
                         n == nav.bank and n in banks, "Bank") for n in range(1, MAX_BANKS + 1))


def idle_oled(layout: Layout | None, nav: NavState) -> OledText:
    """Row 0 the layout name, row 1 'P<n> <page> | B<n> <bank>' (contract d108)."""
    if layout is None:
        return OledText.no_layout()
    page, bank = layout.page(nav.page), layout.bank(nav.bank)
    return OledText.idle(layout.display_name, nav.page if page else None, page.name if page else None,
                         nav.bank if bank else None, bank.name if bank else None)


def resolve(layout: Layout | None, nav: NavState, missing: frozenset = frozenset()) -> SurfaceMeaning:
    """What every SURFACE control means now, on both layers; missing names devices whose port is absent."""
    missing = frozenset(missing)
    page = layout.page(nav.page) if layout else None
    bank = layout.bank(nav.bank) if layout else None
    pages, banks = _nav_pages(layout, nav), _nav_banks(layout, nav)
    controls = {}
    for item in SURFACE:
        control, base, shift = item.id, EMPTY, EMPTY
        if isinstance(control, Strip) and bank:
            base, shift = (_slot(bank.binding(layer, control), missing) for layer in Layer)
        elif isinstance(control, StripTouch) and bank:
            strip = Strip(control.n)
            base, shift = (_slot(b, missing) if b and b.touch else EMPTY
                           for b in (bank.binding(layer, strip) for layer in Layer))
        elif isinstance(control, SceneButton):
            slot = pages[control.n - 1]
            base = shift = Slot(None, slot.display)
        elif isinstance(control, StripModeButton):
            base = shift = Slot(None, banks[control.n - 1].display)
        elif isinstance(control, Shift):
            base = shift = Slot(None, "Shift")
        elif isinstance(control, DeviceLocal):
            base = shift = Slot(None, f"{item.display} (unit)")
        elif item.role is ControlRole.BINDABLE and page:
            base, shift = (_slot(page.binding(layer, control), missing) for layer in Layer)
        controls[control] = ControlMeaning(control, item.role, item.display, base, shift, nav.layer,
                                           item.shift_reach)
    return SurfaceMeaning(nav, layout.display_name if layout else None, controls, pages, banks,
                          idle_oled(layout, nav))


# --- where else, card, overview -------------------------------------------------------------------------
@dataclass(frozen=True)
class Elsewhere:
    page: int | None
    bank: int | None
    layer: Layer
    binding: Binding | StripBinding

    @property
    def text(self) -> str:
        where = f"Page {self.page}" if self.page is not None else f"Bank {self.bank}"
        if self.layer is Layer.SHIFT:
            where += " Shift"
        if getattr(self.binding, "module_action", None) is not None:
            return f"{where}: {self.binding.label or self.binding.module_action}"
        return f"{where}: {self.binding.label or message_text(_main_action(self.binding))}"


def _bound_at(layout: Layout, control: ControlId):
    """Every (location, binding) of a control in a layout, pages/banks in order, base before Shift."""
    if isinstance(control, (Strip, StripTouch)):
        strip = Strip(control.n)
        for bank in sorted(layout.banks.values(), key=lambda b: b.number):
            for layer in Layer:
                binding = bank.binding(layer, strip)
                if binding is not None and (isinstance(control, Strip) or binding.touch):
                    yield BankLocation(bank.number, layer, strip), binding
        return
    for page in sorted(layout.pages.values(), key=lambda p: p.number):
        for layer in Layer:
            binding = page.binding(layer, control)
            if binding is not None:
                yield PageLocation(page.number, layer, control), binding


def elsewhere(layout: Layout, control: ControlId, nav: NavState | None = None) -> tuple[Elsewhere, ...]:
    """Where else the control is bound differently from the current page (or bank), both layers."""
    found = []
    strips = isinstance(control, (Strip, StripTouch))
    here = (layout.bank(nav.bank) if strips else layout.page(nav.page)) if nav else None
    for location, binding in _bound_at(layout, control):
        number = location.bank if strips else location.page
        if here is not None and number == here.number:
            continue
        current = here.binding(location.layer, Strip(control.n) if strips else control) if here else None
        if current == binding:
            continue
        found.append(Elsewhere(None if strips else number, number if strips else None, location.layer, binding))
    return tuple(found)


@dataclass(frozen=True)
class ControlCard:
    control: ControlId
    display: str
    role: ControlRole
    base: str | None
    shift: str | None
    base_binding: Binding | StripBinding | None
    shift_binding: Binding | StripBinding | None
    feedback: str | None
    port_status: tuple[str, ...]
    elsewhere: tuple[Elsewhere, ...]
    reachable: Reachability

    def lines(self) -> list[str]:
        out = [f"Base: {self.base or 'empty'}", f"Shift: {self.shift or 'empty'}"]
        out += list(self.port_status) + [e.text for e in self.elsewhere]
        return out


def _feedback_text(binding) -> str | None:
    rule = getattr(binding, "feedback", None)
    if rule is None:
        return None
    channel = f" ch {rule.channel}" if rule.channel else ""
    return f"{rule.kind} {rule.number}{channel} from {rule.device}"


def card(layout: Layout | None, nav: NavState, control: ControlId,
         missing: frozenset = frozenset()) -> ControlCard:
    """Everything about one control in one step: both layers, mode, feedback, ports, elsewhere (A129)."""
    meaning = resolve(layout, nav, missing)[control]
    base, shift = meaning.base.binding, meaning.shift.binding
    devices = []
    for binding in (base, shift):
        if binding is not None:
            devices += [a.device for a in _actions(binding)]
    ports = tuple(f"{d} {'missing' if d in missing else 'connected'}" for d in dict.fromkeys(devices))
    return ControlCard(
        control, meaning.display, meaning.role,
        binding_detail(base) if base else None, binding_detail(shift) if shift else None, base, shift,
        _feedback_text(meaning.current.binding), ports,
        elsewhere(layout, control, nav) if layout and meaning.role is ControlRole.BINDABLE else (),
        entry(control).shift_reach)


@dataclass(frozen=True)
class Cell:
    label: str
    colour: int | None


@dataclass(frozen=True)
class PageOverview:
    number: int
    name: str | None
    defined: bool
    base: dict[ControlId, Cell]
    shift: dict[ControlId, Cell]


@dataclass(frozen=True)
class BankOverview:
    number: int
    name: str | None
    defined: bool
    base: dict[Strip, Cell]
    shift: dict[Strip, Cell]


@dataclass(frozen=True)
class Overview:
    layout_name: str | None
    pages: tuple[PageOverview, ...]
    banks: tuple[BankOverview, ...]


def _cells(bindings: dict) -> dict:
    return {c: Cell(binding_label(b), (b.colour.index if b.colour else None)) for c, b in bindings.items()}


def overview(layout: Layout | None) -> Overview:
    """Every page as a grid of labels and colours and every bank as a strip set, both layers (5a.9)."""
    if layout is None:
        return Overview(None, (), ())
    pages = []
    for n in range(1, MAX_PAGES + 1):
        page: Page | None = layout.page(n)
        pages.append(PageOverview(n, page.name if page else None, bool(page and not page.empty),
                                  _cells(page.layers[Layer.BASE]) if page else {},
                                  _cells(page.layers[Layer.SHIFT]) if page else {}))
    banks = []
    for n in range(1, MAX_BANKS + 1):
        bank: Bank | None = layout.bank(n)
        banks.append(BankOverview(n, bank.name if bank else None, bool(bank and any(bank.layers.values())),
                                  _cells(bank.layers[Layer.BASE]) if bank else {},
                                  _cells(bank.layers[Layer.SHIFT]) if bank else {}))
    return Overview(layout.display_name, tuple(pages), tuple(banks))
