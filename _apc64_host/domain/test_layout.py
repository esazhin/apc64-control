import pytest

from _apc64_host.domain.controls import (
    Encoder, EncoderPress, PadPos, SceneButton, Shift, Strip, StripModeButton, TrackButton, Transport,
    TransportName,
)
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.layout import (
    Action, AftertouchPolicy, Bank, BankLocation, BankNo, Binding, BindingMode, ContentHash, DeviceDecl, Fixed,
    FeedbackRule, Layer, Layout, LayoutId, MessageKind, NavState, Page, PageLocation, PageNo, PressVelocity,
    RoutingRule, StripBinding, StripPosition, ToggleState, ToggleValues, UnitPortRole,
)
from _apc64_host.domain.palette import parse_colour

MPC = DeviceDecl("mpc", "MPC Live III MIDI 1", 10)


def note(n, ch=10, device="mpc"):
    return Action(device, MessageKind.NOTE, ch, n, PressVelocity())


def cc(n, ch=1, device="mpc", value=None):
    return Action(device, MessageKind.CC, ch, n, value or Fixed(127))


def test_page_9_and_bank_7_are_refused_with_the_scene_and_strip_mode_counts():
    with pytest.raises(DomainInvariantError) as raised:
        PageNo(9)
    assert (raised.value.problem, raised.value.fix) == ("the APC64 has 8 scene buttons", "so pages are 1–8")
    with pytest.raises(DomainInvariantError) as raised:
        BankNo(7)
    assert raised.value.fix == "so banks are 1–6"


def test_a_strip_position_cannot_be_a_toggle():
    position = Action("mpc", MessageKind.CC, 1, 20, StripPosition())
    with pytest.raises(DomainInvariantError) as raised:
        StripBinding(position, mode=BindingMode.TOGGLE)
    assert (raised.value.problem, raised.value.fix) == ("a strip position cannot be a toggle", 'remove "toggle"')


def test_a_device_naming_an_apc64_port_is_refused():
    with pytest.raises(DomainInvariantError) as raised:
        DeviceDecl("apc", "APC64 Notes (APC64)")
    assert raised.value.problem == "device apc targets an APC64 port"
    assert raised.value.fix == "the host never sends to the APC64's own ports, choose another port"


def test_navigation_shift_and_strip_controls_cannot_be_bound_on_a_page():
    binding = Binding((note(36),))
    for control in (SceneButton(1), StripModeButton(1), Shift(), Strip(1)):
        with pytest.raises(DomainInvariantError):
            Page(1, layers={Layer.BASE: {control: binding}})


def test_the_encoder_is_bound_on_the_base_layer_only_and_as_one_cc():
    turn = Binding((cc(30),))
    assert Page(1, layers={Layer.BASE: {Encoder(): turn}}).encoder == turn
    for control in (Encoder(), EncoderPress()):
        with pytest.raises(DomainInvariantError) as raised:
            Page(1, layers={Layer.SHIFT: {control: turn}})
        assert raised.value.problem == "Shift + encoder browses layouts and cannot be bound"
    with pytest.raises(DomainInvariantError):
        Page(1, layers={Layer.BASE: {Encoder(): Binding((note(36),))}})


def test_pitch_bend_and_14_bit_cc_belong_to_strips():
    with pytest.raises(DomainInvariantError):
        Binding((Action("mpc", MessageKind.PITCHBEND, 1, None, StripPosition()),))
    pair = Action("mpc", MessageKind.CC14, 1, 20, StripPosition())
    assert pair.lsb == 52
    with pytest.raises(DomainInvariantError):
        Action("mpc", MessageKind.CC14, 1, 100, StripPosition())


def test_a_layout_refuses_bindings_to_undeclared_devices_and_lists_the_declared_ones():
    page = Page(1, "Drums", {Layer.BASE: {PadPos(1, 1): Binding((note(36, device="mcp"),))}})
    with pytest.raises(DomainInvariantError) as raised:
        Layout("jam", "Jam", {"mpc": MPC}, {1: page})
    assert (raised.value.problem, raised.value.fix) == ("unknown device mcp", "declared devices: mpc")


def test_a_minimal_layout_has_one_page_and_one_bank():
    page = Page(1, "Drums", {Layer.BASE: {PadPos(1, 1): Binding((note(36),))}})
    bank = Bank(1, "Mix", {Layer.BASE: {Strip(1): StripBinding(Action("mpc", MessageKind.CC, 1, 20, StripPosition()))}})
    layout = Layout("jam", "Jam", {"mpc": MPC}, {1: page}, {1: bank})
    assert layout.display_name == "Jam" and layout.page(1).display_name == "Drums"
    assert Layout("jam", None, {}).display_name == "jam"
    assert Page(3).display_name == "Page 3" and Page(3).empty


def test_layout_ids_are_file_stems_never_paths():
    assert LayoutId("tonnetz-c_2") == "tonnetz-c_2"
    for bad in ("../etc", "my layout", "a/b", ""):
        with pytest.raises(DomainInvariantError):
            LayoutId(bad)


def test_feedback_index_finds_the_places_a_message_drives():
    rule = FeedbackRule("mpc", MessageKind.NOTE, 50, on_colour=parse_colour("green"))
    toggle = Binding((cc(20, value=ToggleState(ToggleValues())),), BindingMode.TOGGLE,
                     feedback=FeedbackRule("mpc", MessageKind.CC, 20, channel=1))
    page2 = Page(2, layers={Layer.BASE: {PadPos(1, 1): Binding((note(50),), feedback=rule)},
                            Layer.SHIFT: {TrackButton(1): toggle}})
    bar = StripBinding(Action("mpc", MessageKind.CC, 1, 21, StripPosition()),
                       feedback=FeedbackRule("mpc", MessageKind.CC, 21))
    layout = Layout("jam", None, {"mpc": MPC}, {2: page2}, {1: Bank(1, layers={Layer.BASE: {Strip(1): bar}})})
    index = layout.feedback_index()
    assert [loc for _, loc in index.lookup("mpc", MessageKind.NOTE, 50, 3)] == [
        PageLocation(2, Layer.BASE, PadPos(1, 1))]
    assert [loc for _, loc in index.lookup("mpc", MessageKind.CC, 20, 1)] == [
        PageLocation(2, Layer.SHIFT, TrackButton(1))]
    assert list(index.lookup("mpc", MessageKind.CC, 20, 2)) == []
    assert [loc for _, loc in index.lookup("mpc", MessageKind.CC, 21, 9)] == [BankLocation(1, Layer.BASE, Strip(1))]


def test_routing_rules_check_port_role_transpose_and_remap():
    rule = RoutingRule(UnitPortRole.NOTES, "mpc", 2, AftertouchPolicy.CHANNEL_PRESSURE, 12, ((36, 38),))
    assert rule.remap_of(36) == 38 and rule.remap_of(40) == 40
    with pytest.raises(DomainInvariantError):
        RoutingRule(UnitPortRole.DAW, "mpc", 2)
    with pytest.raises(DomainInvariantError):
        RoutingRule(UnitPortRole.NOTES, "mpc", 2, transpose=128)


def test_bindings_compare_by_meaning():
    assert Binding((note(36),), colour=parse_colour("red")) == Binding((note(36),), colour=parse_colour(5))
    assert Binding((note(36),)) != Binding((note(37),))
    assert Binding((cc(118),)).look_colour == parse_colour("white")
    assert Transport(TransportName.PLAY) != Transport(TransportName.STOP)


def test_nav_state_names_its_layer_and_content_hashes_are_stable():
    assert NavState("jam").layer is Layer.BASE and NavState("jam", shift=True).layer is Layer.SHIFT
    assert ContentHash.of("a") == ContentHash.of("a") != ContentHash.of("b")
