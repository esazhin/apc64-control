"""The LabSession aggregate on the contract §4.2 values (T7, s5 supplier) and the §2.7 a5/q9 rules."""
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.layout import ControlEvent
from _apc64_lab.domain.generators import FifthsHue, Isomorphic, TonnetzCheckerboard, generate
from _apc64_lab.domain.lab_section import INTERVAL_CYCLE, WINDOW_SHIFT, LabDefinition
from _apc64_lab.domain.memory_sysex import parse_project_dump
from _apc64_lab.domain.pads import Rgb
from _apc64_lab.domain.records import StripAssignment
from _apc64_lab.domain.session import (
    RESTORED_MESSAGE, EdgeHit, Ended, EndReason, Ignored, LabSession, NeedBackup, Paused, SessionLayout, ShowOled,
    State, Unchanged, Write,
)

NOW = 10_000.0


def tonnetz(name="Tonnetz C", base=48, strips=()):
    definition = LabDefinition("tonnetz", (("base", base), ("channel", 1)), strips=tuple(strips))
    return SessionLayout.of_grid(name.lower().replace(" ", "-"), name, lambda t: generate(
        TonnetzCheckerboard(), {"base": base, "channel": 1}, FifthsHue(), t), definition)


def r1c1(decision):
    return decision.record.pad(PadPos(1, 1)).note


def loops(factory_frame):
    """'Loops' in slot 0 before the session: the factory record with one pad recoloured."""
    record = parse_project_dump(factory_frame)[1]
    return record.with_pad_records({5: record.pads[5].with_fields(rest=Rgb(1, 2, 3))})


def running(factory_frame, layout=None, view=UnitView.CUSTOM):
    session = LabSession()
    session.on_view(view)
    assert isinstance(session.activate(layout or tonnetz()), NeedBackup)
    first = session.started(loops(factory_frame), "slot0-2026-10-24T20-15", None, NOW)
    return session, first


def on_fifth(session):
    assert isinstance(session.cycle_interval(), ShowOled)
    return session


def test_first_activation_backs_up_slot_0_once_then_writes_at_oct_0(factory_frame):   # A22, d75, d38
    session, first = running(factory_frame)
    assert isinstance(first, Write) and r1c1(first) == 48
    assert first.oled.rows == ("Tonnetz C", "Oct +0") and not first.prompt_custom
    assert session.backup == loops(factory_frame) and session.expected == first.record
    assert first.record.pads[5].rest == Rgb(0, 0, 0)   # r1c6 is a dark checkerboard pad, written over Loops
    assert isinstance(session.shift(+1), Write)   # shifts take no further backup: no NeedBackup ever again


def test_each_session_takes_a_full_backup_unless_a_recent_one_exists(factory_frame):   # §2.7 a5/q9
    _, first = running(factory_frame)
    assert first.full_backup
    session = LabSession()
    session.activate(tonnetz())
    assert not session.started(loops(factory_frame), "slot0-x", NOW - 300, NOW).full_backup
    session = LabSession()
    session.activate(tonnetz())
    assert session.started(loops(factory_frame), "slot0-x", NOW - 601, NOW).full_backup


def test_outside_custom_view_the_first_write_still_happens_and_asks_for_custom(factory_frame):   # A23, d21
    _, first = running(factory_frame, view=UnitView.SESSION)
    assert isinstance(first, Write) and first.prompt_custom


def test_one_detent_right_and_left_on_fifth(factory_frame):   # A24, A25
    session = on_fifth(running(factory_frame)[0])
    right = session.shift(+1)
    assert r1c1(right) == 55 and right.oled.row1 == "5th +1"
    left = session.shift(-1)
    assert r1c1(left) == 48 and left.oled.row1 == "5th +0"


def test_the_replica_encoder_takes_the_same_path(factory_frame):   # A37, s40
    session = on_fifth(running(factory_frame)[0])
    decision = session.on_control(WINDOW_SHIFT, ControlEvent.turn(+1))
    assert r1c1(decision) == 55 and decision.oled.row1 == "5th +1"
    assert session.on_control(INTERVAL_CYCLE, ControlEvent.pressed()).oled.row1 == "3rd +0"


def test_tempo_during_a_spin_keeps_the_steps_already_counted(factory_frame):   # A36, d34
    session = on_fifth(running(factory_frame)[0])
    session.shift(+1)
    session.shift(+1)
    session.cycle_interval()
    session.shift(+1)
    last = session.shift(+1)
    assert last.oled.row1 == "3rd +2" and r1c1(last) == 70   # 48 + 14 + 8


def test_a_multi_step_message_and_the_edge(factory_frame):   # A32, A31
    session = on_fifth(running(factory_frame)[0])
    assert r1c1(session.shift(+3)) == 69
    session = running(factory_frame)[0]
    for _ in range(4):
        decision = session.shift(+1)
    assert r1c1(decision) == 96 and decision.record.pad(PadPos(8, 8)).note == 124
    edge = session.shift(+1)
    assert isinstance(edge, EdgeHit) and edge.oled.row1 == "Oct +4 edge"
    assert session.expected == decision.record                         # pads unchanged


def test_an_identical_layout_under_another_name_writes_nothing(factory_frame):   # A13, d7
    session, _ = running(factory_frame)
    decision = session.activate(tonnetz("Tonnetz C copy"))
    assert isinstance(decision, Unchanged) and decision.oled.row0 == "Tonnetz C copy"


def test_switching_to_another_layout_ends_held_notes_and_starts_at_oct_0(factory_frame):   # d38, d47
    session, _ = running(factory_frame)
    session.cycle_interval()
    session.shift(+2)
    fourths = SessionLayout.of_grid("fourths", "Fourths", lambda t: generate(
        Isomorphic(), {"base": 36, "column": 1, "row": 5, "channel": 1}, FifthsHue(), t))
    decision = session.activate(fourths, held=[55, 48, 55])
    assert isinstance(decision, Write) and r1c1(decision) == 36 and decision.oled.rows == ("Fourths", "Oct +0")
    assert decision.end_notes == (48, 55)


def test_a_shift_ends_the_held_notes(factory_frame):   # A41 (domain half), d47
    session = on_fifth(running(factory_frame)[0])
    assert session.shift(+1, held=[48]).end_notes == (48,)


def test_other_views_pause_and_custom_resumes_where_it_was(factory_frame):   # A38, d22
    session = on_fifth(running(factory_frame)[0])
    session.shift(+2)
    note_view = session.on_view(UnitView.NOTE)
    assert note_view.message == "Custom view off" and note_view.oled.row1 == "Custom off"   # 14-character OLED
    paused = session.shift(+1)
    assert isinstance(paused, Paused) and paused.message == "Custom view off"
    assert isinstance(session.cycle_interval(), Paused)
    resumed = session.on_view(UnitView.CUSTOM)
    assert isinstance(resumed, ShowOled) and resumed.oled.row1 == "5th +2"


def test_a_changed_definition_is_rewritten_at_the_current_window(factory_frame):   # A15, d9
    session = on_fifth(running(factory_frame)[0])
    session.shift(+2)
    decision = session.reloaded(tonnetz(base=50))
    assert isinstance(decision, Write) and r1c1(decision) == 64 and decision.oled.row1 == "5th +2"


def test_the_strip_section_is_written_with_the_pads(factory_frame):   # §2.7 q6
    layout = tonnetz(strips=[(3, StripAssignment(cc=30, channel=2))])
    _, first = running(factory_frame, layout)
    assert first.record.strip(3).cc == 30 and first.record.strip(1) == loops(factory_frame).strip(1)


def test_release_restores_the_backup_while_slot_0_holds_the_lab_record(factory_frame):   # A42, inv6
    session, _ = running(factory_frame)
    written = session.shift(+1).record
    ended = session.end(EndReason.RELEASE, slot0_now=written)
    assert isinstance(ended, Ended) and ended.restore == loops(factory_frame) and ended.message == RESTORED_MESSAGE
    assert session.state is State.ENDED


def test_leaving_for_a_host_layout_restores_too(factory_frame):   # A44
    session, first = running(factory_frame)
    assert session.end(EndReason.LEFT, slot0_now=first.record).restore == loops(factory_frame)


def test_unplugged_names_the_backup_to_restore(factory_frame):   # A43, d80
    session, _ = running(factory_frame)
    ended = session.end(EndReason.GONE)
    assert ended.restore is None and ended.message == (
        "slot 0 could not be restored; restore slot0-2026-10-24T20-15 after reconnecting")


# --- §2.7 a5/q9: the user changes projects on the unit ----------------------------------------------------
def test_loading_another_project_ends_the_session_quietly(factory_frame):   # §2.7: Project-view report
    session, _ = running(factory_frame)
    ended = session.on_view(UnitView.PROJECT)
    assert isinstance(ended, Ended) and ended.quiet and ended.restore is None
    assert ended.backup_id == "slot0-2026-10-24T20-15"                    # the pre-session backup is kept
    assert isinstance(session.shift(+1), Ignored)


def test_a_slot_0_mismatch_ends_the_session_quietly(factory_frame):   # §2.7: slot-0 mismatch
    session, first = running(factory_frame)
    assert isinstance(session.on_slot0(first.record), Ignored)
    other = parse_project_dump(factory_frame)[1]
    assert not session.may_overwrite(other)
    ended = session.on_slot0(other)
    assert ended.quiet and ended.restore is None and session.state is State.ENDED


def test_release_after_an_on_unit_project_change_restores_nothing(factory_frame):   # §2.7 hermetic case
    session, _ = running(factory_frame)
    session.on_view(UnitView.PROJECT)
    ended = session.end(EndReason.RELEASE, slot0_now=parse_project_dump(factory_frame)[1])
    assert ended.quiet and ended.restore is None


def test_release_restores_nothing_over_a_project_loaded_without_a_view_report(factory_frame):   # inv5
    session, _ = running(factory_frame)
    ended = session.end(EndReason.STOP, slot0_now=parse_project_dump(factory_frame)[1])
    assert ended.quiet and ended.restore is None


def test_a_save_on_the_unit_leaves_the_session_running(factory_frame):   # §2.7: save mid-session
    session, first = running(factory_frame)
    # saving copies slot 0 into a project slot; slot 0 itself still holds the lab's record
    assert isinstance(session.on_slot0(first.record), Ignored) and session.active


def test_returning_to_a_generated_layout_starts_a_fresh_session(factory_frame):   # §2.7
    session, _ = running(factory_frame)
    session.cycle_interval()
    session.on_view(UnitView.PROJECT)
    session.on_view(UnitView.CUSTOM)
    assert isinstance(session.activate(tonnetz()), NeedBackup)
    other = parse_project_dump(factory_frame)[1]
    first = session.started(other, "slot0-2026-10-24T20-40", NOW, NOW + 60)
    assert first.oled.row1 == "Oct +0" and session.backup == other and not first.full_backup


# --- previews (§2.7 q4) and edges of the state machine ---------------------------------------------------
def test_a_library_entry_previews_live_with_the_same_backup_and_restore(factory_frame):   # §2.7 q4
    captured = parse_project_dump(factory_frame)[1]
    preview = SessionLayout("live-set-b", "Live set B", preview=captured)
    session, first = running(factory_frame, preview)
    assert first.record == captured and first.oled.rows == ("Live set B", "preview")
    assert isinstance(session.shift(+1), Ignored)
    assert session.end(EndReason.RELEASE, slot0_now=captured).restore == loops(factory_frame)


def test_no_session_no_writes():
    session = LabSession()
    assert isinstance(session.shift(+1), Ignored) and isinstance(session.cycle_interval(), Ignored)
    assert session.end(EndReason.RELEASE).quiet
    assert session.held_to_end([52, 48, 52]) == (48, 52)


def test_a_repaint_writes_the_same_window_again_quietly(factory_frame):
    from _apc64_lab.domain.performer_pads import control_pads, with_controls
    session, first = running(factory_frame)
    assert isinstance(session.repaint(), Ignored)                                   # the same record: nothing to write
    plain = session.layout.render
    session.layout = type(session.layout)(session.layout.layout_id, session.layout.name, session.layout.definition,
                                          lambda t: with_controls(plain(t), control_pads(6, ["maj"], [], "maj")),
                                          session.layout.span)
    again = session.repaint()
    assert isinstance(again, Write) and again.quiet and again.end_notes == ()
