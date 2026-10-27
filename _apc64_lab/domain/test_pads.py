import pytest

from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_lab.domain.pads import BLACK, WHITE, NoteSpan, PadAssignment, PadGrid, Rgb


def test_rgb_components_are_bytes_and_render_as_hex():   # d19, A21 (#FFFFFF)
    assert WHITE.to_hex() == "#FFFFFF" and Rgb(1, 127, 128).bytes == b"\x01\x7f\x80"
    assert Rgb.of("#ff0080") == Rgb(255, 0, 128) and Rgb.of([1, 2, 3]) == Rgb(1, 2, 3)
    with pytest.raises(DomainInvariantError) as error:
        Rgb(300, 0, 0)
    assert error.value.problem == "300 is outside 0–255"


def test_a_grid_is_64_pads_from_the_bottom_left():
    pads = [PadAssignment(36 + i, WHITE, WHITE) for i in range(64)]
    grid = PadGrid(tuple(pads))
    assert grid.note_at(1, 1) == 36 and grid.note_at(1, 2) == 37 and grid.note_at(2, 1) == 44
    assert grid.span() == NoteSpan(36, 99)
    assert grid.highest_pad() == PadPos(8, 8) and grid.lowest_pad() == PadPos(1, 1)
    with pytest.raises(DomainInvariantError):
        PadGrid(tuple(pads[:63]))


def test_silent_pads_are_unlit_and_do_not_count_for_the_span():   # d3
    silent = PadAssignment.silence()
    assert silent.silent and silent.rest == BLACK and not silent.aftertouch
    grid = PadGrid((PadAssignment(60, WHITE, WHITE),) + (silent,) * 63)
    assert grid.span() == NoteSpan(60, 60) and len(grid.active) == 1
    assert PadGrid((silent,) * 64).span() is None


def test_active_pads_default_to_aftertouch_on_channel_1():   # d45, q8
    pad = PadAssignment(48, WHITE, WHITE)
    assert pad.aftertouch and pad.channel == 1
    with pytest.raises(DomainInvariantError):
        PadAssignment(128)
    with pytest.raises(DomainInvariantError):
        PadAssignment(60, channel=17)
