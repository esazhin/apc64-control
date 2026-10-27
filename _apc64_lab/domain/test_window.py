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


# --- a generator's own window: steps and range (amendment 2026-10-27, the guitar neck) ---------------------
from _apc64_lab.domain.window import StepWindow, WindowSpec, WindowStep, window_for

FRET, PAGE = WindowStep("Fret", "Fr", 1), WindowStep("Page", "Pg", paged=True)
NECK_24 = WindowSpec((FRET, PAGE), 0, 17, pages=(0, 8, 16, 17), shown=8)   # 24 frets, 8 on the pads
E_STANDARD = NoteSpan(40, 71)    # low E open to high E fret 7 at transposition 0


def at(position, step=0, spec=NECK_24):
    return StepWindow(spec, step, position)


def test_a_layout_without_its_own_window_keeps_octave_fifth_third():
    assert window_for(None) == LabWindow()
    assert window_for(NECK_24) == StepWindow(NECK_24, 0, 0)


def test_the_fret_step_moves_one_semitone_and_row_2_shows_the_frets_on_the_pads():
    window = StepWindow.starting(NECK_24).shifted(+3, E_STANDARD)
    assert window.transposition() == 3 and window.oled("Guitar").rows == ("Guitar", "Fret 3-10")
    assert window.shifted(-1, E_STANDARD).label() == "Fret 2-9"


def test_tempo_toggles_fret_and_page_and_the_position_stays():
    window = at(3).cycled()
    assert window.kind is PAGE and window.position == 3 and window.label() == "Page 3-10"
    assert window.cycled().kind is FRET and window.cycled().position == 3


def test_paging_stops_at_the_multiples_of_8_and_the_end_of_the_neck():
    assert at(3, 1).shifted(-1, E_STANDARD).position == 0
    assert at(17, 1).shifted(-1, E_STANDARD).position == 16
    assert at(16, 1).shifted(+1, E_STANDARD).position == 17
    assert at(0, 1).shifted(+1, E_STANDARD).position == 8 and at(3, 1).shifted(+1, E_STANDARD).position == 8
    assert at(0, 1).shifted(+3, E_STANDARD).position == 17          # several detents: several pages at once
    assert at(17, 1).oled("Guitar").row1 == "Page 17-24"


def test_beyond_either_end_the_step_is_an_edge_refused_as_a_whole():
    edge = at(17, 1).shifted(+1, E_STANDARD)
    assert isinstance(edge, Edge) and edge.window == at(17, 1)
    assert edge.oled("Guitar").row1 == "Pg 17-24 edge"                # 'Page 17-24 edge' is 15 characters
    assert at(15).shifted(+3, E_STANDARD) == Edge(at(15), 3)          # 18 > 17: none of the three is taken
    assert at(0).shifted(-1, E_STANDARD).oled("Guitar").row1 == "Fret 0-7 edge"
    assert at(17).shifted(+1, E_STANDARD).oled("Guitar").row1 == "Fr 17-24 edge"
    assert isinstance(at(0, 1).shifted(-1, E_STANDARD), Edge)
    assert isinstance(at(0, 1).shifted(+4, E_STANDARD), Edge)        # only three pages ahead of 0


def test_the_0_127_edge_still_applies_inside_the_range():
    high = NoteSpan(100, 125)
    assert isinstance(at(2).shifted(+1, high), Edge) and at(2).shifted(-1, high).position == 1


def test_a_changed_spec_keeps_the_window_while_its_range_holds_it():
    shorter = WindowSpec((FRET, PAGE), 0, 5, pages=(0, 5), shown=8)   # 12 frets
    assert at(4, 1).within(shorter) == StepWindow(shorter, 1, 4)
    assert at(9, 1).within(shorter) is None and at(4).within(None) is None


def test_the_api_shape_of_a_stepped_window():
    found = at(3, 1).to_json()
    assert found["interval"] == "Page" and found["offset"] == 3 and found["transposition"] == 3
    assert found["window"] == {"steps": ["Fret", "Page"], "step": "Page", "position": 3, "label": "Page 3-10",
                               "lowest": 0, "highest": 17, "pages": [0, 8, 16, 17], "shown": 8, "unit": None}
    assert LabWindow().to_json()["window"] == {"steps": ["Oct", "5th", "3rd"], "step": "Oct", "label": "Oct +0"}


def test_with_a_unit_row_2_shows_what_is_on_the_pads_and_the_kind_and_edge_flash():   # 2026-10-27
    from dataclasses import replace
    frets = replace(NECK_24, unit="Frets", end_text="Neck end")
    assert at(8, 1, frets).oled("Guitar").row1 == "Frets 8-15" == at(8, 0, frets).oled("Guitar").row1
    assert at(8, 1, frets).flash_step("Guitar").row1 == "Step: Page"
    edge = at(17, 1, frets).shifted(+1, E_STANDARD)
    assert edge.oled("Guitar").row1 == "Frets 17-24" and edge.flash("Guitar").row1 == "Neck end"
    assert len(StepWindow(replace(frets, highest=29), 0, 29).oled("Guitar").row1) <= 14   # 'Frets 29-36'
    assert at(8).flash_step("Guitar") is None and LabWindow().flash_step("x") is None   # no unit: as before
    assert at(3, 1).label() == "Page 3-10"                                 # the page's window line keeps the kind
