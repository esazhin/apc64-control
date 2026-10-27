import asyncio

from _apc64_host.application.ports import (
    Clock, ConsentAnswer, ConsentPrompt, FeedbackInputs, HolderLookup, LayoutSource, PortBusy, PortCatalog,
    PortDirection, PortInfo, PortNoPermission, SendResult, StateStore, TargetPorts, UnitConnection, UnitLocator,
    UnitPort, VersionStore,
)
from _apc64_host.domain.unit_status import Holder, UnitPresence


class Connection:
    def listen(self, on_bytes, on_gone): ...
    def write(self, data): ...
    def close(self): ...


class Port:
    def open(self, role, address):
        raise PortBusy(Holder("Bitwig Studio"))


class Prompt:
    async def ask(self, text):
        return ConsentAnswer.TAKE

    def withdraw(self): ...


def test_doubles_satisfy_the_protocols_structurally():
    assert isinstance(Connection(), UnitConnection) and isinstance(Port(), UnitPort)
    assert isinstance(Prompt(), ConsentPrompt)
    assert not isinstance(object(), Clock)
    for protocol in (UnitLocator, HolderLookup, TargetPorts, FeedbackInputs, PortCatalog, LayoutSource, VersionStore,
                     StateStore):
        assert not isinstance(object(), protocol)


def test_port_errors_carry_the_holder_and_answers_are_named():
    try:
        Port().open("daw", "hw:4,0,0")
    except PortBusy as busy:
        assert busy.holder == Holder("Bitwig Studio") and str(busy) == "busy: held by Bitwig Studio"
    assert str(PortBusy()) == "busy" and issubclass(PortNoPermission, Exception)
    assert asyncio.run(Prompt().ask("Take control of APC64?")) is ConsentAnswer.TAKE
    assert [r.value for r in SendResult] == ["sent", "missing", "failed"]
    assert PortInfo("MPC Live III MIDI 1", PortDirection.BOTH).present


def test_unit_presence_names_each_role_by_address():
    presence = UnitPresence("hw:4,0,0", "hw:4,0,1", "hw:4,0,3")
    assert presence.address("daw") == "hw:4,0,0" and presence.address("custom") == "hw:4,0,3"
    assert UnitPresence("hw:5,0,0").address("notes") is None
