"""ExpressiveRouter against the acceptance values of contract §4.2 (T5: A102–A118)."""
from _apc64_host.domain.conftest import layout, notes_rule
from _apc64_host.domain.effects import Activity, Play, PlayedMidi, Send, UnitView
from _apc64_host.domain.layout import AftertouchPolicy, RoutingRule, UnitPortRole
from _apc64_host.domain.midi import (
    ChannelPressure, ControlChange, NoteOff, NoteOn, PolyAftertouch,
)
from _apc64_host.domain.router import NOT_ROUTED, ExpressiveRouter

NOTES, CUSTOM = UnitPortRole.NOTES, UnitPortRole.CUSTOM


def router(*rules):
    r = ExpressiveRouter()
    r.set_layout(layout(routing=rules))
    return r


def play(r, *messages, role=NOTES, view=UnitView.NOTE):
    effects = []
    for message in messages:
        effects += r.handle(PlayedMidi(role, message), view)
    return effects


def sent(effects):
    return [e.message for e in effects if isinstance(e, Send)]


def test_note_view_passes_velocity_and_poly_aftertouch_to_the_target_channel():   # A102
    r = router(notes_rule(channel=2))
    effects = play(r, NoteOn(1, 53, 56), PolyAftertouch(1, 53, 10), PolyAftertouch(1, 53, 0), NoteOff(1, 53))
    assert sent(effects) == [NoteOn(2, 53, 56), PolyAftertouch(2, 53, 10), PolyAftertouch(2, 53, 0), NoteOff(2, 53)]
    assert all(e.port == "MPC Live III MIDI 1" for e in effects if isinstance(e, Send))


def test_aftertouch_converted_to_channel_pressure_is_the_highest_held_value():   # A103, d141
    r = router(notes_rule(channel=2, aftertouch=AftertouchPolicy.CHANNEL_PRESSURE))
    effects = play(r, NoteOn(1, 53, 56), NoteOn(1, 57, 60), PolyAftertouch(1, 53, 40), PolyAftertouch(1, 57, 90))
    pressures = [m for m in sent(effects) if isinstance(m, ChannelPressure)]
    assert pressures[-1] == ChannelPressure(2, 90)
    assert not any(isinstance(m, PolyAftertouch) for m in sent(effects))
    after = sent(play(r, NoteOff(1, 57)))
    assert after == [NoteOff(2, 57), ChannelPressure(2, 40)]


def test_dropped_aftertouch_sends_only_the_notes():   # A104
    r = router(notes_rule(channel=2, aftertouch=AftertouchPolicy.DROP))
    effects = play(r, NoteOn(1, 53, 56), PolyAftertouch(1, 53, 30), NoteOff(1, 53))
    assert sent(effects) == [NoteOn(2, 53, 56), NoteOff(2, 53)]


def test_a_chord_sends_three_note_ons_at_one_velocity_and_aftertouch_per_note():   # A105, d129
    r = router(notes_rule(channel=2))
    effects = play(r, *[NoteOn(1, n, 80) for n in (60, 64, 67)], *[PolyAftertouch(1, n, 20) for n in (60, 64, 67)],
                   view=UnitView.CHORD)
    assert sent(effects) == [NoteOn(2, 60, 80), NoteOn(2, 64, 80), NoteOn(2, 67, 80),
                             PolyAftertouch(2, 60, 20), PolyAftertouch(2, 64, 20), PolyAftertouch(2, 67, 20)]


def test_step_and_drum_views_route_by_port_like_note_view():   # A106, A109
    assert sent(play(router(notes_rule(channel=2)), NoteOn(1, 41, 18), view=UnitView.STEP)) == [NoteOn(2, 41, 18)]
    assert sent(play(router(notes_rule(channel=10)), NoteOn(1, 38, 90), view=UnitView.DRUM)) == [NoteOn(10, 38, 90)]


def test_custom_view_notes_and_strip_ccs_follow_the_custom_rule():   # A107, A108, d132
    r = router(RoutingRule(CUSTOM, "mpc", 3))
    effects = play(r, NoteOn(1, 36, 11), ControlChange(1, 20, 64), role=CUSTOM, view=UnitView.CUSTOM)
    assert sent(effects) == [NoteOn(3, 36, 11), ControlChange(3, 20, 64)]
    assert sent(play(r, NoteOn(1, 36, 11))) == []   # the Notes port has no rule here


def test_every_aftertouch_value_is_forwarded_in_order():   # A110, d134
    r = router(notes_rule(channel=2))
    values = [(i * 7) % 128 for i in range(200)]
    effects = play(r, NoteOn(1, 53, 70), *[PolyAftertouch(1, 53, v) for v in values])
    assert [m.pressure for m in sent(effects) if isinstance(m, PolyAftertouch)] == values


def test_a_velocity_zero_note_on_ends_the_note():   # A111, d135
    r = router(notes_rule(channel=2))
    assert sent(play(r, NoteOn(1, 53, 56), NoteOn(1, 53, 0))) == [NoteOn(2, 53, 56), NoteOff(2, 53)]


def test_overlapping_note_ons_are_forwarded_as_received():   # A112, d136
    r = router(notes_rule(channel=2))
    effects = play(r, NoteOn(1, 60, 80), NoteOn(1, 60, 90), view=UnitView.CHORD)
    assert sent(effects) == [NoteOn(2, 60, 80), NoteOn(2, 60, 90)]


def test_a_note_off_reuses_its_note_ons_transform_after_the_rule_changed():   # A113, d137
    r = router(notes_rule(channel=2, transpose=12))
    assert sent(play(r, NoteOn(1, 53, 56))) == [NoteOn(2, 65, 56)]
    r.set_layout(layout(routing=[notes_rule(channel=2, transpose=0)]))
    assert sent(play(r, NoteOff(1, 53))) == [NoteOff(2, 65)]
    assert sent(play(r, NoteOn(1, 53, 56))) == [NoteOn(2, 53, 56)]


def test_without_a_routing_rule_nothing_is_sent_and_the_note_still_shows():   # A115, d143
    r = router()
    effects = play(r, NoteOn(1, 53, 56))
    assert sent(effects) == []
    assert [e.event.reason for e in effects if isinstance(e, Play)] == [NOT_ROUTED]
    assert NOT_ROUTED == "expressive pads not routed in this layout"
    playing = r.sounding()
    assert [(p.note, p.velocity, p.routed) for p in playing] == [(53, 56, False)]
    play(r, NoteOff(1, 53))
    assert r.sounding() == ()


def test_a_note_transposed_out_of_range_is_dropped_and_listed():   # A116, d144
    r = router(notes_rule(channel=2, transpose=24))
    effects = play(r, NoteOn(1, 120, 70), PolyAftertouch(1, 120, 5), NoteOff(1, 120))
    assert sent(effects) == []
    entries = [e.entry for e in effects if isinstance(e, Activity)]
    assert [(e.result, e.reason) for e in entries] == [("dropped", "note 144 out of range")]


def test_remap_applies_to_listed_notes_and_others_pass_through():   # A117, d145
    r = router(notes_rule(channel=2, remap=((36, 38),)))
    assert sent(play(r, NoteOn(1, 36, 50), NoteOn(1, 40, 50))) == [NoteOn(2, 38, 50), NoteOn(2, 40, 50)]


def test_routing_ignores_pages_and_banks():   # A118, d146
    r = router(notes_rule(channel=2))
    assert sent(play(r, NoteOn(1, 53, 40))) == [NoteOn(2, 53, 40)]


def test_the_played_notes_row_holds_the_latest_aftertouch():   # q7, inv7
    r = router(notes_rule(channel=2))
    play(r, NoteOn(1, 53, 56), PolyAftertouch(1, 53, 33))
    assert [(p.note, p.velocity, p.aftertouch) for p in r.sounding()] == [(53, 56, 33)]


def test_replaying_the_same_performance_routes_identically():   # A119, inv10
    def performance():
        r = router(notes_rule(channel=2, aftertouch=AftertouchPolicy.CHANNEL_PRESSURE, transpose=-3))
        messages = []
        for n in range(30):
            messages += [NoteOn(1, 40 + n % 12, 10 + n), PolyAftertouch(1, 40 + n % 12, n * 3 % 128)]
            if n % 3:
                messages.append(NoteOff(1, 40 + (n - 1) % 12))
        return play(r, *messages)
    assert performance() == performance()
