import asyncio

from _apc64_host.application.conftest import ManualClock, run
from _apc64_host.application.play_stream import PlayStream, StreamClosed
from _apc64_host.domain.controls import PadPos, TrackButton
from _apc64_host.domain.effects import PlayEvent


def press(control):
    return PlayEvent("press", control=control, velocity=127)


def test_two_watchers_receive_the_same_events_in_the_same_order():   # A125
    stream = PlayStream(ManualClock())
    a, b = stream.subscribe(), stream.subscribe()
    stream.publish(press(PadPos(1, 1)))
    stream.publish(press(TrackButton(1)))
    assert [e.control for e in a.take()] == [PadPos(1, 1), TrackButton(1)]
    assert [e.control for e in b.take()] == [PadPos(1, 1), TrackButton(1)]


def test_a_watcher_starts_from_now():   # A126
    stream = PlayStream(ManualClock())
    for n in range(1, 9):
        stream.publish(press(TrackButton(n)))
    late = stream.subscribe()
    stream.publish(press(PadPos(1, 1)))
    assert [e.control for e in late.take()] == [PadPos(1, 1)]


def test_a_stalled_watcher_is_closed_too_slow_after_5_s_and_others_carry_on():   # A124, s73
    clock = ManualClock()
    stream = PlayStream(clock)
    reader, stalled = stream.subscribe(), stream.subscribe()
    for second in range(7):
        stream.publish(press(PadPos(1, 1)))
        assert len(reader.take()) == 1
        clock.advance(1.0)
    items = stalled.take()
    assert isinstance(items[-1], StreamClosed) and items[-1].reason == "too slow"
    assert all(not isinstance(i, StreamClosed) for i in items[:-1]) and 5 <= len(items) - 1 <= 7
    assert stalled.closed == "too slow" and stalled.take() == []
    stream.publish(press(TrackButton(1)))
    assert [e.control for e in reader.take()] == [TrackButton(1)]
    assert stream.watchers == 1


def test_next_waits_for_an_event_and_cancel_unsubscribes():
    async def scenario():
        stream = PlayStream(ManualClock())
        sub = stream.subscribe()
        waiter = asyncio.ensure_future(sub.next())
        await asyncio.sleep(0)
        assert not waiter.done()
        stream.publish(press(PadPos(2, 1)))
        event = await asyncio.wait_for(waiter, 1)
        sub.cancel()
        stream.publish(press(PadPos(3, 1)))
        return event, stream.watchers, await sub.next()

    event, watchers, after = run(scenario())
    assert event.control == PadPos(2, 1) and watchers == 0
    assert isinstance(after, StreamClosed) and after.reason == "unsubscribed"


def test_publish_stamps_nothing_and_never_blocks_with_a_huge_backlog():   # s48.c2
    stream = PlayStream(ManualClock(), max_queue=100)
    stalled = stream.subscribe()
    for _ in range(1000):
        stream.publish(press(PadPos(1, 1)))
    items = stalled.take()
    assert isinstance(items[-1], StreamClosed) and items[-1].reason == "too slow" and len(items) == 101
