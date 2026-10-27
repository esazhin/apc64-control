"""The scale library and the circle's keys (the harmony core)."""
import pytest

from _apc64_lab.domain.harmony import (
    MODES_BY_BRIGHTNESS, SCALES, circle_keys, closest_scale, find_scale, mode_steps, spell_scale,
)
from _apc64_lab.domain.harmony.scales import BY_KEY, NATIVE_UNSPECIFIED


def test_every_scale_is_an_ascending_set_from_its_root_with_a_unique_key_and_name():
    assert len({s.key for s in SCALES}) == len(SCALES) and len({s.name for s in SCALES}) == len(SCALES)
    for scale in SCALES:
        assert scale.intervals[0] == 0 and list(scale.intervals) == sorted(set(scale.intervals))
        assert all(0 <= i < 12 for i in scale.intervals), scale.key
        assert scale.key == scale.key.lower() and " " not in scale.key


def test_the_note_views_sixteen_are_the_known_fourteen_and_two_with_unpublished_notes():
    native = [s.name.split(" (")[0] for s in SCALES if s.native]
    assert native == ["Chromatic", "Major", "Melodic minor", "Harmonic minor", "Major pentatonic",
                      "Minor pentatonic", "Dorian", "Phrygian", "Lydian", "Mixolydian", "Aeolian", "Locrian",
                      "Blues", "Whole tone"]
    assert len(native) + len(NATIVE_UNSPECIFIED) == 16
    # the library's own Flamenco and Hungarian say they are not the unit's
    assert not BY_KEY["flamenco"].native and "Akai" in BY_KEY["flamenco"].note
    assert not BY_KEY["hungarian-minor"].native and "Akai" in BY_KEY["hungarian-minor"].note


@pytest.mark.parametrize("key,intervals", [
    ("major", (0, 2, 4, 5, 7, 9, 11)), ("melodic-minor", (0, 2, 3, 5, 7, 9, 11)),
    ("harmonic-minor", (0, 2, 3, 5, 7, 8, 11)), ("harmonic-major", (0, 2, 4, 5, 7, 8, 11)),
    ("double-harmonic", (0, 1, 4, 5, 7, 8, 11)), ("hungarian-minor", (0, 2, 3, 6, 7, 8, 11)),
    ("hungarian-major", (0, 3, 4, 6, 7, 9, 10)), ("neapolitan-major", (0, 1, 3, 5, 7, 9, 11)),
    ("neapolitan-minor", (0, 1, 3, 5, 7, 8, 11)), ("phrygian-dominant", (0, 1, 4, 5, 7, 8, 10)),
    ("octatonic-half-whole", (0, 1, 3, 4, 6, 7, 9, 10)), ("octatonic-whole-half", (0, 2, 3, 5, 6, 8, 9, 11)),
    ("bebop-dominant", (0, 2, 4, 5, 7, 9, 10, 11)), ("bebop-major", (0, 2, 4, 5, 7, 8, 9, 11)),
    ("hirajoshi", (0, 2, 3, 7, 8)), ("in", (0, 1, 5, 7, 8)), ("iwato", (0, 1, 5, 6, 10)),
    ("prometheus", (0, 2, 4, 6, 9, 10)), ("enigmatic", (0, 1, 4, 6, 8, 10, 11)),
    ("flamenco", (0, 1, 3, 4, 5, 7, 8, 10)), ("blues", (0, 3, 5, 6, 7, 10)), ("whole-tone", (0, 2, 4, 6, 8, 10)),
])
def test_scale_intervals(key, intervals):
    assert BY_KEY[key].intervals == intervals


def test_the_melodic_minor_modes_are_its_rotations():
    base = BY_KEY["melodic-minor"].intervals
    for mode, key in enumerate(("dorian-b2", "lydian-augmented", "lydian-dominant", "mixolydian-b6",
                                "locrian-natural2", "altered"), start=1):
        rotated = tuple(sorted((i - base[mode]) % 12 for i in base))
        assert BY_KEY[key].intervals == rotated, key


def test_scales_are_found_by_key_name_or_alias_and_a_misspelling_is_corrected():
    assert find_scale("Harmonic Minor").key == "harmonic-minor"
    assert find_scale("dorian ♭2").key == find_scale("Dorian b2").key == "dorian-b2"
    assert find_scale("Locrian ♮2").key == "locrian-natural2" and find_scale("ionian").key == "major"
    assert find_scale("minor").key == "aeolian" and find_scale("super locrian").key == "altered"
    assert find_scale("nonsense") is None and closest_scale("dorain") == "dorian"


def test_the_parallel_modes_by_brightness_each_raise_one_note():
    assert MODES_BY_BRIGHTNESS == ("locrian", "phrygian", "aeolian", "dorian", "mixolydian", "major", "lydian")
    steps = dict(mode_steps())
    # the degree raised: ♭5, ♭2, ♭6, ♭3, ♭7, 4 (0-based degree indices)
    assert steps == {"locrian": None, "phrygian": 4, "aeolian": 1, "dorian": 5, "mixolydian": 2, "major": 6,
                     "lydian": 3}
    for darker, brighter in zip(MODES_BY_BRIGHTNESS, MODES_BY_BRIGHTNESS[1:]):
        assert len(set(BY_KEY[darker].intervals) ^ set(BY_KEY[brighter].intervals)) == 2


def test_seven_note_scales_are_spelled_letter_correctly_with_the_fewest_accidentals():
    assert list(spell_scale(2, BY_KEY["major"]).values()) == ["D", "E", "F♯", "G", "A", "B", "C♯"]
    assert list(spell_scale(1, BY_KEY["locrian"]).values()) == ["C♯", "D", "E", "F♯", "G", "A", "B"]
    assert list(spell_scale(1, BY_KEY["major"]).values()) == ["D♭", "E♭", "F", "G♭", "A♭", "B♭", "C"]
    assert spell_scale(0, BY_KEY["major-pentatonic"]) == {0: "C", 2: "D", 4: "E", 7: "G", 9: "A"}   # fixed table


def test_the_circle_has_the_relative_minors_inside():
    keys = circle_keys()
    assert [k.major for k in keys] == [("C",), ("G",), ("D",), ("A",), ("E",), ("B",), ("F♯", "G♭"), ("D♭",),
                                       ("A♭",), ("E♭",), ("B♭",), ("F",)]
    assert [k.minor for k in keys] == [("Am",), ("Em",), ("Bm",), ("F♯m",), ("C♯m",), ("G♯m",), ("D♯m", "E♭m"),
                                       ("B♭m",), ("Fm",), ("Cm",), ("Gm",), ("Dm",)]
    assert all(k.minor_pc == (k.pc + 9) % 12 for k in keys)
