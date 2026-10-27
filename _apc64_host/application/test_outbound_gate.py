import threading

import pytest

from _apc64_host.application.conftest import RecordingConnection
from _apc64_host.application.modules import collect
from _apc64_host.application.outbound_gate import GateResult, OutboundGate
from _apc64_host.application.ports import PortGone
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.leds import LedState
from _apc64_host.domain.oled import OledText
from _apc64_host.domain.outbound import CONTRACT1_POLICY, DeviceLogOutcome, SysexCommand
from _apc64_host.domain.palette import parse_colour
from _apc64_host.infrastructure.simulated_apc64 import SimulatedApc64
from _apc64_host.protocol import sysex
from _apc64_host.protocol.surface_map import encode_led

LED = encode_led(PadPos(1, 1), LedState(parse_colour("red")))
OLED_ROW0, OLED_ROW1 = sysex.oled_frames(OledText("Jam", ""))
PROJECT_WRITE = sysex.akai_frame(sysex.PROJECT_WRITE, bytes([0, 0, 1, 2, 3]))   # slot 0
GLOBAL_WRITE = sysex.akai_frame(sysex.GLOBAL_WRITE, bytes([0, 1]))
PROJECT_READ = sysex.akai_frame(sysex.PROJECT_READ, bytes([0]))
GLOBAL_READ = sysex.akai_frame(sysex.GLOBAL_READ, bytes([0]))


def gate(**kw):
    return OutboundGate(CONTRACT1_POLICY, wall=lambda: 1.5, **kw)


def test_frames_are_written_in_order_and_a_project_write_is_refused_and_logged():   # A31 (gate side)
    g, connection = gate(), RecordingConnection()
    g.attach(connection)
    results = g.send([LED, OLED_ROW0, PROJECT_WRITE])
    assert results == [GateResult.SENT, GateResult.SENT, GateResult.REFUSED]
    assert connection.written == [LED, OLED_ROW0]
    log = g.device_log()
    assert [e.outcome for e in log] == [DeviceLogOutcome.SENT, DeviceLogOutcome.SENT, DeviceLogOutcome.REFUSED]
    assert log[-1].hazard and log[-1].command is SysexCommand.PROJECT_WRITE
    assert log[-1].refusal_text() == "refused: project write (0x14)"
    assert log[0].at == 1.5


@pytest.mark.parametrize("frame", [GLOBAL_WRITE, PROJECT_READ, GLOBAL_READ, LED + LED, b"\xf0\x00\x01\xf7"])
def test_reads_writes_and_anything_not_one_known_message_never_reach_the_unit(frame):
    g, connection = gate(), RecordingConnection()
    g.attach(connection)
    assert g.send([frame]) == [GateResult.REFUSED]
    assert connection.written == [] and g.device_log()[-1].hazard


def test_detached_frames_are_dropped_silently_but_hazards_are_still_refused_and_logged():
    g, connection = gate(), RecordingConnection()
    g.attach(connection)
    g.detach()
    assert g.send([LED, OLED_ROW1]) == [GateResult.DROPPED, GateResult.DROPPED]
    assert g.send([PROJECT_WRITE]) == [GateResult.REFUSED]
    assert connection.written == []
    assert [e.outcome for e in g.device_log()] == [DeviceLogOutcome.REFUSED]   # drops are not logged
    assert not g.attached


def test_a_failing_write_propagates_port_gone_and_detaches():   # s37.c3, s54.c2
    g, connection = gate(), RecordingConnection(fail_after=1)
    g.attach(connection)
    with pytest.raises(PortGone):
        g.send([LED, OLED_ROW0, OLED_ROW1])
    assert connection.written == [LED]
    assert not g.attached and g.send([OLED_ROW1]) == [GateResult.DROPPED]


def test_writes_from_several_threads_never_interleave_inside_a_frame():   # a18: one write path
    g, connection = gate(), RecordingConnection()
    g.attach(connection)
    batches = [[LED] * 50, [OLED_ROW0, OLED_ROW1] * 25]
    threads = [threading.Thread(target=g.send, args=(b,)) for b in batches for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(connection.written) == 400
    assert all(sysex.command_of(f) is not SysexCommand.UNKNOWN_SYSEX for f in connection.written)


def test_the_device_log_is_a_bounded_ring_in_send_order():
    g = gate(log_size=3)
    g.attach(RecordingConnection())
    g.send([LED, OLED_ROW0, OLED_ROW1, PROJECT_WRITE])
    assert [e.frame for e in g.device_log()] == [OLED_ROW0, OLED_ROW1, PROJECT_WRITE]


def test_a_module_policy_addition_widens_the_gate_without_core_edits():   # s77 / OCP
    class Lab:
        name = "lab"

        def outbound_additions(self):
            return frozenset({SysexCommand.PROJECT_READ})

        def router(self):
            return None

        def panel(self):
            return None

    g = OutboundGate(collect([Lab()]).policy(CONTRACT1_POLICY))
    g.attach(RecordingConnection())
    assert g.send([PROJECT_READ, PROJECT_WRITE]) == [GateResult.SENT, GateResult.REFUSED]


def test_a_full_session_through_the_gate_holds_only_identity_handshake_leds_and_oled():   # A32
    sim = SimulatedApc64()
    g = gate()
    g.attach(sim.open("daw", sim.address("daw")))
    g.send(list(sysex.handshake_frames()) + [sysex.daw_on(), LED, OLED_ROW0, OLED_ROW1, PROJECT_WRITE,
                                              GLOBAL_WRITE, sysex.daw_off()])
    assert sim.hazards == []
    allowed = {SysexCommand.IDENTITY_REQUEST, SysexCommand.DRUM_FLAG, SysexCommand.PAD_MODE,
               SysexCommand.DAW_MODE, SysexCommand.CHANNEL_MESSAGE, SysexCommand.OLED_TEXT}
    assert set(sim.commands) <= allowed and not sim.daw_mode
    assert [e.refusal_text() for e in g.device_log() if e.hazard] == [
        "refused: project write (0x14)", "refused: global-settings write (0x18)"]
