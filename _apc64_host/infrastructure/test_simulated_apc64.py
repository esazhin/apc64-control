import threading

import pytest

from _apc64_host.application.ports import (
    HolderLookup, PortBusy, PortGone, PortNoPermission, UnitConnection, UnitLocator, UnitPort,
)
from _apc64_host.domain.controls import PadPos, Shift, Strip
from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.layout import UnitPortRole
from _apc64_host.domain.leds import LedFrame
from _apc64_host.domain.midi import NoteOn, PolyAftertouch
from _apc64_host.domain.oled import OledText
from _apc64_host.domain.outbound import SysexCommand
from _apc64_host.domain.unit_status import Holder, UnitPresence
from _apc64_host.infrastructure.alsa_rawmidi import InputOnlyPort
from _apc64_host.infrastructure.conftest import capture, wait_for
from _apc64_host.infrastructure.simulated_apc64 import SimulatedApc64
from _apc64_host.protocol import sysex
from _apc64_host.protocol.surface_map import clear_frames

VIEWS = "daw-mode-views-velocity-aftertouch-2026-10-23.log"
SESSION = "daw-mode-session-velocity-2026-10-23.log"
DAW, NOTES, CUSTOM = UnitPortRole.DAW, UnitPortRole.NOTES, UnitPortRole.CUSTOM


def held(unit, *roles):
    """Opens each role at the located address and collects what it receives."""
    presence = unit.find()
    got = {}
    for role in roles or (DAW,):
        connection = unit.open(role, presence.address(role))
        chunks, gone = [], []
        connection.listen(chunks.append, lambda gone=gone: gone.append(True))
        got[role] = (connection, chunks, gone)
    return got


def test_the_simulator_is_a_unit_port_locator_and_holder_lookup():
    unit = SimulatedApc64()
    assert isinstance(unit, UnitPort) and isinstance(unit, UnitLocator)
    assert isinstance(unit.holder_lookup, HolderLookup)
    assert unit.find() == UnitPresence("hw:4,0,0", "hw:4,0,1", "hw:4,0,3")
    assert isinstance(held(unit)[DAW][0], UnitConnection)


def test_it_answers_the_identity_request_with_the_fixture_reply_and_nothing_else():
    # T18: the handshake as the session sends it; only the identity request is answered (fixtures)
    unit = SimulatedApc64()
    daw, chunks, _ = held(unit)[DAW]
    for frame in sysex.handshake_frames():
        daw.write(frame)
    assert chunks == [capture(VIEWS)[0][1]]                      # byte-exact: line 1 of the capture
    identity = sysex.parse_identity(chunks[0])
    assert identity.is_apc64 and identity.firmware_warning is None and identity.serial == "000000000000000"
    daw.write(sysex.daw_on())
    assert unit.daw_mode and len(chunks) == 1
    for frame in sysex.oled_frames(OledText("Jam", "P1 Drums | B1")):
        daw.write(frame)
    assert unit.oled == {0: "Jam", 1: "P1 Drums | B1"}
    for frame in clear_frames():
        daw.write(frame)
    daw.write(sysex.daw_off())
    assert not unit.daw_mode and unit.dark() and len(chunks) == 1
    assert unit.commands[:3] == [SysexCommand.DRUM_FLAG, SysexCommand.PAD_MODE, SysexCommand.IDENTITY_REQUEST]
    assert unit.commands[-1] is SysexCommand.DAW_MODE and unit.hazards == []


def test_presses_strips_encoder_and_view_reports_go_out_exactly_as_captured():
    unit = SimulatedApc64()
    daw, chunks, _ = held(unit)[DAW]
    unit.press(PadPos(1, 1))
    unit.release(PadPos(1, 1))
    assert chunks == [line for port, line in capture(SESSION)[1:3]]          # '96 00 7F', '86 00 00'
    del chunks[:]
    unit.press(Shift())
    unit.move(Strip(3), 8192)
    unit.turn(-2)
    unit.view(UnitView.SESSION)
    assert chunks == [b"\x90\x78\x7f", b"\xe2\x00\x40", b"\xb0\x5a\x7e", bytes.fromhex("F0 47 00 53 19 00 01 00 F7")]


def test_notes_and_custom_streams_and_a_whole_capture_replay_in_order():
    unit = SimulatedApc64()
    got = held(unit, DAW, NOTES, CUSTOM)
    unit.play(NOTES, NoteOn(1, 0x35, 0x38))
    unit.play(NOTES, PolyAftertouch(1, 0x35, 0x0A))
    assert got[NOTES][1] == [b"\x90\x35\x38", b"\xa0\x35\x0a"]
    for role in got:
        del got[role][1][:]
    count = unit.replay(VIEWS)
    expected = {role: [data for port, data in capture(VIEWS)[1:] if port == name]
                for role, name in ((DAW, "DAW"), (NOTES, "Notes"), (CUSTOM, "Custom"))}
    assert {role: got[role][1] for role in got} == expected
    assert count == sum(len(v) for v in expected.values())


def test_bytes_sent_before_anyone_listens_wait_for_the_listener():
    unit = SimulatedApc64()
    daw = unit.open(DAW, "hw:4,0,0")
    daw.write(sysex.IDENTITY_REQUEST)
    chunks = []
    daw.listen(chunks.append, lambda: None)
    assert chunks == [capture(VIEWS)[0][1]]


def test_busy_with_a_named_holder_and_the_holder_freeing_it():
    # T18 fault: busy (A3/A13 as seen through the ports)
    unit = SimulatedApc64()
    changes = []
    unit.holder_lookup.subscribe(lambda role, holder: changes.append((role, holder)))
    unit.hold(DAW, "Bitwig Studio")
    with pytest.raises(PortBusy) as busy:
        unit.open(DAW, "hw:4,0,0")
    assert busy.value.holder == Holder("Bitwig Studio") and unit.holder_lookup.holder_of(DAW) == Holder("Bitwig Studio")
    unit.free(DAW)
    assert changes == [(DAW, Holder("Bitwig Studio")), (DAW, None)]
    unit.open(DAW, "hw:4,0,0").close()
    unit.hold(NOTES, None)                       # held by something unnamed: Busy without a name
    with pytest.raises(PortBusy) as busy:
        unit.open(NOTES, "hw:4,0,1")
    assert busy.value.holder is None
    unit.open(DAW, "hw:4,0,0")                   # only Notes is busy (A15)


def test_no_permission_and_a_second_open_while_held():
    unit = SimulatedApc64()
    unit.no_permission = True
    with pytest.raises(PortNoPermission):
        unit.open(DAW, "hw:4,0,0")
    unit.no_permission = False
    first = unit.open(DAW, "hw:4,0,0")
    with pytest.raises(PortBusy):
        unit.open(DAW, "hw:4,0,0")
    first.close()
    first.close()
    unit.open(DAW, "hw:4,0,0")


def test_unplug_ends_every_connection_once_and_replug_lands_on_another_card_out_of_daw_mode():
    # T18 fault: unplug (A27), d9
    unit = SimulatedApc64()
    presence = []
    unit.subscribe(presence.append)
    got = held(unit, DAW, NOTES)
    got[DAW][0].write(sysex.daw_on())
    unit.unplug()
    unit.unplug()
    assert [g[2] for g in got.values()] == [[True], [True]]
    assert presence == [None, None] and unit.find() is None and not unit.daw_mode
    with pytest.raises(PortGone):
        got[DAW][0].write(sysex.daw_off())
    with pytest.raises(PortGone):
        unit.open(DAW, "hw:4,0,0")
    unit.press(PadPos(1, 1))                                   # nothing reaches a gone connection
    assert got[DAW][1] == []
    unit.plug(card=5)
    assert presence[-1] == UnitPresence("hw:5,0,0", "hw:5,0,1", "hw:5,0,3")
    with pytest.raises(PortGone):
        unit.open(DAW, "hw:4,0,0")                             # the old address is stale
    unit.open(DAW, "hw:5,0,0")


def test_silent_units_other_products_and_firmware():
    unit = SimulatedApc64(silent=True)
    daw, chunks, _ = held(unit)[DAW]
    daw.write(sysex.IDENTITY_REQUEST)
    assert chunks == []
    for product, firmware, check in ((0x51, (1, 2, 1, 6), lambda i: not i.is_apc64),
                                     (0x53, (1, 2, 2, 0), lambda i: i.firmware_warning == "untested firmware 1.2.2.0")):
        unit = SimulatedApc64(product=product, firmware=firmware)
        daw, chunks, _ = held(unit)[DAW]
        daw.write(sysex.IDENTITY_REQUEST)
        assert check(sysex.parse_identity(chunks[0]))


def test_nothing_is_written_to_notes_or_custom_and_hazards_are_listed():
    unit = SimulatedApc64()
    got = held(unit, DAW, NOTES, CUSTOM)
    for role in (NOTES, CUSTOM):
        with pytest.raises(InputOnlyPort):
            got[role][0].write(b"\x90\x24\x7f")
    project_write = sysex.akai_frame(sysex.PROJECT_WRITE, b"\x00")
    got[DAW][0].write(project_write)       # only the outbound gate could stop this; the fake just records it
    assert unit.hazards == [project_write]


def test_led_frames_are_tracked_so_a_redraw_and_a_clear_can_be_checked():
    unit = SimulatedApc64()
    daw = held(unit)[DAW][0]
    from _apc64_host.protocol.surface_map import encode_frame
    for frame in encode_frame(LedFrame.blank()):
        daw.write(frame)
    assert unit.dark()
    daw.write(b"\x96\x00\x05")
    assert not unit.dark() and unit.leds[(0x90, 0)] == 5


def test_threaded_delivery_keeps_each_connections_order():
    # a5 support: chunks from two emitting threads reach each role's listener in order on its own thread
    unit = SimulatedApc64(threaded=True)
    got = held(unit, DAW, NOTES)
    threads_seen = set()
    original = got[NOTES][0]._on_bytes
    got[NOTES][0]._on_bytes = lambda chunk: (threads_seen.add(threading.current_thread().name), original(chunk))
    daw_bytes = [bytes([0xE0, n & 0x7F, n >> 7 & 0x7F]) for n in range(1000)]
    notes_bytes = [bytes([0xA0, 0x35, n & 0x7F]) for n in range(1000)]
    emitters = [threading.Thread(target=lambda: [unit.emit(DAW, b) for b in daw_bytes]),
                threading.Thread(target=lambda: [unit.emit(NOTES, b) for b in notes_bytes])]
    for emitter in emitters:
        emitter.start()
    for emitter in emitters:
        emitter.join()
    assert wait_for(lambda: len(got[DAW][1]) == 1000 and len(got[NOTES][1]) == 1000)
    assert got[DAW][1] == daw_bytes and got[NOTES][1] == notes_bytes
    assert threads_seen == {"apc64-sim-notes"}
    unit.unplug()
    assert wait_for(lambda: got[DAW][2] == [True] and got[NOTES][2] == [True])
    for connection, _, _ in got.values():
        connection.close()


def test_a_strip_colour_without_a_bar_mode_is_dark():
    """Releasing a lit strip sends mode CC 0 (bar off) and leaves the colour CC as it was; the unit shows nothing
    then, so dark() must not count that colour."""
    from _apc64_host.domain.layout import UnitPortRole as Role
    sim = SimulatedApc64()
    connection = sim.open(Role.DAW, sim.address(Role.DAW))
    connection.write(bytes([0xB0, 0x70, 3]))      # strip 1 colour white
    connection.write(bytes([0xB0, 0x68, 1]))      # strip 1 bar on
    assert not sim.dark()
    connection.write(bytes([0xB0, 0x68, 0]))      # strip 1 bar off
    assert sim.dark()
