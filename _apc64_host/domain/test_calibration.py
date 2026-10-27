from datetime import datetime

import pytest

from _apc64_host.domain.calibration import Calibration, PadPosition
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.issues import DomainInvariantError

AT = datetime(2026, 10, 23, 14, 2)


def test_two_corner_notes_give_an_assumed_isomorphic_grid():
    calibration = Calibration(AT, 36, 99)   # 8 semitones per row
    assert calibration.row_step == 8
    assert calibration.position_of(36) == PadPosition(PadPos(1, 1), assumed=True)
    assert calibration.position_of(53) == PadPosition(PadPos(3, 2))
    assert calibration.position_of(99).pad == PadPos(8, 8)
    assert calibration.position_of(20) is None
    assert calibration.label == "calibrated 14:02 (assumed)"


def test_repeated_notes_light_the_lowest_pad_and_non_isomorphic_grids_know_only_the_corners():
    fourths = Calibration(AT, 36, 36 + 7 + 35)
    assert fourths.row_step == 5 and fourths.position_of(41).pad == PadPos(1, 6)
    odd = Calibration(AT, 36, 80)
    assert odd.row_step is None and odd.position_of(36).pad == PadPos(1, 1) and odd.position_of(40) is None


def test_a_top_right_note_not_above_the_bottom_left_is_refused():
    with pytest.raises(DomainInvariantError):
        Calibration(AT, 60, 60)
