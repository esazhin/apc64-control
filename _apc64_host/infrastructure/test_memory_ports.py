"""The in-memory ports of the simulated run and the silent consent prompt."""
import asyncio

from _apc64_host.application.ports import ConsentAnswer, SendResult
from _apc64_host.domain.midi import ControlChange, NoteOn
from _apc64_host.infrastructure.memory_ports import MemoryPorts
from _apc64_host.infrastructure.notifier import SilentPrompt


def test_sends_resolve_by_exact_name_or_unique_part_and_are_recorded():
    ports = MemoryPorts(["MPC Live III MIDI 1", "USB MIDI Interface MIDI 1", "Bitwig Studio In"])
    assert ports.send("MPC Live III MIDI 1", NoteOn(10, 36, 127)) is SendResult.SENT
    assert ports.send("bitwig", NoteOn(1, 60, 100)) is SendResult.SENT
    assert ports.send("MIDI 1", NoteOn(1, 60, 100)) is SendResult.MISSING      # ambiguous
    assert ports.send("Nord", NoteOn(1, 60, 100)) is SendResult.MISSING
    assert [name for name, _ in ports.sent] == ["MPC Live III MIDI 1", "Bitwig Studio In"]
    assert [p.name for p in ports.list()] == ["MPC Live III MIDI 1", "USB MIDI Interface MIDI 1", "Bitwig Studio In"]


def test_feedback_reaches_listeners_of_that_port_until_cancelled_and_presence_is_announced():
    ports = MemoryPorts(["MPC Live III MIDI 1"])
    heard, presence = [], []
    listener = ports.listen("MPC", heard.append)
    ports.subscribe_presence(lambda name, present: presence.append((name, present)))
    assert ports.deliver("MPC Live III MIDI 1", ControlChange(1, 20, 0)) == 1
    listener.cancel()
    assert ports.deliver("MPC Live III MIDI 1", ControlChange(1, 20, 0)) == 0
    assert len(heard) == 1
    ports.unplug("MPC Live III MIDI 1")
    assert ports.send("mpc live", NoteOn(1, 1, 1)) is SendResult.MISSING
    ports.plug("MPC Live III MIDI 1")
    assert presence == [("MPC Live III MIDI 1", False), ("MPC Live III MIDI 1", True)]


def test_the_silent_prompt_asks_nothing_visible_and_answers_dismissed_when_withdrawn():
    async def scenario():
        prompt = SilentPrompt()
        task = asyncio.ensure_future(prompt.ask("Take control of APC64?"))
        await asyncio.sleep(0)
        assert not task.done() and prompt.asked == ["Take control of APC64?"]
        prompt.withdraw()
        assert await task is ConsentAnswer.DISMISSED
    asyncio.run(scenario())
