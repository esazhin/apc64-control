"""The WebSocket hub (contract s12, s14, s26–s28, s30, s31; d151, d159, d160).

/ws (the page): on every (re)connect the current snapshot first, then the newest activity (newest first), then a
diff after every state change and each new or updated (aftertouch-folded) activity entry, in order. A page that
stops reading for long (a phone asleep) is not allowed to pile up messages: past BACKLOG queued messages the
queue is replaced by one fresh snapshot and activity list, so it catches up at once when it reads again.

/ws/play (agents): play events from the moment of connecting, one JSON message each, in order. A watcher that
falls more than 5 s behind is closed by the play stream; the hub sends {type:'closed', reason:'too slow'} and
closes the socket. The unit and the other watchers are unaffected (A124).

Contract 2 (T18, s24/s25): publish(topic, payload) sends {type:'topic', topic, data} to every /ws page, from any
thread. The hub keeps the latest payload per topic and kind (payload['kind'], e.g. 'lab' and 'harmony'), and a
page that (re)connects gets those right after its snapshot and activity list, then each new one in publish order.
With nothing published, /ws is exactly contract 1's stream.

Subscription callbacks run inside engine/session handling, so they only queue (never await). A callback from
another thread is handed to the socket's loop.
"""
import asyncio
import contextlib
import logging
import threading
from enum import StrEnum

from ..application.play_stream import StreamClosed
from . import view_model as _view_model

log = logging.getLogger(__name__)
BACKLOG = 2000
CLOSE_NORMAL, CLOSE_TOO_SLOW = 1000, 4000


class Channel(StrEnum):
    STATE = "state"
    PLAY = "play"


class _Outbox:
    """A per-socket message queue that may be filled from the loop or from another thread."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.queue: asyncio.Queue = asyncio.Queue()

    def put(self, item) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self.queue.put_nowait(item)
        else:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, item)


class WebSocketHub:
    def __init__(self, state_view, activity, stream, view_model=_view_model, backlog: int = BACKLOG):
        self._state, self._activity, self._stream = state_view, activity, stream
        self._vm = view_model
        self._backlog = backlog
        self.connected = {Channel.STATE: 0, Channel.PLAY: 0}
        self._topics_lock = threading.Lock()
        self._retained: dict[tuple[str, object], object] = {}   # (topic, kind) → latest payload, oldest first
        self._pages: list[_Outbox] = []

    # --- topics (contract 2) ----------------------------------------------------------------------------
    def publish(self, topic: str, payload) -> None:
        """To every page now, and kept (latest per topic and kind) for pages that connect later (s24.c2)."""
        topic = str(topic)
        key = (topic, payload.get("kind") if isinstance(payload, dict) else None)
        with self._topics_lock:
            self._retained.pop(key, None)
            self._retained[key] = payload
            pages = list(self._pages)
        for outbox in pages:
            outbox.put(("topic", (topic, payload)))

    def current(self, topic: str, kind=None):
        """The latest payload published on topic (of that kind), or None."""
        with self._topics_lock:
            return self._retained.get((str(topic), kind))

    def _retained_items(self) -> list:
        return [("topic", (topic, payload)) for (topic, _), payload in self._retained.items()]

    async def accept(self, ws, channel) -> None:
        """Owns the socket until either side closes (s12.c2)."""
        channel = Channel(channel)
        await ws.accept()
        self.connected[channel] += 1
        try:
            if channel is Channel.STATE:
                await self._serve_state(ws)
            else:
                await self._serve_play(ws)
        finally:
            self.connected[channel] -= 1

    # --- /ws ------------------------------------------------------------------------------------------
    async def _serve_state(self, ws) -> None:
        outbox = _Outbox(asyncio.get_running_loop())
        state_token = activity_token = None
        try:
            state_token = self._state.subscribe(lambda item: outbox.put(("state", item)))   # snapshot first
            outbox.put(("activity_list", self._activity.records()))
            activity_token = self._activity.subscribe(lambda record: outbox.put(("activity", record)))
            with self._topics_lock:                 # the retained topics, then every new one: none lost or doubled
                for item in self._retained_items():
                    outbox.put(item)
                self._pages.append(outbox)
            await _until_either(self._send_state(ws, outbox), _drain_client(ws))
        finally:
            with self._topics_lock:
                if outbox in self._pages:
                    self._pages.remove(outbox)
            if state_token is not None:
                self._state.unsubscribe(state_token)
            if activity_token is not None:
                self._activity.unsubscribe(activity_token)

    async def _send_state(self, ws, outbox: _Outbox) -> None:
        while True:
            if outbox.queue.qsize() > self._backlog:
                _clear(outbox.queue)
                outbox.queue.put_nowait(("state", self._state.snapshot()))
                outbox.queue.put_nowait(("activity_list", self._activity.records()))
                with self._topics_lock:
                    for retained in self._retained_items():
                        outbox.queue.put_nowait(retained)
            kind, item = await outbox.queue.get()
            if kind == "state":
                message = self._vm.state_message(item)
            elif kind == "activity":
                message = self._vm.activity_message(item)
            elif kind == "topic":
                message = _topic_message(self._vm, *item)
            else:
                message = self._vm.activity_list_message(item)
            await ws.send_json(message)

    # --- /ws/play -------------------------------------------------------------------------------------
    async def _serve_play(self, ws) -> None:
        subscription = self._stream.subscribe()
        try:
            await _until_either(self._send_play(ws, subscription), _drain_client(ws))
        finally:
            subscription.cancel()

    async def _send_play(self, ws, subscription) -> None:
        while True:
            item = await subscription.next()
            if isinstance(item, StreamClosed):
                with contextlib.suppress(Exception):
                    await ws.send_json(self._vm.closed_message(item.reason))
                    await ws.close(code=CLOSE_TOO_SLOW if item.reason == "too slow" else CLOSE_NORMAL,
                                   reason=f"stream closed: {item.reason}")
                return
            await ws.send_json(self._vm.play_message(item))


def _topic_message(vm, topic: str, payload) -> dict:
    shape = getattr(vm, "topic_message", None)
    return shape(topic, payload) if shape is not None else {"type": "topic", "topic": topic, "data": payload}


def _clear(queue: asyncio.Queue) -> None:
    while not queue.empty():
        queue.get_nowait()


async def _drain_client(ws) -> None:
    """Reads (and ignores) what the client sends, until it disconnects."""
    while True:
        message = await ws.receive()
        if message.get("type") == "websocket.disconnect":
            return


async def _until_either(*coroutines) -> None:
    """Runs both; when one ends (or fails, e.g. a send to a closed socket) the other is cancelled."""
    tasks = [asyncio.ensure_future(c) for c in coroutines]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            error = task.exception()
            if error is not None and not _is_disconnect(error):
                log.warning("websocket ended: %r", error)
    finally:
        for task in tasks:
            task.cancel()
        # asyncio.wait, not gather: if this task is cancelled again while it waits (the server or the test
        # client's cancel scope re-delivers its cancellation), wait raises the canceller's own CancelledError.
        # gather would raise the children's anonymous one instead, which the canceller does not recognise as
        # its own and re-raises (the intermittent CancelledError at a TestClient socket's close).
        await asyncio.wait(tasks)


def _is_disconnect(error: BaseException) -> bool:
    return type(error).__name__ in ("WebSocketDisconnect", "ConnectionClosed", "ConnectionClosedOK",
                                    "ConnectionClosedError", "ClientDisconnected")
