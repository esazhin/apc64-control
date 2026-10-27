"""PlayStream: the agents' ordered stream of what is played and pressed (contract d150–d154, s28, s48, s73).

Every watcher gets the same events in the same order, from the moment it subscribes (no history). Publish
never blocks: each watcher has its own bounded queue, and a watcher whose oldest undelivered event is more
than 5 s old (or whose queue overflows) is closed with StreamClosed('too slow'); the others carry on.
Publish and the watchers' reads run on the engine's event loop.

Contract 2 (s19, s20): every event carries its source (PlayEvent.port, a PlaySource: the APC64's Custom or
Notes port, a Session-view binding, or any other MIDI input by name, §2.7 q7), and the host's ending of a held
note at a window shift is the kind NOTE_ENDED with reason ENDED_BY_WINDOW_SHIFT. Any part of the host (or a
module) may publish; watchers see one order.
"""
import asyncio
from collections import deque
from dataclasses import dataclass

from ..domain.effects import ENDED_BY_WINDOW_SHIFT, NOTE_ENDED, PlayEvent, PlaySource, PlaySourceKind  # noqa: F401
from .ports import Clock

MAX_LAG = 5.0
MAX_QUEUE = 20000
TOO_SLOW = "too slow"


@dataclass(frozen=True)
class StreamClosed:
    reason: str


class PlaySubscription:
    def __init__(self, stream: "PlayStream"):
        self._stream = stream
        self._queue: deque[tuple[float, PlayEvent]] = deque()
        self._closing: StreamClosed | None = None   # delivered once, after the pending events
        self.closed: str | None = None
        self._wake: asyncio.Event | None = None

    def take(self) -> list[PlayEvent | StreamClosed]:
        """Everything pending, without waiting; a close notice comes last, once."""
        items: list = [event for _, event in self._queue]
        self._queue.clear()
        if self._closing is not None:
            items.append(self._closing)
            self._closing = None
        return items

    async def next(self) -> PlayEvent | StreamClosed:
        while True:
            if self._queue:
                return self._queue.popleft()[1]
            if self._closing is not None:
                closing, self._closing = self._closing, None
                return closing
            if self.closed is not None:
                return StreamClosed(self.closed)
            if self._wake is None:
                self._wake = asyncio.Event()
            self._wake.clear()
            await self._wake.wait()

    def cancel(self) -> None:
        self._stream._drop(self)
        self._close("unsubscribed", keep_pending=False)

    # --- the stream's side ------------------------------------------------------------------------------
    def _offer(self, now: float, event: PlayEvent, max_lag: float, max_queue: int) -> bool:
        """Queues the event; False when the watcher is too slow (it is then closed)."""
        if self._queue and (now - self._queue[0][0] > max_lag or len(self._queue) >= max_queue):
            self._close(TOO_SLOW, keep_pending=True)
            return False
        self._queue.append((now, event))
        self._signal()
        return True

    def _close(self, reason: str, keep_pending: bool) -> None:
        if self.closed is not None:
            return
        self.closed = reason
        if not keep_pending:
            self._queue.clear()
        self._closing = StreamClosed(reason)
        self._signal()

    def _signal(self) -> None:
        if self._wake is not None:
            self._wake.set()


class PlayStream:
    def __init__(self, clock: Clock, max_lag: float = MAX_LAG, max_queue: int = MAX_QUEUE):
        self._clock = clock
        self._max_lag, self._max_queue = max_lag, max_queue
        self._subscribers: list[PlaySubscription] = []

    @property
    def watchers(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> PlaySubscription:
        subscription = PlaySubscription(self)
        self._subscribers.append(subscription)
        return subscription

    def publish(self, event: PlayEvent) -> None:
        now = self._clock.monotonic()
        for subscription in list(self._subscribers):
            if not subscription._offer(now, event, self._max_lag, self._max_queue):
                self._drop(subscription)

    def _drop(self, subscription: PlaySubscription) -> None:
        if subscription in self._subscribers:
            self._subscribers.remove(subscription)
