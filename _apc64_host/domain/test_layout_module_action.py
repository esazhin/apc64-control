"""Contract 2 (T8): the ModuleAction binding kind on base-layer controls."""
import pytest

from _apc64_host.domain.controls import Encoder, FunctionButton, FunctionName, PadPos
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.layout import (
    Action, Binding, BindingMode, ControlEvent, Layer, Layout, MessageKind, ModuleAction, Page, check_page_binding,
)

SHIFT_WINDOW = Binding((), module_action=ModuleAction("lab", "window_shift"), label="window")
TEMPO = FunctionButton(FunctionName.TEMPO)


def test_a_module_action_binds_the_base_layer_encoder_and_tempo():   # s2.c7
    page = Page(1, None, {Layer.BASE: {Encoder(): SHIFT_WINDOW,
                                       TEMPO: Binding((), module_action=ModuleAction("lab", "interval_cycle"))}})
    assert page.encoder.is_module_action and str(page.encoder.module_action) == "lab.window_shift"
    assert page.binding(Layer.BASE, TEMPO).module_action.action == "interval_cycle"
    layout = Layout("tonnetz-c", "Tonnetz C", {}, {1: page}, sections={"lab": "definition"})
    assert layout.referenced_devices() == [] and layout.section("lab") == "definition"


def test_never_on_the_shift_layer():   # s2.c7
    with pytest.raises(DomainInvariantError, match="Shift"):
        check_page_binding(Encoder(), Layer.SHIFT, SHIFT_WINDOW)
    with pytest.raises(DomainInvariantError, match="base layer only"):
        check_page_binding(TEMPO, Layer.SHIFT, Binding((), module_action=ModuleAction("lab", "interval_cycle")))


def test_a_module_action_sends_no_midi_and_has_no_toggle():
    cc = Action("mpc", MessageKind.CC, 1, 20)
    with pytest.raises(DomainInvariantError):
        Binding((cc,), module_action=ModuleAction("lab", "window_shift"))
    with pytest.raises(DomainInvariantError):
        Binding((), BindingMode.TOGGLE, module_action=ModuleAction("lab", "window_shift"))
    with pytest.raises(DomainInvariantError):
        ModuleAction("Lab", "window shift")
    with pytest.raises(DomainInvariantError):   # contract 1's rule for MIDI bindings is unchanged
        Binding(())


def test_control_events_are_turns_or_presses():
    assert ControlEvent.turn(-3) == ControlEvent(-3, False) and ControlEvent.pressed().press
    assert check_page_binding(PadPos(1, 1), Layer.BASE, SHIFT_WINDOW) is None
