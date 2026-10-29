import errno
import gc
import queue
import threading

import pytest
from alsa_midi import (
    SYSTEM_ANNOUNCE, Address, ALSAError, ClientInfo, MidiBytesEvent, PortCaps, PortExitEvent, PortInfo as SeqPortInfo,
    PortStartEvent, PortSubscribedEvent, PortType, PortUnsubscribedEvent, SubscriptionQuery,
)

from _apc64_host.application.ports import (
    FeedbackInputs, HolderLookup, PortCatalog, PortDirection, PortInfo, SendResult, TargetPorts,
)
from _apc64_host.domain.layout import UnitPortRole
from _apc64_host.domain.midi import ControlChange, NoteOff, NoteOn
from _apc64_host.domain.unit_status import Holder
from _apc64_host.infrastructure.alsa_seq import AlsaSequencer
from _apc64_host.infrastructure.conftest import wait_for

READ = PortCaps.READ | PortCaps.SUBS_READ
WRITE = PortCaps.WRITE | PortCaps.SUBS_WRITE
HW = PortType.MIDI_GENERIC | PortType.HARDWARE | PortType.PORT
APP = PortType.MIDI_GENERIC | PortType.APPLICATION
MPC = "MPC Live III MIDI 1"
OWN = 130


class FakeSequencer:
    """An alsa-midi SequencerClient double: clients, ports, subscriptions, an event queue and the calls made."""

    def __init__(self):
        self.client_id = OWN
        self.clients = {0: "System", 14: "Midi Through", OWN: "apc64-host"}
        self.ports = {}                   # Address -> SeqPortInfo
        self.subscriptions = set()        # (sender Address, dest Address)
        self.calls = []
        self.events = queue.Queue()
        self.output_error = None
        self._next_port = 0
        self.closed = False

    # --- the world --------------------------------------------------------------------------------------
    def add_port(self, client_id, client_name, port_id, name, caps, type=HW):
        self.clients[client_id] = client_name
        self.ports[Address(client_id, port_id)] = SeqPortInfo(client_id=client_id, port_id=port_id, name=name,
                                                              capability=caps, type=type)
        return Address(client_id, port_id)

    def remove_port(self, address):
        del self.ports[address]
        self.subscriptions = {s for s in self.subscriptions if address not in s}

    def push(self, event):
        self.events.put(event)

    # --- SequencerClient --------------------------------------------------------------------------------
    def create_port(self, name, caps, type):
        port_id = self._next_port
        self._next_port += 1
        self.calls.append(("create_port", name, caps, type))
        self.add_port(OWN, "apc64-host", port_id, name, caps, type)
        return type_port(self, OWN, port_id)

    def list_ports(self, **options):
        self.calls.append(("list_ports", tuple(sorted(options))))
        result = []
        for address, info in sorted(self.ports.items()):
            if address.client_id == 0 and not options.get("include_system", False):
                continue
            listed = SeqPortInfo(client_id=info.client_id, port_id=info.port_id, name=info.name,
                                 capability=info.capability, type=info.type)
            listed.client_name = self.clients[address.client_id]
            result.append(listed)
        return result

    def subscribe_port(self, sender, dest, **kwargs):
        self.calls.append(("subscribe", Address(sender), Address(dest)))
        self.subscriptions.add((Address(sender), Address(dest)))

    def unsubscribe_port(self, sender, dest):
        self.calls.append(("unsubscribe", Address(sender), Address(dest)))
        if (Address(sender), Address(dest)) not in self.subscriptions:
            raise ALSAError("no such subscription", -errno.ENOENT)
        self.subscriptions.discard((Address(sender), Address(dest)))

    def list_port_subscribers(self, port, type=None):
        port = Address(port)
        found = [s for s in sorted(self.subscriptions) if port in s]
        return [SubscriptionQuery(root=port, addr=(dest if sender == port else sender)) for sender, dest in found]

    def get_client_info(self, client_id=None):
        return ClientInfo(client_id=client_id, name=self.clients[client_id])

    def event_output(self, event, queue=None, port=None, dest=None):
        self.calls.append(("output", bytes(event.midi_bytes), Address(dest), getattr(port, "port_id", port)))
        if self.output_error is not None:
            raise self.output_error
        info = self.ports.get(Address(dest))
        sender = Address(OWN, getattr(port, "port_id", port))
        if info is not None and info.type & PortType.HARDWARE and (sender, Address(dest)) not in self.subscriptions:
            raise ALSAError("No such device", -errno.ENODEV)   # a kernel port is open only while connected
        return len(event.midi_bytes)

    def drain_output(self):
        self.calls.append(("drain",))
        return 0

    def drop_output(self):
        self.calls.append(("drop_output",))

    def event_input(self, prefer_bytes=False, timeout=None):
        try:
            return self.events.get(timeout=timeout or 0.001)
        except queue.Empty:
            return None

    def close(self):
        self.closed = True


class type_port:
    """Like alsa-midi's Port: dropping the object deletes the port and its subscriptions."""

    def __init__(self, seq, client_id, port_id):
        self.seq, self.client_id, self.port_id = seq, client_id, port_id

    def __del__(self):
        address = Address(self.client_id, self.port_id)
        if address in self.seq.ports:
            self.seq.remove_port(address)


def world():
    """MPC (both ways), Bitwig's virtual input, the USB interface, the APC64 client (4 ports) held by Chrome."""
    seq = FakeSequencer()
    mpc = seq.add_port(24, "MPC Live III", 0, MPC, READ | WRITE)
    bitwig = seq.add_port(129, "Bitwig Studio", 0, "Bitwig Studio In", WRITE, APP)
    interface = seq.add_port(20, "USB MIDI Interface", 0, "USB MIDI Interface MIDI 1", READ | WRITE)
    apc = {role: seq.add_port(32, "APC64", n, f"APC64 {word}", READ | WRITE)
           for n, (role, word) in enumerate([("daw", "DAW"), ("notes", "Notes"), ("midi", "MIDI"),
                                              ("custom", "Custom")])}
    chrome = seq.add_port(128, "Chrome", 0, "Chrome Web MIDI", READ | WRITE, APP)
    seq.subscriptions.add((apc["daw"], chrome))      # Chrome reads the DAW port (Web MIDI input)
    return seq, {"mpc": mpc, "bitwig": bitwig, "interface": interface, "apc": apc, "chrome": chrome}


def adapter(seq, **kwargs):
    sequencer = AlsaSequencer(client_factory=lambda: seq, **kwargs)
    sequencer.open()
    return sequencer


def touches_apc64(seq, addresses):
    apc = set(addresses["apc"].values())
    return [s for s in seq.subscriptions if (s[0] in apc or s[1] in apc) and OWN in (s[0].client_id, s[1].client_id)]


def test_open_creates_one_client_with_an_out_and_an_in_port_listening_to_system_announce():
    seq, _ = world()
    sequencer = adapter(seq)
    assert [c[1] for c in seq.calls if c[0] == "create_port"] == ["apc64-host out", "apc64-host in"]
    assert ("subscribe", SYSTEM_ANNOUNCE, Address(OWN, 1)) in seq.calls
    gc.collect()   # both ports outlive open(): the announce connection stays (a port appearing is noticed)
    assert {Address(OWN, 0), Address(OWN, 1)} <= set(seq.ports)
    assert (SYSTEM_ANNOUNCE, Address(OWN, 1)) in seq.subscriptions
    for protocol in (TargetPorts, FeedbackInputs, PortCatalog, HolderLookup):
        assert isinstance(sequencer, protocol)
    sequencer.close()
    assert seq.closed


def test_the_catalog_lists_ports_by_name_and_direction_never_the_apc64_or_our_own():
    # T14, s25.c2, s89.c2, a14
    seq, _ = world()
    listed = adapter(seq).list()
    assert listed == [PortInfo("USB MIDI Interface MIDI 1", PortDirection.BOTH),
                      PortInfo(MPC, PortDirection.BOTH),
                      PortInfo("Chrome Web MIDI", PortDirection.BOTH),
                      PortInfo("Bitwig Studio In", PortDirection.OUTPUT)]
    assert not any("APC64" in p.name or "apc64-host" in p.name for p in listed)


def test_send_resolves_the_pattern_by_exact_name_or_unique_part_and_maps_missing_and_failed():
    # T14, s45.c2, s82.c2
    seq, at = world()
    sequencer = adapter(seq)
    assert sequencer.send(MPC, NoteOn(10, 36, 127)) is SendResult.SENT
    assert sequencer.send("bitwig studio", ControlChange(1, 20, 64)) is SendResult.SENT   # unique part, any case
    outputs = [c for c in seq.calls if c[0] in ("output", "drain")]
    assert outputs == [("output", b"\x99\x24\x7f", at["mpc"], 0), ("drain",),
                       ("output", b"\xb0\x14\x40", at["bitwig"], 0), ("drain",)]
    assert sequencer.send(MPC, NoteOff(10, 36, 0)) is SendResult.SENT
    assert [c for c in seq.calls if c[0] == "subscribe" and c[1] == Address(OWN, 0)] == [   # connected once each
        ("subscribe", Address(OWN, 0), at["mpc"]), ("subscribe", Address(OWN, 0), at["bitwig"])]
    del seq.calls[:]
    assert sequencer.send("Nord Stage", NoteOn(1, 60, 100)) is SendResult.MISSING      # no such port
    assert sequencer.send("MIDI 1", NoteOn(1, 60, 100)) is SendResult.MISSING          # two ports match
    assert sequencer.send("APC64 DAW", NoteOn(1, 60, 100)) is SendResult.MISSING       # never the APC64
    assert sequencer.send("APC64", NoteOn(1, 60, 100)) is SendResult.MISSING
    assert not [c for c in seq.calls if c[0] == "output"]
    seq.output_error = ALSAError("no such port", -errno.ENOENT)                         # vanished in between
    assert sequencer.send(MPC, NoteOn(10, 36, 127)) is SendResult.MISSING
    seq.output_error = ALSAError("broken", -errno.EPIPE)
    assert sequencer.send(MPC, NoteOn(10, 36, 127)) is SendResult.FAILED
    assert seq.calls.count(("drop_output",)) == 2


def test_a_send_to_a_vanished_port_is_missing_and_it_reconnects_by_name_when_it_appears():
    # T14, A86, d61, s4.c3, s45.c3
    seq, at = world()
    sequencer = adapter(seq)
    presence = []
    sequencer.subscribe_presence(lambda name, present: presence.append((name, present)))
    seq.remove_port(at["mpc"])
    seq.push(PortExitEvent(at["mpc"]))
    sequencer.process_pending()
    assert presence == [(MPC, False)]
    assert sequencer.send(MPC, NoteOn(10, 36, 127)) is SendResult.MISSING
    back = seq.add_port(36, "MPC Live III", 0, MPC, READ | WRITE)                   # replugged, new client id
    seq.push(PortStartEvent(back))
    sequencer.process_pending()
    assert presence == [(MPC, False), (MPC, True)]
    assert sequencer.send(MPC, NoteOn(10, 36, 127)) is SendResult.SENT
    assert [c for c in seq.calls if c[0] == "output"][-1][2] == back


def test_a_port_listed_before_its_announce_is_handled_is_still_reported_present():
    seq, _ = world()
    sequencer = adapter(seq)
    presence = []
    sequencer.subscribe_presence(lambda name, present: presence.append((name, present)))
    port = seq.add_port(40, "Launch Control XL", 0, "Launch Control XL MIDI 1", READ | WRITE)
    assert "Launch Control XL MIDI 1" in [p.name for p in sequencer.list()]   # a page or CLI listing comes first
    seq.push(PortStartEvent(port))
    sequencer.process_pending()
    assert presence == [("Launch Control XL MIDI 1", True)]


def test_feedback_listeners_get_midi_messages_in_order_and_follow_their_port_by_name():
    # T14, s4.c2, s45.c3, s65.c1–c2
    seq, at = world()
    sequencer = adapter(seq)
    got, other = [], []
    subscription = sequencer.listen(MPC, got.append)
    sequencer.listen("USB MIDI Interface", other.append)
    assert ("subscribe", at["mpc"], Address(OWN, 1)) in seq.calls
    for data in (b"\x90\x24\x64", b"\xb0\x4a\x0a", b"\x80\x24\x00", b"\xf0\x7e\x7f\x06\x01\xf7"):
        seq.push(MidiBytesEvent(data, source=at["mpc"]))
    seq.push(MidiBytesEvent(b"\x91\x30\x40", source=at["interface"]))
    sequencer.process_pending()
    assert got == [NoteOn(1, 36, 100), ControlChange(1, 74, 10), NoteOff(1, 36, 0)]
    assert other == [NoteOn(2, 48, 64)]

    # the port vanishes and comes back elsewhere: the listener follows it by name
    seq.remove_port(at["mpc"])
    seq.push(PortExitEvent(at["mpc"]))
    back = seq.add_port(36, "MPC Live III", 0, MPC, READ | WRITE)
    seq.push(PortStartEvent(back))
    seq.push(MidiBytesEvent(b"\x90\x25\x50", source=back))
    sequencer.process_pending()
    assert ("subscribe", back, Address(OWN, 1)) in seq.calls
    assert got[-1] == NoteOn(1, 37, 80)

    subscription.cancel()
    subscription.cancel()
    assert ("unsubscribe", back, Address(OWN, 1)) in seq.calls
    seq.push(MidiBytesEvent(b"\x90\x26\x50", source=back))
    sequencer.process_pending()
    assert got[-1] == NoteOn(1, 37, 80)


def test_realtime_listeners_hear_the_clock_with_its_arrival_time_and_note_listeners_do_not():   # §2.10
    seq, at = world()
    sequencer = adapter(seq)
    clock, notes = [], []
    sequencer.listen_realtime(MPC, lambda status, t: clock.append((status, t)))
    sequencer.listen(MPC, notes.append)
    for data in (b"\xfa", b"\xf8", b"\x90\x24\x64", b"\xf8", b"\xfc"):
        seq.push(MidiBytesEvent(data, source=at["mpc"]))
    sequencer.process_pending()
    assert [status for status, _ in clock] == [0xFA, 0xF8, 0xF8, 0xFC]
    assert all(isinstance(t, float) for _, t in clock) and clock == sorted(clock, key=lambda c: c[1])
    assert notes == [NoteOn(1, 36, 100)]


def test_a_listener_on_a_missing_port_connects_when_the_port_appears():
    seq, _ = world()
    sequencer = adapter(seq)
    got = []
    sequencer.listen("Launch Control", got.append)
    assert not [c for c in seq.calls if c[0] == "subscribe" and c[1].client_id == 40]
    port = seq.add_port(40, "Launch Control XL", 0, "Launch Control XL MIDI 1", READ)
    seq.push(PortStartEvent(port))
    seq.push(MidiBytesEvent(b"\xb8\x0d\x7f", source=port))
    sequencer.process_pending()
    assert got == [ControlChange(9, 13, 127)]


def test_holder_of_names_the_subscribed_client_and_changes_are_announced():
    # T14, s33.c2, s4.c4, s82.c3
    seq, at = world()
    sequencer = adapter(seq)
    changes = []
    sequencer.subscribe(lambda role, holder: changes.append((role, holder)))
    assert sequencer.holder_of(UnitPortRole.DAW) == Holder("Chrome")
    assert sequencer.holder_of(UnitPortRole.NOTES) is None
    seq.subscriptions.discard((at["apc"]["daw"], at["chrome"]))
    seq.push(PortUnsubscribedEvent(at["apc"]["daw"], at["chrome"]))
    sequencer.process_pending()
    assert changes == [(UnitPortRole.DAW, None)]
    assert sequencer.holder_of(UnitPortRole.DAW) is None
    # Bitwig subscribes to the Notes port: a holder change for that role only
    seq.subscriptions.add((at["bitwig"], at["apc"]["notes"]))
    seq.push(PortSubscribedEvent(at["bitwig"], at["apc"]["notes"]))
    sequencer.process_pending()
    assert changes == [(UnitPortRole.DAW, None), (UnitPortRole.NOTES, Holder("Bitwig Studio"))]
    # unrelated subscriptions change nothing
    seq.push(PortSubscribedEvent(at["interface"], at["mpc"]))
    sequencer.process_pending()
    assert len(changes) == 2


def test_holder_of_without_an_apc64_is_none():
    seq = FakeSequencer()
    assert adapter(seq).holder_of(UnitPortRole.DAW) is None


def test_our_client_never_subscribes_to_any_apc64_port():
    # T14, a14, s82.c4: listening or sending by an APC64 name does nothing
    seq, at = world()
    sequencer = adapter(seq)
    sequencer.listen("APC64 DAW", lambda m: None)
    sequencer.listen("APC64 Notes", lambda m: None)
    sequencer.send("APC64 Custom", NoteOn(1, 1, 1))
    seq.push(PortStartEvent(at["apc"]["daw"]))
    sequencer.process_pending()
    assert touches_apc64(seq, at) == []
    assert not [c for c in seq.calls if c[0] == "subscribe" and c[1] in at["apc"].values()]


def test_the_reader_thread_delivers_through_dispatch_and_stops():
    seq, at = world()
    threads = []

    def dispatch(fn, *args):
        threads.append(threading.current_thread().name)
        fn(*args)

    sequencer = AlsaSequencer(client_factory=lambda: seq, dispatch=dispatch, poll_timeout=0.01)
    got = []
    sequencer.start()
    try:
        sequencer.listen(MPC, got.append)
        seq.push(MidiBytesEvent(b"\x90\x24\x64", source=at["mpc"]))
        assert wait_for(lambda: got == [NoteOn(1, 36, 100)])
        assert threads == ["apc64-sequencer"]
    finally:
        sequencer.stop()
    assert seq.closed


def test_a_failing_callback_does_not_stop_event_handling():
    seq, at = world()
    sequencer = adapter(seq)
    got = []

    def flaky(message):
        got.append(message)
        if len(got) == 1:
            raise RuntimeError("listener bug")

    sequencer.listen(MPC, flaky)
    seq.push(MidiBytesEvent(b"\x90\x24\x64", source=at["mpc"]))
    seq.push(MidiBytesEvent(b"\x90\x25\x64", source=at["mpc"]))
    sequencer.process_pending()
    assert len(got) == 2


def test_an_unavailable_sequencer_reads_as_no_ports():
    def broken():
        raise ALSAError("no sequencer", -errno.ENOENT)

    sequencer = AlsaSequencer(client_factory=broken)
    assert sequencer.list() == []
    assert sequencer.send(MPC, NoteOn(1, 1, 1)) is SendResult.FAILED
    assert sequencer.holder_of(UnitPortRole.DAW) is None
