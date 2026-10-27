"""LabWindow on the 'Tonnetz C' values of contract §4.2 (T2)."""
from _apc64_lab.domain.music import Interval
from _apc64_lab.domain.pads import NoteSpan
from _apc64_lab.domain.window import Edge, LabWindow

TONNETZ_C = NoteSpan(48, 76)     # Tonnetz base 48: r1c1 = 48 is the lowest pad, r8c8 = 76 the highest
R1C1 = 48


def test_tempo_pressed_four_times_reads_fifth_third_octave_fifth():   # A26
    window, rows = LabWindow(), []
    for _ in range(4):
        window = window.cycled()
        rows.append(window.oled("Tonnetz C").row1)
    assert rows == ["5th +0", "3rd +0", "Oct +0", "5th +0"]


def test_one_step_right_on_octave_is_plus_12():   # A27
    window = LabWindow().shifted(+1, TONNETZ_C)
    assert window.transposition() == 12 and R1C1 + window.transposition() == 60
    assert window.oled("Tonnetz C").rows == ("Tonnetz C", "Oct +1")


def test_one_step_right_on_third_is_plus_4():   # A28
    window = LabWindow().cycled().cycled().shifted(+1, TONNETZ_C)
    assert window.interval is Interval.THIRD and window.transposition() == 4
    assert R1C1 + window.transposition() == 52 and window.label() == "3rd +1"


def test_tempo_two_steps_tempo_one_step_back():   # A29
    window = LabWindow().cycled()
    window = window.shifted(+1, TONNETZ_C).shifted(+1, TONNETZ_C)
    assert window.label() == "5th +2"
    window = window.cycled().shifted(-1, TONNETZ_C)
    assert window.label() == "3rd -1"
    assert window.transposition() == 10 and R1C1 + window.transposition() == 58   # 48 + 14 − 4


def test_a_step_past_127_is_refused_as_an_edge():   # A31
    window = LabWindow()
    for _ in range(4):
        window = window.shifted(+1, TONNETZ_C)
    assert R1C1 + window.transposition() == 96 and TONNETZ_C.highest + window.transposition() == 124
    edge = window.shifted(+1, TONNETZ_C)
    assert isinstance(edge, Edge) and edge.window == window
    assert edge.oled("Tonnetz C").row1 == "Oct +4 edge"


def test_a_step_below_0_is_refused_too():   # d29
    window = LabWindow()
    for _ in range(4):
        window = window.shifted(-1, TONNETZ_C)
    assert window.transposition() == -48
    assert isinstance(window.shifted(-1, TONNETZ_C), Edge)


def test_each_interval_keeps_its_own_count():   # d39, d34
    window = LabWindow().cycled().stepped(2).cycled().stepped(2)
    assert (window.count(Interval.OCTAVE), window.count(Interval.FIFTH), window.count(Interval.THIRD)) == (0, 2, 2)
    assert window.transposition() == 22 and window.label() == "3rd +2"


def test_a_long_layout_name_is_cut_to_14_on_the_oled():   # A39
    assert LabWindow().oled("Tonnetz C major lattice").rows == ("Tonnetz C majo", "Oct +0")


def test_a_multi_step_message_moves_all_steps_at_once():   # d30 (A32's 3 steps)
    window = LabWindow().cycled().shifted(+3, TONNETZ_C)
    assert window.label() == "5th +3" and R1C1 + window.transposition() == 69
