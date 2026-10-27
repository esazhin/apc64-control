from _apc64_host.domain.effects import (
    ActivityEntry, ActivityResult, EncoderTurn, Press, StripMove, UnitView,
)
from _apc64_host.domain.controls import PadPos, Strip
from _apc64_host.domain.layout import LayoutCatalog


def test_activity_entries_read_control_message_port_and_result():
    sent = ActivityEntry("pad r1c1", ActivityResult.SENT, "note 36 ch 10", "MPC Live III MIDI 1")
    assert sent.text() == "pad r1c1 → note 36 ch 10 → MPC Live III MIDI 1: sent"
    missing = ActivityEntry("pad r1c1", ActivityResult.NOT_SENT, "note 36 ch 10", "mpc", "mpc missing")
    assert missing.text() == "pad r1c1 → note 36 ch 10 → mpc: not sent, mpc missing"
    assert ActivityEntry("pad r8c8", ActivityResult.UNBOUND).text() == "pad r8c8: unbound"
    assert ActivityEntry("note 144", ActivityResult.DROPPED, reason="note 144 out of range").text() == \
        "note 144: dropped, note 144 out of range"


def test_only_session_view_is_host_drawn():
    assert UnitView.SESSION.host_drawn
    assert not any(v.host_drawn for v in UnitView if v is not UnitView.SESSION)


def test_inputs_default_to_the_unit_and_coerce_values():
    assert Press(PadPos(1, 1)).velocity == 127 and Press(PadPos(1, 1)).source == "unit"
    assert StripMove(Strip(1), 8192).value == 8192 and EncoderTurn(-2).steps == -2


def test_the_catalog_browses_alphabetically_and_wraps():
    catalog = LayoutCatalog.of([("tonnetz-c", "Tonnetz C"), ("jam", "Jam"), ("ambient", "Ambient")])
    assert catalog.ids == ("ambient", "jam", "tonnetz-c")
    assert catalog.step("jam", 1) == "tonnetz-c" and catalog.step("tonnetz-c", 1) == "ambient"
    assert catalog.step("ambient", -1) == "tonnetz-c"
    assert catalog.step(None, 1) == "ambient" and catalog.step(None, -1) == "tonnetz-c"
    assert LayoutCatalog().step("jam", 1) is None and catalog.name_of("jam") == "Jam"
