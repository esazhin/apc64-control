"""HostSurface: the aggregate root of the host's surface. handle(input) → [Effect], pure and deterministic.

It turns presses, releases, strip moves, encoder turns, view reports, feedback, navigation and layout
swaps into the MIDI to send, the LEDs and OLED to show, activity and play events (contract inv1–inv5,
inv8, inv10). After every input it compares the desired frame with what it last emitted and emits only
the differences; a return to Session view, a Redraw and a swap emit what is needed to repaint.
"""
from .controls import (
    ControlId, DeviceLocal, Encoder, EncoderPress, PadPos, SceneButton, Shift, Strip, StripModeButton, StripTouch,
)
from .effects import (
    Activity, ActivityEntry, ActivityResult, CallModule, CatalogUpdate, EncoderTurn, Effect, FeedbackMessage,
    InputSource, Led, LayoutSwap, Oled, Origin, Play, PlayEvent, Press, Redraw, Release, RequestLayout,
    ScheduleAfter, SelectBank, SelectPage, Send, SetPageShift, SetResting, ShowTransient, StripBar, StripMove, Tick,
    UnitView, ViewReport,
)
from .layout import (
    BankLocation, BankNo, Binding, ControlEvent, Layer, Layout, LayoutCatalog, MessageKind, NavState, PageLocation,
    PageNo, StripBinding,
)
from .leds import BAR_OFF, IDLE, LED_CONTROLS, LED_OFF, ON, LedFrame, LedState, StripBarState, look, nav_look
from .midi import ControlChange, NoteOff, NoteOn, Value14
from .oled import TRANSIENT_SECONDS, OledText
from .palette import WHITE
from .resolver import SurfaceMeaning, binding_label, idle_oled, resolve
from .surface_parts import (
    BrowseCursor, EncoderDial, FeedbackBook, Navigator, PressLedger, PressToken, StripPositions, ToggleBook,
    position_message, press_message, release_message, toggle_message,
)

OLED_TICK = "oled"


class HostSurface:
    def __init__(self):
        self.layout: Layout | None = None
        self.catalog = LayoutCatalog()
        self.view = UnitView.SESSION
        self._nav = Navigator()
        self._toggles = ToggleBook()
        self._feedback = FeedbackBook()
        self._presses = PressLedger()
        self._dial = EncoderDial()
        self._browse = BrowseCursor()
        self._strips = StripPositions()
        self._index = None
        self._transient: OledText | None = None
        self._resting: OledText | None = None     # a module's resting text (contract 2 s2.c8)
        self._oled_seq = 0
        self._shown: LedFrame | None = None       # what the unit was last told
        self._shown_oled: OledText | None = None

    # --- read side ------------------------------------------------------------------------------------
    @property
    def nav(self) -> NavState:
        return self._nav.state

    def meaning(self, missing=frozenset()) -> SurfaceMeaning:
        return resolve(self.layout, self.nav, missing)

    def toggled(self, location: PageLocation) -> bool:
        return self.layout is not None and self._toggles.get(self.layout.id, location)

    def frame(self) -> LedFrame:
        """The full desired surface for the current layout, page, bank, layer and states."""
        looks: dict[ControlId, LedState] = {}
        layout, nav = self.layout, self.nav
        page = layout.page(nav.page) if layout else None
        for control in LED_CONTROLS:
            if isinstance(control, SceneButton):
                defined = bool(layout and layout.page(control.n) and not layout.page(control.n).empty)
                looks[control] = nav_look(page is not None and control.n == nav.page, defined)
            elif isinstance(control, StripModeButton):
                bank = layout.bank(control.n) if layout else None
                defined = bool(bank and any(bank.layers.values()))
                looks[control] = nav_look(defined and control.n == nav.bank, defined)
            elif isinstance(control, Shift):
                looks[control] = LedState(WHITE, ON if nav.shift else IDLE) if layout else LED_OFF
            elif page is not None:
                location = PageLocation(nav.page, nav.layer, control)
                looks[control] = self._look(page.binding(nav.layer, control), location)
        bars = {strip: self._bar(strip) for strip in (Strip(n) for n in range(1, 9))}
        return LedFrame.for_state(looks, bars)

    def oled(self) -> OledText:
        if self._browse.active:
            return OledText.transient(self.catalog.name_of(self._browse.cursor) or self._browse.cursor, "Load: press")
        return self._transient or self._resting or idle_oled(self.layout, self.nav)

    def strip_positions(self):
        return self._strips.positions()

    def restore_positions(self, positions) -> None:
        """Remembered strip positions (from the last run) come back as last touches; nothing is sent (q6)."""
        for (layout, bank, strip), value in dict(positions).items():
            self._strips.touch(layout, BankNo(bank), Strip(strip.n) if isinstance(strip, Strip) else Strip(strip),
                               Value14(value))

    def _look(self, binding: Binding | None, location: PageLocation) -> LedState:
        if binding is None:
            return LED_OFF
        colour = binding.look_colour
        if binding.feedback is not None:
            value = self._feedback.get(self.layout.id, location)
            if value is not None:
                rule = binding.feedback
                exact = dict(rule.colours).get(value)
                if exact is not None:
                    return LedState(exact, ON)
                if value == 0:
                    return LedState(rule.off_colour, ON) if rule.off_colour else look(colour, False)
                return LedState(rule.on_colour or colour, ON)
        if binding.toggle:
            return look(colour, self._toggles.get(self.layout.id, location))
        return look(colour, self._presses.holds(self.layout.id, location))

    def _strip_binding(self, strip: Strip, layer: Layer) -> StripBinding | None:
        bank = self.layout.bank(self.nav.bank) if self.layout else None
        return bank.binding(layer, strip) if bank else None

    def _bar(self, strip: Strip) -> StripBarState:
        """The bar shows its feedback value if a rule exists, otherwise the last touch (d86)."""
        layer = Layer.BASE if self._strip_binding(strip, Layer.BASE) else Layer.SHIFT
        binding = self._strip_binding(strip, layer)
        if binding is None:
            return BAR_OFF
        value = self._strips.last(self.layout.id, self.nav.bank, strip)
        if binding.feedback is not None:
            received = self._feedback.get(self.layout.id, BankLocation(self.nav.bank, layer, strip))
            value = Value14.from7(received) if received is not None else Value14(0)
        return StripBarState(value, binding.colour, binding.style)

    # --- write side -----------------------------------------------------------------------------------
    def handle(self, event) -> list[Effect]:
        effects: list[Effect] = []
        full = False
        match event:
            case Press():
                self._on_press(event, effects)
            case Release():
                self._on_release(event, effects)
            case StripMove():
                self._on_strip(event, effects)
            case EncoderTurn():
                self._on_turn(event, effects)
            case ViewReport(view=view):
                self.view = view   # the unit wipes Session view on every mode change: repaint on its report (p6)
                full = view.host_drawn
                effects.append(Play(PlayEvent("view", view=view)))
            case SelectPage(page=page, source=source):
                self._select_page(PageNo(page), source, effects)
            case SelectBank(bank=bank, source=source):
                self._select_bank(BankNo(bank), source, effects)
            case SetPageShift(held=held):
                self._set_shift(page_shift=held, effects=effects)
            case FeedbackMessage():
                self._on_feedback(event)
            case LayoutSwap():
                self._swap(event, effects)
                full = True
            case CatalogUpdate(catalog=catalog):
                self.catalog = catalog
            case Redraw():
                full = True
            case SetResting(text=text):
                self._resting = text
            case ShowTransient(text=text):
                self._show(text, effects)
            case Tick(kind=kind, seq=seq):
                if kind == OLED_TICK and seq == self._oled_seq:
                    self._transient = None
            case _:
                raise TypeError(f"HostSurface cannot handle {event!r}")
        return effects + self._flush(full)

    def _flush(self, full: bool) -> list[Effect]:
        """Led/StripBar/Oled effects for what differs from what the unit was last told."""
        frame, oled = self.frame(), self.oled()
        previous = None if full else self._shown
        out: list[Effect] = []
        for control, state in frame.led_changes(previous):
            if isinstance(control, PadPos) and not self.view.host_drawn:
                continue   # outside Session view the grid is the unit's (PROTOCOL-SPEC §4.6)
            out.append(Led(control, state))
        out += [StripBar(strip, state) for strip, state in frame.bar_changes(previous)]
        if full or oled != self._shown_oled:
            out.append(Oled(oled))
        self._shown, self._shown_oled = frame, oled
        if not self.view.host_drawn:   # the grid will be repainted in full on the return to Session
            self._shown = LedFrame({c: s for c, s in frame.leds.items() if not isinstance(c, PadPos)}, frame.bars)
        return out

    def _show(self, text: OledText, effects: list[Effect]):
        """Show a name for about 2 s, then the idle rows again."""
        self._oled_seq += 1
        self._transient = text
        effects.append(ScheduleAfter(TRANSIENT_SECONDS, Tick(OLED_TICK, self._oled_seq)))

    # presses ------------------------------------------------------------------------------------------
    def _on_press(self, press: Press, effects: list[Effect]):
        control = press.control
        if isinstance(control, Shift):
            self._set_shift(unit_shift=True, effects=effects)
        elif isinstance(control, DeviceLocal):
            return
        elif isinstance(control, SceneButton):
            if self.nav.shift:   # Shift + scene does nothing: the unit may switch itself to Project mode (d88)
                effects.append(Play(PlayEvent("press", press.source, self.view, control, reason="Shift + scene unused")))
                return
            self._select_page(PageNo(control.n), press.source, effects)
        elif isinstance(control, StripModeButton):
            self._select_bank(BankNo(control.n), press.source, effects)
        elif isinstance(control, EncoderPress) and self.nav.shift:
            chosen = self._browse.stop()   # Shift + encoder press loads the layout shown (d105)
            if chosen is not None and (self.layout is None or chosen != self.layout.id):
                effects.append(RequestLayout(chosen))
        elif isinstance(control, StripTouch):
            self._on_touch(press, effects)
        else:
            self._on_bound_press(press, effects)

    def _on_bound_press(self, press: Press, effects: list[Effect]):
        control, nav = press.control, self.nav
        page = self.layout.page(nav.page) if self.layout else None
        binding = page.binding(nav.layer, control) if page else None
        location = PageLocation(nav.page, nav.layer, control)
        self._presses.press(PressToken(control, binding, nav.layout, location))
        if binding is None:
            self._unbound(control, press.source, effects, "press", press.velocity)
            return
        if binding.is_module_action:   # contract 2: the module's action, base layer only (s2.c7)
            effects.append(CallModule(binding.module_action, ControlEvent.pressed(), control))
            effects.append(Play(PlayEvent("press", press.source, self.view, control, value=1, velocity=press.velocity,
                                          reason=f"module {binding.module_action}")))
            return
        if binding.toggle:   # each press flips the latch; the release does nothing (d92)
            on = not self._toggles.get(self.layout.id, location)
            self._toggles.set(self.layout.id, location, on)
            messages, kind = [toggle_message(a, on) for a in binding.actions], "toggle"
        else:
            on = True
            messages, kind = [press_message(a, press.velocity) for a in binding.actions], "press"
        self._send(binding.actions, messages, Origin(control, kind=kind), effects)
        effects.append(Play(PlayEvent("press", press.source, self.view, control, value=int(on),
                                      velocity=press.velocity, sent=_described(messages))))

    def _on_release(self, release: Release, effects: list[Effect]):
        control = release.control
        if isinstance(control, Shift):
            self._set_shift(unit_shift=False, effects=effects)
            return
        token = self._presses.release(control)
        if token is None:
            return
        if token.touch is not None:
            message = release_message(token.touch)
            self._send((token.touch,), [message], Origin(control, kind="touch"), effects)
            effects.append(Play(PlayEvent("release", release.source, self.view, control, sent=_described([message]))))
            return
        binding = token.binding
        if not isinstance(binding, Binding):
            return
        messages = [] if binding.toggle else [release_message(a) for a in binding.actions]
        self._send(binding.actions, messages, Origin(control, kind="release"), effects)
        effects.append(Play(PlayEvent("release", release.source, self.view, control, sent=_described(messages))))

    def _on_touch(self, press: Press, effects: list[Effect]):
        control, nav = press.control, self.nav
        binding = self._strip_binding(Strip(control.n), nav.layer)
        if binding is None:
            self._presses.press(PressToken(control, None, nav.layout, None))
            self._unbound(Strip(control.n), press.source, effects, "touch", press.velocity)
            return
        if binding.touch is None:
            return
        self._presses.press(PressToken(control, binding, nav.layout, None, binding.touch))
        message = press_message(binding.touch, press.velocity)
        self._send((binding.touch,), [message], Origin(control, kind="touch"), effects)
        effects.append(Play(PlayEvent("press", press.source, self.view, control, velocity=press.velocity,
                                      sent=_described([message]))))

    def _unbound(self, control: ControlId, source: InputSource, effects: list[Effect], kind: str, velocity=None):
        effects.append(Activity(ActivityEntry(str(control), ActivityResult.UNBOUND)))
        effects.append(Play(PlayEvent(kind, source, self.view, control, velocity=velocity, reason="unbound")))

    def _send(self, actions, messages, origin: Origin, effects: list[Effect]):
        for action, message in zip(actions, messages):
            if message is not None:
                effects.append(Send(action.device, self.layout.devices[action.device].pattern, message, origin))

    # strips and encoder -------------------------------------------------------------------------------
    def _on_strip(self, move: StripMove, effects: list[Effect]):
        strip, nav = move.strip, self.nav
        binding = self._strip_binding(strip, nav.layer)
        if self.layout is not None:
            self._strips.touch(self.layout.id, nav.bank, strip, move.value)
        if binding is None:   # no activity entry per move: an unbound touch already listed it (d53)
            effects.append(Play(PlayEvent("move", move.source, self.view, strip, value=move.value, reason="unbound")))
            return
        message = position_message(binding.position, move.value)
        key = (self.layout.id, nav.bank, nav.layer, strip)
        sent = []
        if self._strips.changed(key, message):   # an unchanged value is not sent again (d55)
            self._send((binding.position,), [message], Origin(strip, kind="move"), effects)
            sent = [message]
        effects.append(Play(PlayEvent("move", move.source, self.view, strip, value=move.value, sent=_described(sent))))

    def _on_turn(self, turn: EncoderTurn, effects: list[Effect]):
        if self.nav.shift:   # Shift + encoder browses layout names on the OLED (inv5)
            self._browse.turn(self.catalog, self.layout.id if self.layout else None, turn.steps)
            effects.append(Play(PlayEvent("turn", turn.source, self.view, value=turn.steps, reason="browse")))
            return
        nav = self.nav
        page = self.layout.page(nav.page) if self.layout else None
        binding = page.encoder if page else None
        if binding is None:
            self._unbound(Encoder(), turn.source, effects, "turn", None)
            return
        if binding.is_module_action:   # contract 2: the module shows its own resting text, no host transient
            effects.append(CallModule(binding.module_action, ControlEvent.turn(turn.steps), Encoder()))
            effects.append(Play(PlayEvent("turn", turn.source, self.view, Encoder(), value=turn.steps,
                                          reason=f"module {binding.module_action}")))
            return
        value, changed = self._dial.turn(self.layout.id, nav.page, turn.steps)
        action = binding.actions[0]
        message = ControlChange(action.channel, action.number, value)
        if changed:
            self._send((action,), [message], Origin(Encoder(), kind="turn"), effects)
        self._show(OledText.transient(binding_label(binding), str(value)), effects)
        effects.append(Play(PlayEvent("turn", turn.source, self.view, Encoder(), value=value,
                                      sent=_described([message] if changed else []))))

    # navigation ---------------------------------------------------------------------------------------
    def _select_page(self, number: PageNo, source: InputSource, effects: list[Effect]):
        if self.layout is None:
            return
        page = self.layout.page(number)
        if page is None or page.empty:   # an empty page keeps the current one (d82)
            self._show(OledText.transient(f"Page {number} empty"), effects)
            return
        self._nav.page = number
        self._show(OledText.transient(page.display_name, f"Page {number}"), effects)
        effects.append(Play(PlayEvent("nav", source, self.view, value=int(number), reason="page")))

    def _select_bank(self, number: BankNo, source: InputSource, effects: list[Effect]):
        if self.layout is None:
            return
        bank = self.layout.bank(number)
        if bank is None or not any(bank.layers.values()):   # an empty bank keeps the current one (d85)
            self._show(OledText.transient(f"Bank {number} empty"), effects)
            return
        self._nav.bank = number
        self._show(OledText.transient(bank.display_name, f"Bank {number}"), effects)
        effects.append(Play(PlayEvent("nav", source, self.view, value=int(number), reason="bank")))

    def _set_shift(self, effects: list[Effect], unit_shift: bool | None = None, page_shift: bool | None = None):
        before = self.nav.shift
        if unit_shift is not None:
            self._nav.unit_shift = unit_shift
        if page_shift is not None:
            self._nav.page_shift = page_shift
        if before and not self.nav.shift and self._browse.active:   # letting go of Shift cancels the browse
            self._browse.stop()
        if before != self.nav.shift:
            effects.append(Play(PlayEvent("shift", value=int(self.nav.shift))))

    # feedback -----------------------------------------------------------------------------------------
    def _on_feedback(self, event: FeedbackMessage):
        if self.layout is None or self._index is None:
            return
        message = event.message
        if isinstance(message, NoteOn):
            kind, number, value = MessageKind.NOTE, message.note, int(message.velocity)
        elif isinstance(message, NoteOff):
            kind, number, value = MessageKind.NOTE, message.note, 0
        elif isinstance(message, ControlChange):
            kind, number, value = MessageKind.CC, message.control, int(message.value)
        else:
            return
        for device in (d.name for d in self.layout.devices.values() if d.pattern.matches(event.port)):
            for rule, location in self._index.lookup(device, kind, number, message.channel):
                self._feedback.put(self.layout.id, location, value)
                if isinstance(location, PageLocation):
                    page = self.layout.page(location.page)
                    binding = page.binding(location.layer, location.control)
                    if binding is not None and binding.toggle:   # feedback also sets the toggle (d103)
                        self._toggles.set(self.layout.id, location, value != 0)

    # layouts ------------------------------------------------------------------------------------------
    def _swap(self, swap: LayoutSwap, effects: list[Effect]):
        old, new = self.layout, swap.layout
        self._browse.stop()
        self.layout = new
        self._index = new.feedback_index() if new else None
        if new is None:
            self._nav.layout = None
            self._transient = None
            return
        if old is not None and old.id == new.id:   # hot reload: keep where we are (d96)
            self._toggles.carry(old, new)
            if new.page(self._nav.page) is None:
                self._nav.page = _first(new.pages)
            if new.bank(self._nav.bank) is None:
                self._nav.bank = _first(new.banks)
            effects.append(Play(PlayEvent("layout", value=None, reason=f"reloaded {new.id}")))
            return
        self._nav.layout = new.id
        self._nav.page = PageNo(swap.page) if swap.page and new.page(swap.page) else _first(new.pages)
        self._nav.bank = BankNo(swap.bank) if swap.bank and new.bank(swap.bank) else _first(new.banks)
        self._show(OledText.transient(new.display_name, "Layout"), effects)
        effects.append(Play(PlayEvent("layout", reason=f"loaded {new.id}")))


def _first(numbered: dict) -> int:
    """Page/bank 1 when it exists, otherwise the lowest defined one (q6), otherwise 1."""
    return PageNo(1) if 1 in numbered or not numbered else min(numbered)


def _described(messages) -> tuple[str, ...]:
    return tuple(m.describe() for m in messages if m is not None)
