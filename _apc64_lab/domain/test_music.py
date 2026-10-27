import pytest

from _apc64_host.domain.issues import DomainInvariantError
from _apc64_lab.domain.music import Interval, PitchClass


def test_intervals_are_octave_fifth_and_major_third():   # d35–d37
    assert [(i.semitones, i.label) for i in Interval] == [(12, "Oct"), (7, "5th"), (4, "3rd")]


def test_tempo_cycles_octave_fifth_third_and_round_again():   # d33
    assert Interval.OCTAVE.next() is Interval.FIFTH
    assert Interval.FIFTH.next() is Interval.THIRD
    assert Interval.THIRD.next() is Interval.OCTAVE


def test_pitch_classes_and_their_place_on_the_circle_of_fifths():
    assert PitchClass.of(64) == 4 and PitchClass.of(48) == 0
    assert [PitchClass(pc).fifths_index for pc in (0, 7, 2, 5)] == [0, 1, 2, 11]
    with pytest.raises(DomainInvariantError):
        PitchClass(12)
