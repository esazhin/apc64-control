"""Contract 2 T18: WebSocket hub topics (inv15, pi7; s24 and s25 suppliers; A79), and the socket-teardown fix
behind contract 1's intermittent test_the_last_switch_wins_for_everyone."""
import asyncio
import threading

from _apc64_host.application.ports import TopicPublisher
from _apc64_host.presentation import view_model
from _apc64_host.presentation.test_ws_hub import FakeSocket, rig, settle
from _apc64_host.presentation.ws_hub import Channel, WebSocketHub, _until_either

LAB = {"kind": "lab", "active": {"layout": "Tonnetz C", "interval": "5th", "counts": {"fifth": 2}}}
HARMONY_C = {"kind": "harmony", "held": [48, 52, 55], "chord": "C"}
HARMONY_AM = {"kind": "harmony", "held": [45, 48, 52], "chord": "Am"}


def topics(socket):
    return [m for m in socket.sent if m.get("type") == "topic"]


def test_a79_a_new_tab_gets_the_current_lab_and_harmony_snapshots_first_then_updates_in_order():
    async def scenario():
        state, _, _, _, hub = rig()
        assert isinstance(hub, TopicPublisher)
        hub.publish("lab", LAB)
        hub.publish("lab", {"kind": "harmony", "held": [48], "chord": "—"})
        hub.publish("lab", HARMONY_C)                          # the user is holding C E G
        tab = FakeSocket()
        task = asyncio.ensure_future(hub.accept(tab, Channel.STATE))
        await settle()
        assert [m["type"] for m in tab.sent] == ["snapshot", "activity_list", "topic", "topic"]
        assert topics(tab) == [{"type": "topic", "topic": "lab", "data": LAB},
                               {"type": "topic", "topic": "lab", "data": HARMONY_C}]   # chord 'C' at once
        hub.publish("lab", HARMONY_AM)
        state.emit({"changed": {"page": 2}})
        hub.publish("lab", {**LAB, "active": {"layout": "Fourths"}})
        await settle()
        assert [m.get("data", {}).get("chord") or m["type"] for m in tab.sent[4:]] == ["Am", "diff", "topic"]
        assert hub.current("lab", "harmony") == HARMONY_AM and hub.current("lab", "lab")["active"]["layout"] == "Fourths"
        tab.disconnect()
        await task
    asyncio.run(scenario())


def test_two_pages_get_each_publish_and_a_closed_page_gets_nothing_more():
    async def scenario():
        _, _, _, _, hub = rig()
        phone, laptop = FakeSocket(), FakeSocket()
        tasks = [asyncio.ensure_future(hub.accept(s, Channel.STATE)) for s in (phone, laptop)]
        await settle()
        hub.publish("lab", HARMONY_C)
        await settle()
        assert topics(phone) == topics(laptop) == [{"type": "topic", "topic": "lab", "data": HARMONY_C}]
        phone.disconnect()
        await tasks[0]
        hub.publish("lab", HARMONY_AM)
        await settle()
        assert len(topics(phone)) == 1 and len(topics(laptop)) == 2
        laptop.disconnect()
        await tasks[1]
    asyncio.run(scenario())


def test_a_publish_from_another_thread_reaches_the_page():
    async def scenario():
        _, _, _, _, hub = rig()
        page = FakeSocket()
        task = asyncio.ensure_future(hub.accept(page, Channel.STATE))
        await settle()
        thread = threading.Thread(target=hub.publish, args=("lab", HARMONY_C))
        thread.start()
        thread.join()
        for _ in range(50):
            await asyncio.sleep(0.001)
            if topics(page):
                break
        assert topics(page) == [{"type": "topic", "topic": "lab", "data": HARMONY_C}]
        page.disconnect()
        await task
    asyncio.run(scenario())


def test_a_page_that_catches_up_gets_the_retained_topics_again():
    async def scenario():
        state, _, _, _, hub = rig(backlog=3)
        page = FakeSocket()
        task = asyncio.ensure_future(hub.accept(page, Channel.STATE))
        await settle()
        page.stall.clear()
        for n in range(10):
            hub.publish("lab", {"kind": "harmony", "held": [n]})
        await settle()
        page.stall.set()
        await settle()
        assert topics(page)[-1]["data"] == {"kind": "harmony", "held": [9]}
        page.disconnect()
        await task
    asyncio.run(scenario())


def test_without_topics_the_page_stream_is_contract_1s():
    async def scenario():
        _, _, _, _, hub = rig()
        page = FakeSocket()
        task = asyncio.ensure_future(hub.accept(page, Channel.STATE))
        await settle()
        assert [m["type"] for m in page.sent] == ["snapshot", "activity_list"]
        page.disconnect()
        await task
    asyncio.run(scenario())


def test_the_view_model_shapes_a_topic_message():
    assert view_model.topic_message("lab", HARMONY_C) == {"type": "topic", "topic": "lab", "data": HARMONY_C}


# --- the flaky contract 1 test: the cause was in _until_either ------------------------------------------------
def test_a_cancellation_repeated_during_cleanup_propagates_the_cancellers_own_error():
    """The server (or the test client's cancel scope) cancels a socket handler and, while the handler is still
    cleaning up its two tasks, cancels it again with its own message. The handler must re-raise that
    cancellation, not an anonymous one the canceller does not recognise (which the TestClient turned into
    a CancelledError at the socket's close, about once in 200 runs)."""
    async def scenario():
        stopping = asyncio.Event()

        async def slow_to_stop():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                stopping.set()
                for _ in range(3):
                    await asyncio.sleep(0)
                raise

        handler = asyncio.ensure_future(_until_either(slow_to_stop(), asyncio.sleep(10)))
        await asyncio.sleep(0)
        handler.cancel("the canceller's scope")
        await stopping.wait()
        handler.cancel("the canceller's scope")              # re-delivered while the handler cleans up
        try:
            await handler
        except asyncio.CancelledError as error:
            return error.args
        return None
    assert asyncio.run(scenario()) == ("the canceller's scope",)
