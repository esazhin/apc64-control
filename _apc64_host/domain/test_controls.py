import pytest

from _apc64_host.domain.controls import (
    SURFACE, ControlRole, EncoderPress, FunctionButton, FunctionName, LedKind, ModeButton, ModeName, PadPos,
    Reachability, SceneButton, Shift, Strip, StripModeButton, StripTouch, TrackButton, TrackControl, Transport,
    TransportName, control_names, entry, format_controls, parse_control, parse_controls, role_of,
)
from _apc64_host.domain.issues import DomainInvariantError


def test_pad_r1c1_is_the_bottom_left_grid_pad_and_wire_pad_0():
    pad = parse_control("pad r1c1")
    assert pad == PadPos(1, 1) and pad.index == 0
    pads = [e for e in SURFACE if isinstance(e.id, PadPos)]
    assert entry(pad).geometry.y == max(e.geometry.y for e in pads)
    assert entry(pad).geometry.x == min(e.geometry.x for e in pads)
    assert PadPos.from_index(63) == PadPos(8, 8)


def test_a_pad_range_expands_to_its_controls_in_reading_order():
    pads = parse_controls("pads r1c1-r2c8")
    assert len(pads) == 16 and pads[0] == PadPos(1, 1) and pads[8] == PadPos(2, 1)
    assert parse_controls("pads r1c5-r2c4") == tuple(PadPos.from_index(i) for i in range(4, 12))
    assert parse_controls("Pads R1C1 – R1C2") == (PadPos(1, 1), PadPos(1, 2))


def test_numbered_ranges_accept_singular_and_plural_words():
    assert parse_controls("tracks 1-8") == tuple(TrackButton(n) for n in range(1, 9))
    assert parse_controls("strip 1-3") == (Strip(1), Strip(2), Strip(3))
    assert parse_controls("trackctls 2-3") == (TrackControl(2), TrackControl(3))
    assert parse_control("strip 3 touch") == StripTouch(3)


def test_named_controls_parse_to_their_ids():
    assert parse_control("play") == Transport(TransportName.PLAY)
    assert parse_control("tempo") == FunctionButton(FunctionName.TEMPO)
    assert parse_control("clipstop") == ModeButton(ModeName.CLIPSTOP)
    assert parse_control("encoder press") == EncoderPress()
    assert parse_control("shift") == Shift()


def test_unknown_controls_name_the_problem_and_the_valid_names():
    with pytest.raises(DomainInvariantError) as raised:
        parse_control("pad r9c1")
    assert (raised.value.problem, raised.value.fix) == ("no such pad", "pads are r1c1–r8c8")
    with pytest.raises(DomainInvariantError) as raised:
        parse_control("knob 3")
    assert "pad r1c1–r8c8" in raised.value.fix
    with pytest.raises(DomainInvariantError):
        parse_control("track 9")
    with pytest.raises(DomainInvariantError):
        parse_controls("pads r2c1-r1c1")
    with pytest.raises(DomainInvariantError):
        parse_control("tracks 1-2")


def test_surface_lists_every_physical_control_once_with_its_role():
    names = control_names()
    assert len(names) == len(set(names))
    assert len([e for e in SURFACE if isinstance(e.id, PadPos)]) == 64
    assert role_of(SceneButton(1)) is ControlRole.NAVIGATION
    assert role_of(StripModeButton(6)) is ControlRole.NAVIGATION
    assert role_of(Shift()) is ControlRole.MODIFIER
    assert role_of(TrackButton(1)) is ControlRole.BINDABLE
    assert entry(PadPos(1, 1)).led is LedKind.RGB and entry(SceneButton(1)).led is LedKind.SINGLE
    assert entry(Strip(1)).led is LedKind.BAR
    assert [e.display for e in SURFACE if isinstance(e.id, StripModeButton)] == [
        "Device", "Volume", "Pan", "Sends", "Channel", "Off"]
    for name in names:
        assert str(parse_control(name)) == name


def test_shift_reach_is_unverified_where_no_capture_exists():
    assert entry(PadPos(1, 1)).shift_reach is Reachability.UNVERIFIED
    assert entry(TrackButton(1)).shift_reach is Reachability.UNVERIFIED
    assert entry(SceneButton(4)).shift_reach is Reachability.VERIFIED
    assert entry(Transport(TransportName.PLAY)).shift_reach is Reachability.VERIFIED


def test_format_controls_writes_the_shortest_run_names():
    assert format_controls([PadPos(1, 3)]) == "pad r1c3"
    assert format_controls(parse_controls("pads r1c5-r1c8")) == "pads r1c5–r1c8"
    assert format_controls([TrackButton(2), TrackButton(1)]) == "tracks 1–2"
    assert format_controls([PadPos(1, 1), PadPos(1, 3)]) == "pad r1c1, pad r1c3"
