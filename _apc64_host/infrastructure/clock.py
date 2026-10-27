"""The real Clock (application/ports.py): time.monotonic and timers on the asyncio loop (contract s87).

call_later may be called from the loop or from any adapter thread; the callback always runs on the loop.
The loop is the one bound with bind(), or else the loop running at the first call.
"""
import asyncio
import threading
import time
from typing import Callable


class _Handle:
    """A timer that can be cancelled before or after it reaches the loop."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cancelled = False
        self._timer: asyncio.TimerHandle | None = None

    def _schedule(self, loop: asyncio.AbstractEventLoop, seconds: float, callback: Callable[[], None]) -> None:
        with self._lock:
            if not self._cancelled:
                self._timer = loop.call_later(seconds, callback)

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            if self._timer is not None:
                self._timer.cancel()


class AsyncioClock:
    def __init__(self, loop: asyncio.AbstractEventLoop | None = None):
        self._loop = loop

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def monotonic(self) -> float:
        return time.monotonic()

    def call_later(self, seconds: float, callback: Callable[[], None]) -> _Handle:
        loop = self._current_loop()
        handle = _Handle()
        if self._on_loop_thread(loop):
            handle._schedule(loop, seconds, callback)
        else:
            loop.call_soon_threadsafe(handle._schedule, loop, seconds, callback)
        return handle

    def _current_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.get_running_loop()
        return self._loop

    @staticmethod
    def _on_loop_thread(loop: asyncio.AbstractEventLoop) -> bool:
        try:
            return asyncio.get_running_loop() is loop
        except RuntimeError:
            return False
