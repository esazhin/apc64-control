from _apc64_host.domain.conftest import (
    BITWIG, MPC, RED, bank, cc, encoder_cc, layout, mix_strips, note, page, strip_bend, toggle_cc,
)
from _apc64_host.domain.controls import (
    SURFACE, ControlRole, DeviceLocal, Encoder, EncoderPress, PadPos, Reachability, SceneButton, Shift, Strip, StripModeButton,
    StripTouch, TrackButton, Transport, TransportName, ViewName,
)
from _apc64_host.domain.layout import NavState
from _apc64_host.domain.resolver import binding_label, card, elsewhere, overview, resolve

PLAY = Transport(TransportName.PLAY)
R1C1 = PadPos(1, 1)


def jam():
    return layout(pages=[
        page(1, "Drums", {R1C1: note(36), PLAY: cc(118), TrackButton(1): toggle_cc(20), Encoder(): encoder_cc(30)},
             {R1C1: note(48), PLAY: cc(119)}),
        page(2, "Keys", {R1C1: note(50)}),
    ], banks=[bank(1, "Mix", mix_strips()), bank(5, "FX", {Strip(3): strip_bend(2, touch_note=60)})])


def test_every_control_has_its_current_label_or_is_empty():
    meaning = resolve(jam(), NavState("jam"))
    assert meaning[R1C1].label == "Note 36 → mpc" and not meaning[R1C1].empty
    assert meaning[PLAY].label == "CC118 → mpc"
    assert meaning[PadPos(8, 8)].empty and meaning[PadPos(8, 8)].label == ""
    assert meaning[Strip(1)].label == "CC20 → mpc"
    assert meaning[Encoder()].label == "CC30 → mpc"
    assert meaning[TrackButton(1)].toggle
    assert set(meaning.controls) == {e.id for e in SURFACE}


def test_holding_shift_swaps_every_label_and_a_missing_shift_binding_is_empty():
    meaning = resolve(jam(), NavState("jam", shift=True))
    assert meaning[R1C1].label == "Note 48 → mpc" and meaning[PLAY].label == "CC119 → mpc"
    assert meaning[TrackButton(1)].empty
    assert meaning[R1C1].base.label == "Note 36 → mpc"


def test_navigation_controls_show_page_and_bank_names_and_strip_modes_keep_their_panel_names():
    meaning = resolve(jam(), NavState("jam", page=2))
    assert meaning[SceneButton(1)].label == "Drums" and meaning[SceneButton(3)].label == ""
    assert meaning[StripModeButton(5)].label == "FX" and meaning[StripModeButton(5)].display == "Channel"
    assert meaning[SceneButton(1)].role is ControlRole.NAVIGATION
    assert meaning[Shift()].label == "Shift"
    assert meaning[DeviceLocal(ViewName.NOTE)].role is ControlRole.DEVICE_LOCAL
    assert [s.current for s in meaning.pages][:2] == [False, True]
    assert [s.defined for s in meaning.banks] == [True, False, False, False, True, False]


def test_strip_touch_and_bank_switch():
    meaning = resolve(jam(), NavState("jam", bank=5))
    assert meaning[Strip(3)].label == "Bend → bitwig" and meaning[StripTouch(3)].label == "Bend → bitwig"
    assert meaning[Strip(1)].empty and meaning[StripTouch(1)].empty


def test_missing_devices_are_marked_on_their_labels():
    meaning = resolve(jam(), NavState("jam"), missing={"mpc"})
    assert meaning[R1C1].label == "Note 36 → mpc (missing)" and meaning[R1C1].current.missing == ("mpc",)


def test_labels_prefer_the_layout_label_and_count_extra_messages():
    assert binding_label(note(36, label="Kick")) == "Kick"
    assert binding_label(None) == ""


def test_the_idle_oled_shows_layout_page_and_bank():
    assert resolve(jam(), NavState("jam")).oled_idle.rows == ("Jam", "P1 Drums | B1")
    assert resolve(None, NavState(None)).oled_idle.rows == ("No layout", "")


def test_the_card_shows_both_layers_ports_and_where_else_in_one_step():
    shown = card(jam(), NavState("jam"), R1C1)
    assert shown.base == "Note 36 → mpc ch 10, momentary"
    assert shown.shift == "Note 48 → mpc ch 10, momentary"
    assert shown.port_status == ("mpc connected",)
    assert [e.text for e in shown.elsewhere] == ["Page 2: Note 50"]
    assert shown.reachable is Reachability.UNVERIFIED
    assert "Base: Note 36 → mpc ch 10, momentary" in shown.lines()
    assert card(jam(), NavState("jam"), TrackButton(1)).base == "CC20 → mpc ch 1, toggle"
    assert card(jam(), NavState("jam"), R1C1, missing={"mpc"}).port_status == ("mpc missing",)


def test_elsewhere_skips_identical_bindings_and_lists_banks_for_strips():
    same = layout(pages=[page(1, base={R1C1: note(36)}), page(2, base={R1C1: note(36)}),
                         page(3, shift={R1C1: note(40)})])
    assert [e.text for e in elsewhere(same, R1C1, NavState("jam"))] == ["Page 3 Shift: Note 40"]
    assert [e.text for e in elsewhere(jam(), Strip(3), NavState("jam"))] == ["Bank 5: Bend"]


def test_the_overview_lists_every_page_and_bank_on_both_layers():
    view = overview(jam())
    assert len(view.pages) == 8 and len(view.banks) == 6
    assert view.pages[0].base[R1C1].label == "Note 36 → mpc" and view.pages[0].shift[PLAY].label == "CC119 → mpc"
    assert view.pages[2].defined is False and view.banks[4].name == "FX"
    assert overview(None).pages == ()


def test_fifty_full_layouts_resolve_every_control_on_page_8_shift():
    bindable = [e.id for e in SURFACE if e.role is ControlRole.BINDABLE
                and not isinstance(e.id, (Strip, StripTouch, Encoder, EncoderPress))]
    layouts = []
    for k in range(50):
        pages = [page(p, f"P{p}", {c: note((i + p) % 128) for i, c in enumerate(bindable)},
                      {c: cc((i + k) % 128) for i, c in enumerate(bindable)}) for p in range(1, 9)]
        banks = [bank(b, f"B{b}", mix_strips(), mix_strips(60)) for b in range(1, 7)]
        layouts.append(layout(f"layout-{k:02d}", f"Layout {k}", pages, banks))
    last = layouts[-1]
    meaning = resolve(last, NavState(last.id, page=8, bank=6, shift=True))
    for control in bindable:
        assert meaning[control].label.startswith("CC"), control
    assert meaning[Strip(8)].label == "CC67 → mpc"
    assert len(overview(last).pages[7].shift) == len(bindable)


def test_a_card_for_a_coloured_binding_keeps_its_colour_out_of_the_label():
    shown = resolve(layout(pages=[page(1, base={R1C1: note(36, colour=RED)})]), NavState("jam"))
    assert shown[R1C1].label == "Note 36 → mpc" and shown[R1C1].base.binding.colour == RED
    assert layout(devices=(MPC, BITWIG)).devices["bitwig"].pattern == "Bitwig Studio In"
