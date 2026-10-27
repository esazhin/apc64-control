import asyncio
import threading
import time

from _apc64_host.application.ports import Cancellable, Clock
from _apc64_host.infrastructure.clock import AsyncioClock


def test_call_later_fires_after_the_delay_and_a_cancelled_handle_never_fires():
    # T11, s41/s52/s62/s73 supplier side, s87: loop.call_later and time.monotonic
    clock = AsyncioClock()
    assert isinstance(clock, Clock)

    async def scenario():
        fired = []
        started = clock.monotonic()
        live = clock.call_later(0.25, lambda: fired.append(("live", clock.monotonic() - started)))
        dead = clock.call_later(0.05, lambda: fired.append(("cancelled", 0)))
        assert isinstance(live, Cancellable) and isinstance(dead, Cancellable)
        dead.cancel()
        dead.cancel()   # cancelling twice is harmless
        await asyncio.sleep(0.35)
        return fired

    fired = asyncio.run(scenario())
    assert [name for name, _ in fired] == ["live"]
    assert fired[0][1] >= 0.25


def test_monotonic_increases():
    clock = AsyncioClock()
    readings = [clock.monotonic() for _ in range(1000)]
    assert readings == sorted(readings) and all(isinstance(r, float) for r in readings)
    first = clock.monotonic()
    time.sleep(0.01)
    assert clock.monotonic() > first


def test_call_later_from_another_thread_runs_on_the_loop_and_can_be_cancelled_before_it_is_scheduled():
    # adapter threads (rawmidi readers, inotify, sequencer) may ask for a timer; the callback runs on the loop
    async def scenario():
        clock = AsyncioClock()
        clock.bind(asyncio.get_running_loop())
        loop_thread = threading.get_ident()
        ran_on = []
        handles = {}

        def from_thread():
            handles["live"] = clock.call_later(0.02, lambda: ran_on.append(threading.get_ident()))
            cancelled = clock.call_later(0.02, lambda: ran_on.append("cancelled"))
            cancelled.cancel()

        worker = threading.Thread(target=from_thread)
        worker.start()
        worker.join()
        await asyncio.sleep(0.1)
        return loop_thread, ran_on

    loop_thread, ran_on = asyncio.run(scenario())
    assert ran_on == [loop_thread]


def test_the_clock_binds_to_the_running_loop_on_first_use():
    clock = AsyncioClock()

    async def first():
        fired = asyncio.Event()
        clock.call_later(0, fired.set)
        await asyncio.wait_for(fired.wait(), 1)
        return True

    assert asyncio.run(first())
