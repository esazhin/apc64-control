import pytest

from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.palette import APPROXIMATE, NAMES, Colour, palette, parse_colour


def test_colour_names_map_to_fixed_ableton_palette_indexes():
    assert [parse_colour(n).index for n in ("red", "orange", "yellow", "green", "cyan", "blue", "purple",
                                            "magenta")] == [5, 9, 13, 21, 37, 45, 49, 53]
    assert parse_colour("Dim White").index == 1 == parse_colour("dim-white").index
    assert parse_colour("gray") == parse_colour("grey")
    assert parse_colour(42).index == 42 and parse_colour("42").index == 42


def test_colours_compare_by_index_and_display_by_name():
    assert Colour(5) == parse_colour("red")
    assert str(parse_colour("red")) == "red" and str(Colour(42)) == "42" and str(Colour(5)) == "red"


def test_unknown_colours_and_indexes_are_refused_with_the_names():
    with pytest.raises(DomainInvariantError) as raised:
        parse_colour("chartreuse")
    assert "red" in raised.value.fix
    with pytest.raises(DomainInvariantError):
        Colour(128)


def test_the_palette_has_128_entries_marked_as_an_approximation():
    entries = palette()
    assert len(entries) == 128 and APPROXIMATE
    assert entries[5].rgb == (255, 0, 0) and entries[5].name == "red"
    assert entries[0].rgb == (0, 0, 0)
    assert set(NAMES.values()) <= {e.index for e in entries}
