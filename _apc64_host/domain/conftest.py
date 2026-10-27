"""Builders for domain tests: small, explicit layouts without going through the notation."""
from _apc64_host.domain.controls import PadPos, Strip
from _apc64_host.domain.layout import (
    Action, Bank, Binding, BindingMode, DeviceDecl, EncoderValue, Fixed, FeedbackRule, Layer, Layout, MessageKind,
    Page, PressVelocity, RoutingRule, StripBinding, StripPosition, ToggleState, ToggleValues, UnitPortRole,
)
from _apc64_host.domain.palette import parse_colour

MPC = DeviceDecl("mpc", "MPC Live III MIDI 1")
BITWIG = DeviceDecl("bitwig", "Bitwig Studio In")


def note(n, ch=10, device="mpc", velocity=None, **options):
    value = Fixed(velocity) if velocity is not None else PressVelocity()
    return Binding((Action(device, MessageKind.NOTE, ch, n, value),), **options)


def cc(n, ch=1, device="mpc", value=127, **options):
    return Binding((Action(device, MessageKind.CC, ch, n, Fixed(value)),), **options)


def toggle_cc(n, ch=1, device="mpc", on=127, off=0, **options):
    action = Action(device, MessageKind.CC, ch, n, ToggleState(ToggleValues(on, off)))
    return Binding((action,), BindingMode.TOGGLE, **options)


def encoder_cc(n, ch=1, device="mpc"):
    return Binding((Action(device, MessageKind.CC, ch, n, EncoderValue()),))


def strip_cc(n, ch=1, device="mpc", **options):
    return StripBinding(Action(device, MessageKind.CC, ch, n, StripPosition()), **options)


def strip_bend(ch, device="bitwig", touch_note=None, **options):
    touch = Action(device, MessageKind.NOTE, ch, touch_note, PressVelocity()) if touch_note is not None else None
    return StripBinding(Action(device, MessageKind.PITCHBEND, ch, None, StripPosition()), touch, **options)


def feedback(kind, number, device="mpc", channel=None, on=None, off=None):
    return FeedbackRule(device, MessageKind(kind), number, channel,
                        parse_colour(on) if on else None, parse_colour(off) if off else None)


def page(number, name=None, base=None, shift=None):
    return Page(number, name, {Layer.BASE: base or {}, Layer.SHIFT: shift or {}})


def bank(number, name=None, base=None, shift=None):
    return Bank(number, name, {Layer.BASE: base or {}, Layer.SHIFT: shift or {}})


def layout(id="jam", name="Jam", pages=(), banks=(), devices=(MPC, BITWIG), routing=()):
    return Layout(id, name, {d.name: d for d in devices}, {p.number: p for p in pages},
                  {b.number: b for b in banks}, {r.role: r for r in routing})


def notes_rule(device="mpc", channel=2, **options):
    return RoutingRule(UnitPortRole.NOTES, device, channel, **options)


def drum_pads(start=36, count=16, ch=10, **options):
    """pads r1c1.. bound to ascending notes, as 'pads r1c1-r2c8: notes from 36' compiles."""
    return {PadPos.from_index(i): note(start + i, ch, **options) for i in range(count)}


def mix_strips(start=20, ch=1):
    return {Strip(n): strip_cc(start + n - 1, ch) for n in range(1, 9)}


RED = parse_colour("red")
