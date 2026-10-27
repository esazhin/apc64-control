"""Contract 2 T11: play-stream event kinds and the source port (inv15; s19 and s20 suppliers; §2.7 q7)."""
import asyncio

import pytest

from _apc64_host.application.conftest import ManualClock
from _apc64_host.application.play_stream import (
    ENDED_BY_WINDOW_SHIFT, NOTE_ENDED, PlayStream, PlaySource, PlaySourceKind, StreamClosed,
)
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.effects import PlayEvent
from _apc64_host.domain.layout import UnitPortRole
from _apc64_host.presentation import view_model


def test_a_subscriber_gets_custom_notes_session_binding_and_ended_events_in_order_with_source_and_kind():
    # T11, s19.c2, s20.c1
    stream = PlayStream(ManualClock())
    watcher = stream.subscribe()
    published = [
        PlayEvent("note_on", note=48, velocity=38, port=PlaySource.of_role(UnitPortRole.CUSTOM)),
        PlayEvent("note_on", note=57, velocity=90, port=PlaySource.of_role(UnitPortRole.NOTES)),
        PlayEvent("press", control=PadPos(1, 1), velocity=127, port=PlaySource.of_role(UnitPortRole.DAW)),
        PlayEvent(NOTE_ENDED, note=48, reason=ENDED_BY_WINDOW_SHIFT, port=PlaySource.of_role(UnitPortRole.CUSTOM)),
    ]
    for event in published:
        stream.publish(event)
    got = watcher.take()
    assert got == published
    assert [(e.kind, e.port.kind) for e in got] == [
        ("note_on", PlaySourceKind.CUSTOM), ("note_on", PlaySourceKind.NOTES),
        ("press", PlaySourceKind.SESSION_BINDING), ("note_ended", PlaySourceKind.CUSTOM)]
    assert [str(e.port) for e in got] == ["APC64 Custom", "APC64 Notes", "APC64 DAW", "APC64 Custom"]
    assert [e.port.played for e in got] == [True, True, False, True]


def test_any_other_midi_input_is_a_named_source():
    # §2.7 q7: the harmony views follow any chosen input (a keyboard, the MPC), so the source names it
    stream = PlayStream(ManualClock())
    watcher = stream.subscribe()
    stream.publish(PlayEvent("note_on", note=60, velocity=70, port=PlaySource.input("MPC Live III MIDI 1")))
    (event,) = watcher.take()
    assert event.port == PlaySource(PlaySourceKind.INPUT, "MPC Live III MIDI 1") and event.port.played
    with pytest.raises(ValueError):
        PlaySource(PlaySourceKind.INPUT)


def test_slow_watchers_are_still_closed_whatever_the_source():
    clock = ManualClock()
    stream = PlayStream(clock, max_lag=5.0)
    slow, fast = stream.subscribe(), stream.subscribe()
    stream.publish(PlayEvent("note_on", note=48, port=PlaySource.input("Keys")))
    fast.take()
    clock.advance(6)
    stream.publish(PlayEvent("note_off", note=48, port=PlaySource.input("Keys")))
    assert isinstance(slow.take()[-1], StreamClosed)
    assert [e.kind for e in fast.take()] == ["note_off"]


def test_contract1_play_json_is_unchanged_by_the_source():
    # contract 1's /ws/play shape stays as built: the source is for in-process subscribers (the lab)
    event = PlayEvent("note_on", note=48, velocity=38, port=PlaySource.of_role(UnitPortRole.CUSTOM))
    assert view_model.play_json(event) == view_model.play_json(PlayEvent("note_on", note=48, velocity=38))


def test_events_reach_an_awaiting_watcher_in_order():
    async def scenario():
        stream = PlayStream(ManualClock())
        watcher = stream.subscribe()
        waiting = asyncio.ensure_future(watcher.next())
        await asyncio.sleep(0)
        stream.publish(PlayEvent(NOTE_ENDED, note=41, reason=ENDED_BY_WINDOW_SHIFT))
        first = await waiting
        return first
    assert asyncio.run(scenario()).kind == "note_ended"
