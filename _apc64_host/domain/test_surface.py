"""HostSurface against the acceptance values of contract §4.2 (T5)."""
import random

from _apc64_host.domain.conftest import (
    RED, bank, cc, encoder_cc, feedback, layout, mix_strips, note, page, strip_bend, strip_cc,
    toggle_cc,
)
from _apc64_host.domain.controls import (
    PadPos, EncoderPress, ModeButton, ModeName, SceneButton, Shift, Strip,
    StripModeButton, StripTouch, TrackButton, Transport, TransportName, DeviceLocal, ViewName, Encoder,
)
from _apc64_host.domain.effects import (
    Activity, ActivityResult, CatalogUpdate, EncoderTurn, FeedbackMessage, InputSource, Led, LayoutSwap, Oled,
    Play, Press, Redraw, Release, RequestLayout, ScheduleAfter, SelectBank, SelectPage, Send, SetPageShift,
    StripBar, StripMove, Tick, UnitView, ViewReport,
)
from _apc64_host.domain.layout import LayoutCatalog
from _apc64_host.domain.leds import LED_OFF, LedBehaviour, LedState
from _apc64_host.domain.midi import ControlChange, NoteOff, NoteOn, PitchBend, ProgramChange, Value14
from _apc64_host.domain.palette import parse_colour
from _apc64_host.domain.surface import HostSurface

PLAY = Transport(TransportName.PLAY)
R1C1, R1C2, R8C8 = PadPos(1, 1), PadPos(1, 2), PadPos(8, 8)
T1, T2 = TrackButton(1), TrackButton(2)
GREEN, DIM_WHITE = parse_colour("green"), parse_colour("dim white")


def jam(**changes):
    pages = changes.pop("pages", None) or [
        page(1, "Drums", {R1C1: note(36, colour=RED), R1C2: note(37), PLAY: cc(118), T1: toggle_cc(20),
                          T2: cc(21), Encoder(): encoder_cc(30)},
             {R1C1: note(48), PLAY: cc(119)}),
        page(2, "Keys", {R1C1: note(50)}),
    ]
    banks = changes.pop("banks", None) or [bank(1, "Mix", mix_strips()), bank(5, "FX", {Strip(1): strip_cc(40)})]
    return layout(pages=pages, banks=banks, **changes)


def live(lay=None, **swap):
    surface = HostSurface()
    surface.handle(LayoutSwap(lay or jam(), **swap))
    surface.handle(Tick("oled", 1))   # let the load name time out
    return surface


def sends(effects):
    return [(e.device, e.message) for e in effects if isinstance(e, Send)]


def leds(effects):
    return {e.control: e.state for e in effects if isinstance(e, Led)}


def oleds(effects):
    return [e.text.rows for e in effects if isinstance(e, Oled)]


def tap(surface, control, velocity=127):
    return surface.handle(Press(control, velocity)) + surface.handle(Release(control))


# --- presses ----------------------------------------------------------------------------------------------
def test_a_session_pad_sends_note_on_127_then_note_off():   # A58
    surface = live()
    assert sends(surface.handle(Press(R1C1, 127))) == [("mpc", NoteOn(10, 36, 127))]
    assert sends(surface.handle(Release(R1C1))) == [("mpc", NoteOff(10, 36))]


def test_a_fixed_velocity_binding_overrides_the_reported_velocity():   # q4
    surface = live(jam(pages=[page(1, base={R1C1: note(36, velocity=100)})]))
    assert sends(surface.handle(Press(R1C1, 127))) == [("mpc", NoteOn(10, 36, 100))]


def test_play_sends_its_cc_and_holding_shift_sends_the_shift_binding_instead():   # A59, A64
    surface = live()
    assert sends(surface.handle(Press(PLAY))) == [("mpc", ControlChange(1, 118, 127))]
    surface.handle(Release(PLAY))
    surface.handle(Press(Shift()))
    assert sends(surface.handle(Press(PLAY))) == [("mpc", ControlChange(1, 119, 127))]
    assert surface.meaning()[PLAY].label == "CC119 → mpc"


def test_shift_pad_sends_its_shift_note():   # A67
    surface = live()
    surface.handle(Press(Shift()))
    assert sends(surface.handle(Press(R1C1))) == [("mpc", NoteOn(10, 48, 127))]


def test_the_page_shift_counts_like_the_unit_shift():   # A88, d90
    surface = live()
    surface.handle(SetPageShift(True))
    assert surface.nav.shift and surface.meaning()[R1C1].label == "Note 48 → mpc"
    assert sends(surface.handle(Press(PLAY))) == [("mpc", ControlChange(1, 119, 127))]
    surface.handle(SetPageShift(False))
    assert not surface.nav.shift


def test_a_shifted_control_without_a_shift_binding_sends_nothing():   # A87, d89
    surface = live()
    surface.handle(Press(Shift()))
    effects = surface.handle(Press(T2))
    assert sends(effects) == []
    assert surface.meaning()[T2].empty


def test_simultaneous_presses_each_send():   # A68
    surface = live()
    effects = surface.handle(Press(R1C1)) + surface.handle(Press(R1C2))
    assert sends(effects) == [("mpc", NoteOn(10, 36, 127)), ("mpc", NoteOn(10, 37, 127))]


def test_a_release_goes_to_the_binding_that_got_the_press():   # A71, d50
    surface = live()
    effects = surface.handle(Press(R1C1)) + surface.handle(Press(SceneButton(2))) + surface.handle(Release(R1C1))
    assert sends(effects) == [("mpc", NoteOn(10, 36, 127)), ("mpc", NoteOff(10, 36))]
    assert surface.nav.page == 2


def test_several_messages_go_out_in_the_written_order():   # A72
    from _apc64_host.domain.layout import Action, Binding, Fixed, MessageKind
    both = Binding((Action("mpc", MessageKind.CC, 1, 20, Fixed(127)), Action("mpc", MessageKind.PROGRAM, 1, 5)))
    surface = live(jam(pages=[page(1, base={T1: both})]))
    assert sends(surface.handle(Press(T1))) == [("mpc", ControlChange(1, 20, 127)), ("mpc", ProgramChange(1, 5))]
    assert sends(surface.handle(Release(T1))) == [("mpc", ControlChange(1, 20, 0))]


def test_an_unbound_control_sends_nothing_shows_empty_and_is_listed_unbound():   # A74, inv2
    surface = live()
    effects = surface.handle(Press(R8C8))
    assert sends(effects) == []
    entries = [e.entry for e in effects if isinstance(e, Activity)]
    assert [e.text() for e in entries] == ["pad r8c8: unbound"] and entries[0].result is ActivityResult.UNBOUND
    assert surface.meaning()[R8C8].empty and surface.frame().leds[R8C8] == LED_OFF
    assert sends(surface.handle(Release(R8C8))) == []


def test_a_latching_toggle_flips_on_each_press_and_ignores_releases():   # A75
    surface = live()
    first = tap(surface, T1)
    assert sends(first) == [("mpc", ControlChange(1, 20, 127))]
    assert leds(first)[T1].behaviour is LedBehaviour.FULL
    second = tap(surface, T1)
    assert sends(second) == [("mpc", ControlChange(1, 20, 0))]
    assert leds(second)[T1].behaviour is LedBehaviour.BRIGHT_25


def test_momentary_leds_light_while_pressed_and_dim_when_idle():   # q9
    surface = live()
    assert surface.frame().leds[R1C1] == LedState(RED, LedBehaviour.BRIGHT_25)
    assert leds(surface.handle(Press(R1C1)))[R1C1] == LedState(RED, LedBehaviour.FULL)
    assert leds(surface.handle(Release(R1C1)))[R1C1] == LedState(RED, LedBehaviour.BRIGHT_25)


def test_toggles_keep_their_state_per_page():   # A98, d83
    surface = live()
    tap(surface, T1)
    surface.handle(Press(SceneButton(2)))
    assert surface.frame().leds[T1] == LED_OFF   # page 2 does not bind track 1
    effects = surface.handle(Press(SceneButton(1)))
    assert leds(effects)[T1].behaviour is LedBehaviour.FULL


def test_toggle_state_survives_a_reload_only_where_its_binding_did_not_change():   # A76, d96
    surface = live()
    tap(surface, T1)
    changed_pad = jam(pages=[page(1, "Drums", {R1C1: note(40), T1: toggle_cc(20)}), page(2, "Keys", {R1C1: note(50)})])
    surface.handle(LayoutSwap(changed_pad))
    assert surface.frame().leds[T1].behaviour is LedBehaviour.FULL
    changed_track = jam(pages=[page(1, "Drums", {R1C1: note(40), T1: toggle_cc(22)})])
    surface.handle(LayoutSwap(changed_track))
    assert surface.frame().leds[T1].behaviour is LedBehaviour.BRIGHT_25


# --- strips and encoder -----------------------------------------------------------------------------------
def test_a_strip_touch_then_slide_sends_its_touch_note_then_14_bit_pitch_bend():   # A60
    surface = live(jam(banks=[bank(1, "Mix", {Strip(3): strip_bend(2, touch_note=60)})]))
    effects = surface.handle(Press(StripTouch(3))) + surface.handle(StripMove(Strip(3), 8192))
    assert sends(effects) == [("bitwig", NoteOn(2, 60, 127)), ("bitwig", PitchBend(2, 8192))]
    assert sends(surface.handle(Release(StripTouch(3)))) == [("bitwig", NoteOff(2, 60))]


def test_a_7_bit_strip_sends_position_divided_by_128_and_no_repeat():   # A61, A73
    surface = live(jam(banks=[bank(1, "Mix", {Strip(4): strip_cc(21), Strip(2): strip_cc(22)})]))
    assert sends(surface.handle(StripMove(Strip(4), 16383))) == [("mpc", ControlChange(1, 21, 127))]
    assert sends(surface.handle(StripMove(Strip(2), 64 * 128))) == [("mpc", ControlChange(1, 22, 64))]
    assert sends(surface.handle(StripMove(Strip(2), 64 * 128 + 50))) == []


def test_a_14_bit_pair_sends_msb_and_lsb_controllers():   # d54
    from _apc64_host.domain.layout import Action, MessageKind, StripBinding, StripPosition
    from _apc64_host.domain.midi import ControlChange14
    pair = StripBinding(Action("mpc", MessageKind.CC14, 1, 20, StripPosition()))
    surface = live(jam(banks=[bank(1, base={Strip(1): pair})]))
    assert sends(surface.handle(StripMove(Strip(1), 8193))) == [("mpc", ControlChange14(1, 20, 52, 8193))]


def test_the_encoder_keeps_an_absolute_value_from_64():   # A62, A63, q2
    surface = live()
    effects = surface.handle(EncoderTurn(1))
    assert sends(effects) == [("mpc", ControlChange(1, 30, 65))]
    assert oleds(effects) == [("CC30 > mpc", "65")]
    assert sends(surface.handle(EncoderTurn(3))) == [("mpc", ControlChange(1, 30, 68))]
    other = live()
    assert sends(other.handle(EncoderTurn(3))) == [("mpc", ControlChange(1, 30, 67))]
    assert sends(other.handle(EncoderTurn(-200))) == [("mpc", ControlChange(1, 30, 0))]
    assert sends(other.handle(EncoderTurn(-1))) == []


# --- views ------------------------------------------------------------------------------------------------
def test_a_view_report_sends_no_bound_action():   # A65
    surface = live()
    effects = surface.handle(ViewReport(UnitView.NOTE))
    assert sends(effects) == [] and surface.view is UnitView.NOTE
    assert [e.event.view for e in effects if isinstance(e, Play)] == [UnitView.NOTE]
    assert surface.handle(Press(DeviceLocal(ViewName.NOTE))) == []


def test_pad_leds_stay_off_the_wire_outside_session_and_all_come_back_on_return():   # A101, inv8
    surface = live()
    surface.handle(ViewReport(UnitView.NOTE))
    tap(surface, T1)
    assert all(not isinstance(c, PadPos) for c in leds(surface.handle(Press(R1C1))))
    back = surface.handle(ViewReport(UnitView.SESSION))
    painted = leds(back)
    assert set(painted) == set(surface.frame().leds)
    assert painted[R1C1] == LedState(RED, LedBehaviour.FULL) and painted[T1].behaviour is LedBehaviour.FULL
    assert len([e for e in back if isinstance(e, StripBar)]) == 8 and oleds(back)


# --- navigation -------------------------------------------------------------------------------------------
def test_a_scene_button_selects_its_page_shows_the_name_and_sends_nothing():   # A89, inv3
    surface = live()
    effects = surface.handle(Press(SceneButton(2)))
    assert surface.nav.page == 2 and sends(effects) == []
    assert oleds(effects) == [("Keys", "Page 2")]
    assert any(isinstance(e, ScheduleAfter) and e.seconds == 2.0 for e in effects)
    frame = surface.frame()
    assert frame.leds[SceneButton(2)].behaviour is LedBehaviour.FULL
    assert frame.leds[SceneButton(1)].behaviour is LedBehaviour.BRIGHT_25
    assert all(frame.leds[SceneButton(n)] == LED_OFF for n in range(3, 9))


def test_an_empty_page_keeps_the_current_one_and_says_so():   # A90
    surface = live()
    effects = surface.handle(Press(SceneButton(5)))
    assert surface.nav.page == 1 and oleds(effects) == [("Page 5 empty", "")]


def test_an_unnamed_page_is_shown_as_page_n():   # A91
    surface = live(jam(pages=[page(1, "Drums", {R1C1: note(36)}), page(3, None, {R1C1: note(40)})]))
    assert oleds(surface.handle(Press(SceneButton(3)))) == [("Page 3", "Page 3")]
    assert surface.meaning().pages[2].display == "Page 3"


def test_strip_mode_buttons_select_banks_independently_of_pages():   # A66, A93, d84
    surface = live(jam(banks=[bank(1, "Mix", mix_strips()), bank(3, "Sends", mix_strips(30)),
                              bank(5, "FX", mix_strips(40))]))
    surface.handle(Press(SceneButton(2)))
    effects = surface.handle(Press(StripModeButton(5)))
    assert surface.nav.bank == 5 and surface.nav.page == 2 and oleds(effects) == [("FX", "Bank 5")]
    surface.handle(Press(StripModeButton(3)))
    assert surface.nav.bank == 3 and surface.nav.page == 2
    assert sends(effects) == []


def test_an_empty_bank_keeps_the_current_one_and_says_so():   # A94
    surface = live()
    effects = surface.handle(Press(StripModeButton(4)))
    assert surface.nav.bank == 1 and oleds(effects) == [("Bank 4 empty", "")]


def test_a_bank_switch_redraws_bars_at_feedback_value_or_last_touch():   # A92, d86
    with_fb = strip_cc(20, feedback=feedback("cc", 20, device="mpc"))
    surface = live(jam(banks=[bank(1, "Mix", mix_strips()), bank(2, "Two", {Strip(1): with_fb, Strip(2): strip_cc(21)})]))
    surface.handle(Press(StripModeButton(2)))
    surface.handle(StripMove(Strip(2), 4000))
    surface.handle(Press(StripModeButton(1)))
    surface.handle(FeedbackMessage("MPC Live III MIDI 1", ControlChange(1, 20, 100)))
    bars = {e.strip: e.state for e in surface.handle(Press(StripModeButton(2))) if isinstance(e, StripBar)}
    assert bars[Strip(1)].value == Value14.from7(100) and bars[Strip(2)].value == 4000


def test_shift_plus_scene_does_nothing():   # A97, d88
    surface = live()
    surface.handle(Press(Shift()))
    effects = surface.handle(Press(SceneButton(4)))
    assert surface.nav.page == 1 and sends(effects) == []


def test_page_and_bank_requests_from_the_page_use_the_same_path():   # inv22
    surface = live()
    surface.handle(SelectPage(2))
    assert surface.nav.page == 2
    surface.handle(SelectBank(5))
    assert surface.nav.bank == 5


def test_the_idle_oled_returns_after_the_name_times_out():   # A100, d108
    surface = live()
    surface.handle(Press(SceneButton(2)))
    surface.handle(Press(SceneButton(1)))
    assert surface.oled().rows == ("Drums", "Page 1")
    assert surface.handle(Tick("oled", 1)) == []          # an older tick changes nothing
    effects = surface.handle(Tick("oled", 3))
    assert oleds(effects) == [("Jam", "P1 Drums | B1")]


# --- layout browsing from the hardware --------------------------------------------------------------------
def catalog_surface():
    surface = live()
    surface.handle(CatalogUpdate(LayoutCatalog.of([("ambient", "Ambient"), ("jam", "Jam"), ("tonnetz-c", "Tonnetz C")])))
    return surface


def test_shift_and_the_encoder_browse_and_load_a_layout_by_name():   # A95, inv5
    surface = catalog_surface()
    surface.handle(Press(Shift()))
    turned = surface.handle(EncoderTurn(1))
    assert sends(turned) == [] and oleds(turned)[0][0] == "Tonnetz C"
    pressed = surface.handle(Press(EncoderPress()))
    assert [e.layout for e in pressed if isinstance(e, RequestLayout)] == ["tonnetz-c"]
    loaded = surface.handle(LayoutSwap(layout("tonnetz-c", "Tonnetz C", [page(1, base={R1C1: note(60)})])))
    assert oleds(loaded) == [("Tonnetz C", "Layout")] and surface.nav.page == 1 and surface.nav.bank == 1


def test_letting_go_of_shift_cancels_the_browse():   # A96, d107
    surface = catalog_surface()
    surface.handle(Press(Shift()))
    surface.handle(EncoderTurn(1))
    released = surface.handle(Release(Shift()))
    assert oleds(released) == [("Jam", "P1 Drums | B1")]
    assert not any(isinstance(e, RequestLayout) for e in surface.handle(Press(EncoderPress())))


def test_browsing_wraps_at_both_ends():   # d106
    surface = catalog_surface()
    surface.handle(Press(Shift()))
    assert surface.handle(EncoderTurn(-2)) and surface.oled().row0 == "Tonnetz C"


# --- feedback ---------------------------------------------------------------------------------------------
def fb_layout():
    return jam(pages=[
        page(1, "Drums", {R1C1: note(36, feedback=feedback("note", 36, on="green", off="dim white")),
                          T1: toggle_cc(20, device="bitwig", feedback=feedback("cc", 20, device="bitwig"))}),
        page(2, "Keys", {R1C1: note(50, colour=GREEN, feedback=feedback("note", 50))}),
    ])


def test_feedback_lights_a_pad_on_and_off_colours():   # A78
    surface = live(fb_layout())
    on = surface.handle(FeedbackMessage("MPC Live III MIDI 1", NoteOn(1, 36, 100)))
    assert leds(on)[R1C1] == LedState(GREEN, LedBehaviour.FULL)
    off = surface.handle(FeedbackMessage("MPC Live III MIDI 1", NoteOff(1, 36)))
    assert leds(off)[R1C1] == LedState(DIM_WHITE, LedBehaviour.FULL)


def test_feedback_sets_a_toggle_so_the_next_press_sends_the_opposite():   # A77, d103
    surface = live(fb_layout())
    tap(surface, T1)   # on
    off = surface.handle(FeedbackMessage("Bitwig Studio In", ControlChange(1, 20, 0)))
    assert leds(off)[T1].behaviour is LedBehaviour.BRIGHT_25
    assert sends(surface.handle(Press(T1))) == [("bitwig", ControlChange(1, 20, 127))]


def test_feedback_never_writes_the_oled_and_unmatched_feedback_changes_nothing():   # A79, A80, d98
    surface = live(fb_layout())
    effects = surface.handle(FeedbackMessage("Bitwig Studio In", ControlChange(1, 20, 99)))
    assert leds(effects)[T1].behaviour is LedBehaviour.FULL and oleds(effects) == []
    assert surface.handle(FeedbackMessage("MPC Live III MIDI 1", ControlChange(1, 99, 5))) == []


def test_a_feedback_burst_ends_on_the_last_value():   # A81
    surface = live(fb_layout())
    for i in range(50):
        surface.handle(FeedbackMessage("Bitwig Studio In", ControlChange(1, 20, 127 if i % 2 == 0 else 0)))
    assert surface.frame().leds[T1].behaviour is LedBehaviour.BRIGHT_25


def test_feedback_for_a_hidden_page_shows_when_that_page_appears():   # A82, d104
    surface = live(fb_layout())
    assert leds(surface.handle(FeedbackMessage("MPC Live III MIDI 1", NoteOn(1, 50, 100)))) == {}
    shown = surface.handle(Press(SceneButton(2)))
    assert leds(shown)[R1C1] == LedState(GREEN, LedBehaviour.FULL)


# --- layouts ----------------------------------------------------------------------------------------------
def test_no_layout_means_a_dark_surface_and_no_layout_on_the_oled():   # A37, d67
    surface = HostSurface()
    effects = surface.handle(LayoutSwap(None))
    assert oleds(effects) == [("No layout", "")]
    assert all(state == LED_OFF for state in leds(effects).values())
    assert sends(surface.handle(Press(R1C1))) == []


def test_a_layout_is_restored_to_a_remembered_page_and_bank():   # q6
    surface = live(jam(), page=2, bank=5)
    assert (surface.nav.page, surface.nav.bank) == (2, 5)


def test_a_redraw_repaints_everything():
    surface = live()
    effects = surface.handle(Redraw())
    assert set(leds(effects)) == set(surface.frame().leds) and oleds(effects) == [("Jam", "P1 Drums | B1")]


def test_replica_input_is_tagged_with_its_source():   # A70
    surface = live()
    effects = surface.handle(Press(R1C1, source=InputSource.REPLICA))
    assert [e.event.source for e in effects if isinstance(e, Play)] == ["replica"]
    assert sends(effects) == [("mpc", NoteOn(10, 36, 127))]


# --- determinism and LED parity ---------------------------------------------------------------------------
def _performance(seed):
    rng = random.Random(seed)
    controls = [R1C1, R1C2, R8C8, PLAY, T1, T2, Shift(), SceneButton(1), SceneButton(2), SceneButton(5),
                StripModeButton(1), StripModeButton(5), ModeButton(ModeName.MUTE)]
    events = []
    for _ in range(100):
        roll = rng.random()
        if roll < 0.55:
            control = rng.choice(controls)
            events += [Press(control, rng.randint(1, 127)), Release(control)]
        elif roll < 0.7:
            events.append(StripMove(Strip(rng.randint(1, 8)), rng.randint(0, 16383)))
        elif roll < 0.8:
            events.append(FeedbackMessage("Bitwig Studio In", ControlChange(1, 20, rng.choice([0, 127]))))
        elif roll < 0.9:
            events.append(EncoderTurn(rng.choice([-2, -1, 1, 3])))
        else:
            events.append(ViewReport(rng.choice([UnitView.SESSION, UnitView.NOTE])))
    return events + [ViewReport(UnitView.SESSION)]


def test_the_same_inputs_give_the_same_effects_and_state():   # A119, inv10
    runs = []
    for _ in range(2):
        surface = live(fb_layout())
        runs.append(([e for ev in _performance(7) for e in surface.handle(ev)], surface.frame(), surface.oled()))
    assert runs[0] == runs[1]


def test_the_leds_sent_always_add_up_to_the_frame():   # A128, d178
    surface = HostSurface()
    unit = {}
    for event in [LayoutSwap(fb_layout())] + _performance(11):
        for effect in surface.handle(event):
            if isinstance(effect, Led):
                unit[effect.control] = effect.state
    assert surface.view is UnitView.SESSION
    assert unit == surface.frame().leds


def test_remembered_strip_positions_come_back_without_sending_anything():   # q6, s53 (added with contract 2)
    surface = HostSurface()
    surface.restore_positions({("jam", 1, Strip(3)): Value14(5000), ("other", 2, Strip(1)): Value14(9)})
    effects = surface.handle(LayoutSwap(jam()))
    assert sends(effects) == []
    bars = {e.strip: e.state for e in effects if isinstance(e, StripBar)}
    assert bars[Strip(3)].value == 5000 and surface.strip_positions()[("jam", 1, Strip(3))] == 5000
