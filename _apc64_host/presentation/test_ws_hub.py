"""s12/s30/s31 supplier and s14/s26/s27/s28 collaboration: the WebSocket hub (T31; A130, A131, A124)."""
import asyncio
from types import SimpleNamespace

from _apc64_host.application.activity import ActivityLog
from _apc64_host.application.conftest import ManualClock
from _apc64_host.application.play_stream import PlayStream
from _apc64_host.domain.effects import ActivityEntry, ActivityResult, PlayEvent
from _apc64_host.presentation import view_model
from _apc64_host.presentation.ws_hub import CLOSE_TOO_SLOW, Channel, WebSocketHub


class FakeSocket:
    def __init__(self):
        self.accepted = False
        self.sent = []
        self.closed = None
        self.incoming = asyncio.Queue()
        self.stall = asyncio.Event()
        self.stall.set()                     # set = reading normally

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        await self.stall.wait()
        self.sent.append(message)

    async def receive(self):
        return await self.incoming.get()

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)

    def disconnect(self):
        self.incoming.put_nowait({"type": "websocket.disconnect"})


class StateDouble:
    """StateView double: subscribe gives the snapshot now, emit() sends a diff to every subscriber."""

    def __init__(self):
        self.current = {"snapshot": 1}
        self.subscribers = {}
        self.next = 1

    def snapshot(self):
        return dict(self.current)

    def subscribe(self, callback):
        token, self.next = self.next, self.next + 1
        self.subscribers[token] = callback
        callback(self.snapshot())
        return token

    def unsubscribe(self, token):
        self.subscribers.pop(token)

    def emit(self, diff):
        self.current = {"snapshot": self.current["snapshot"] + 1}
        for callback in list(self.subscribers.values()):
            callback(diff)


# the view_model double (s14 collaboration): canned shapes that show which function framed which item
VM = SimpleNamespace(
    state_message=lambda item: {"type": "snapshot" if "snapshot" in item else "diff", "data": item},
    activity_message=lambda record: {"type": "activity", "data": record.entry.subject},
    activity_list_message=lambda records: {"type": "activity_list", "data": [r.entry.subject for r in records]},
    play_message=lambda event: {"type": "event", "data": event.kind},
    closed_message=lambda reason: {"type": "closed", "reason": reason},
)


async def settle():
    for _ in range(20):
        await asyncio.sleep(0)


def rig(**kwargs):
    state, activity, clock = StateDouble(), ActivityLog(), ManualClock()
    stream = PlayStream(clock)
    return state, activity, stream, clock, WebSocketHub(state, activity, stream, view_model=VM, **kwargs)


def test_a_page_gets_the_snapshot_first_then_activity_then_diffs_and_again_after_a_reconnect():
    async def scenario():
        state, activity, _, _, hub = rig()
        activity.append(ActivityEntry("pad r1c1", ActivityResult.SENT))
        page = FakeSocket()
        task = asyncio.ensure_future(hub.accept(page, Channel.STATE))
        await settle()
        assert page.accepted and hub.connected[Channel.STATE] == 1
        assert page.sent[:2] == [{"type": "snapshot", "data": {"snapshot": 1}},
                                 {"type": "activity_list", "data": ["pad r1c1"]}]
        state.emit({"changed": {"bank": 3}})
        activity.append(ActivityEntry("track 1", ActivityResult.SENT))
        await settle()
        assert page.sent[2:] == [{"type": "diff", "data": {"changed": {"bank": 3}}},
                                 {"type": "activity", "data": "track 1"}]
        # A131: the connection drops while the bank changes; the page reconnects and sees bank 3 at once
        page.disconnect()
        await task
        assert state.subscribers == {} and hub.connected[Channel.STATE] == 0
        state.emit({"changed": {"bank": 3}})
        again = FakeSocket()
        task = asyncio.ensure_future(hub.accept(again, Channel.STATE))
        await settle()
        assert again.sent[0] == {"type": "snapshot", "data": {"snapshot": 3}}
        assert again.sent[1] == {"type": "activity_list", "data": ["track 1", "pad r1c1"]}
        again.disconnect()
        await task
    asyncio.run(scenario())


def test_two_pages_receive_the_same_diff():
    async def scenario():
        state, _, _, _, hub = rig()
        phone, laptop = FakeSocket(), FakeSocket()
        tasks = [asyncio.ensure_future(hub.accept(s, Channel.STATE)) for s in (phone, laptop)]
        await settle()
        state.emit({"changed": {"page": 2}})          # A130: page 2 tapped on the phone
        await settle()
        assert phone.sent[-1] == laptop.sent[-1] == {"type": "diff", "data": {"changed": {"page": 2}}}
        for socket in (phone, laptop):
            socket.disconnect()
        await asyncio.gather(*tasks)
    asyncio.run(scenario())


def test_a_page_that_stops_reading_catches_up_with_one_fresh_snapshot():
    async def scenario():
        state, _, _, _, hub = rig(backlog=3)
        page = FakeSocket()
        task = asyncio.ensure_future(hub.accept(page, Channel.STATE))
        await settle()
        page.stall.clear()                            # the phone went to sleep
        for n in range(10):
            state.emit({"changed": {"n": n}})
        await settle()
        page.stall.set()
        await settle()
        types = [m["type"] for m in page.sent]
        assert types.count("snapshot") == 2 and len(page.sent) < 10
        assert page.sent[-2] == {"type": "snapshot", "data": {"snapshot": 11}}
        page.disconnect()
        await task
    asyncio.run(scenario())


def test_an_agent_gets_play_events_in_order_and_a_closed_notice_when_too_slow():
    async def scenario():
        _, _, stream, clock, hub = rig()
        agent, other = FakeSocket(), FakeSocket()
        tasks = [asyncio.ensure_future(hub.accept(s, Channel.PLAY)) for s in (agent, other)]
        await settle()
        stream.publish(PlayEvent("press"))
        stream.publish(PlayEvent("release"))
        await settle()
        assert agent.sent == other.sent == [{"type": "event", "data": "press"}, {"type": "event", "data": "release"}]
        agent.stall.clear()                           # A124: the agent stops reading
        stream.publish(PlayEvent("press"))
        await settle()
        for _ in range(3):
            clock.advance(3.0)
            stream.publish(PlayEvent("move"))
            await settle()
        agent.stall.set()
        await asyncio.wait_for(tasks[0], 1)
        assert agent.sent[-1] == {"type": "closed", "reason": "too slow"}
        assert agent.closed == (CLOSE_TOO_SLOW, "stream closed: too slow")
        assert [m["data"] for m in other.sent] == ["press", "release", "press", "move", "move", "move"]
        assert not tasks[1].done()                    # the other watcher carries on
        other.disconnect()
        await tasks[1]
        assert stream.watchers == 0
    asyncio.run(scenario())


def test_the_real_view_model_frames_play_events_and_the_closed_notice():
    async def scenario():
        state, activity, stream, clock, _ = rig()
        hub = WebSocketHub(state, activity, stream, view_model=view_model)
        agent = FakeSocket()
        task = asyncio.ensure_future(hub.accept(agent, "play"))
        await settle()
        stream.publish(PlayEvent("press", velocity=127, at=1.0))
        await settle()
        assert agent.sent[0]["type"] == "event" and agent.sent[0]["data"]["velocity"] == 127
        agent.disconnect()
        await task
    asyncio.run(scenario())


def test_callbacks_from_another_thread_reach_the_socket():
    async def scenario():
        state, _, _, _, hub = rig()
        page = FakeSocket()
        task = asyncio.ensure_future(hub.accept(page, Channel.STATE))
        await settle()
        await asyncio.get_running_loop().run_in_executor(None, state.emit, {"changed": {"x": 1}})
        for _ in range(200):
            if page.sent and page.sent[-1]["data"] == {"changed": {"x": 1}}:
                break
            await asyncio.sleep(0.005)
        assert page.sent[-1] == {"type": "diff", "data": {"changed": {"x": 1}}}
        page.disconnect()
        await task
    asyncio.run(scenario())
