"""Contract 2 T10: the issuer-scoped outbound gate (inv2, a10, a29; s8 s11 s12 s44 suppliers; A3).

Contract 1's assertions ('no 0x13–0x18 ever') stay in test_outbound_gate.py and test___main__.py for the
lab-less composition. Their twin here registers a lab-shaped module: only token-carrying 0x14/0x18 pass."""
import logging

import pytest

from _apc64_host import __main__ as root
from _apc64_host.application.conftest import RecordingConnection
from _apc64_host.application.modules import collect
from _apc64_host.application.outbound_gate import GateResult, OutboundGate
from _apc64_host.application.ports import HostModuleBase
from _apc64_host.domain.oled import OledText
from _apc64_host.domain.outbound import CONTRACT1_POLICY, DeviceLogOutcome, SysexCommand, WriteCapability
from _apc64_host.infrastructure.simulated_apc64 import SimulatedApc64
from _apc64_host.protocol import sysex
from _apc64_host.test___main__ import config_for

TOKEN = WriteCapability("lab guarded writer")
PROJECT_WRITE_3 = sysex.akai_frame(sysex.PROJECT_WRITE, bytes([3]) + bytes(1006))      # slot 3
PROJECT_READ_3 = sysex.akai_frame(sysex.PROJECT_READ, bytes([3]))
GLOBAL_WRITE = sysex.akai_frame(sysex.GLOBAL_WRITE, bytes(64))
GLOBAL_READ = sysex.akai_frame(sysex.GLOBAL_READ, b"")
OLED = sysex.oled_frames(OledText("Tonnetz C", "Oct +0"))[0]
UNKNOWN_15 = sysex.akai_frame(0x15, bytes([0]))
UNKNOWN_16 = sysex.akai_frame(0x16, bytes([0]))
EVERY_MEMORY_FRAME = [PROJECT_READ_3, PROJECT_WRITE_3, UNKNOWN_15, UNKNOWN_16, GLOBAL_READ, GLOBAL_WRITE]


class LabShaped(HostModuleBase):
    """What the lab registers: plain reads, and writes scoped to its one capability."""
    name = "lab"

    def outbound_additions(self):
        return frozenset({SysexCommand.PROJECT_READ, SysexCommand.GLOBAL_READ})

    def outbound_scoped(self):
        return {SysexCommand.PROJECT_WRITE: TOKEN, SysexCommand.GLOBAL_WRITE: TOKEN}


def lab_gate():
    g = OutboundGate(collect([LabShaped()]).policy(CONTRACT1_POLICY), wall=lambda: 2.0)
    connection = RecordingConnection()
    g.attach(connection)
    return g, connection


def test_the_token_frame_passes_a_token_less_one_is_refused_and_logged_and_oled_passes(caplog):
    # T10, A3 (gate side), s44.c1, s11.c2, s8.c2
    g, connection = lab_gate()
    with caplog.at_level(logging.WARNING):
        assert g.send([PROJECT_WRITE_3], issuer=TOKEN) == [GateResult.SENT]
        assert g.send([PROJECT_WRITE_3]) == [GateResult.REFUSED]
        assert g.send([OLED]) == [GateResult.SENT]
    assert connection.written == [PROJECT_WRITE_3, OLED]
    refused = [e for e in g.device_log() if e.hazard]
    assert len(refused) == 1 and refused[0].frame == PROJECT_WRITE_3
    assert refused[0].hazard_line() == "HAZARD refused: project write slot 3"
    assert "HAZARD refused: project write slot 3" in caplog.text
    assert refused[0].refusal_text() == "refused: project write (0x14)"      # contract 1's text, unchanged


@pytest.mark.parametrize("issuer", [None, WriteCapability("look-alike"), "guarded writer", object()])
def test_any_other_issuer_is_no_token(issuer):
    # s44.c1: no issuer, a foreign WriteCapability or a foreign object as issuer
    g, connection = lab_gate()
    assert g.send([PROJECT_WRITE_3, GLOBAL_WRITE], issuer=issuer) == [GateResult.REFUSED, GateResult.REFUSED]
    assert connection.written == []


def test_everything_is_dropped_while_detached_and_refusals_still_logged():
    g, _ = lab_gate()
    g.detach()
    assert g.send([PROJECT_WRITE_3, OLED, GLOBAL_READ], issuer=TOKEN) == [GateResult.DROPPED] * 3
    assert g.send([PROJECT_WRITE_3]) == [GateResult.REFUSED]
    assert [e.outcome for e in g.device_log()] == [DeviceLogOutcome.REFUSED]


def test_the_token_opens_only_the_scoped_commands():
    g, connection = lab_gate()
    assert g.send([UNKNOWN_15, UNKNOWN_16, b"\xf0\x00\x01\xf7"], issuer=TOKEN) == [GateResult.REFUSED] * 3
    assert connection.written == []


def test_hazard_lines_name_what_the_frame_would_have_done():
    g, _ = lab_gate()
    g.send([GLOBAL_WRITE, UNKNOWN_15])
    assert [e.hazard_line() for e in g.device_log()] == [
        "HAZARD refused: global-settings write", "HAZARD refused: unknown SysEx"]


# --- a29: the composed gate, without and with the lab --------------------------------------------------------
def composed_gate(tmp_path, modules):
    config = config_for(tmp_path)
    comp = root.compose(config, root.simulated_adapters(config), modules=modules)
    sim: SimulatedApc64 = comp.adapters.simulator
    comp.gate.attach(sim.open("daw", sim.address("daw")))
    return comp.gate, sim


def test_a29_a_lab_less_composition_still_refuses_every_0x13_to_0x18(tmp_path):
    gate, sim = composed_gate(tmp_path, ())
    assert gate.policy == CONTRACT1_POLICY
    assert gate.send(EVERY_MEMORY_FRAME) == [GateResult.REFUSED] * 6
    assert gate.send(EVERY_MEMORY_FRAME, issuer=TOKEN) == [GateResult.REFUSED] * 6   # no module, no scope
    assert sim.hazards == []


def test_a29_twin_a_lab_registered_composition_passes_only_token_carrying_0x14_and_0x18(tmp_path):
    gate, sim = composed_gate(tmp_path, (LabShaped(),))
    without = gate.send(EVERY_MEMORY_FRAME)
    assert without == [GateResult.SENT, GateResult.REFUSED, GateResult.REFUSED, GateResult.REFUSED,
                       GateResult.SENT, GateResult.REFUSED]        # the reads pass; no write without the token
    assert [sysex.command_of(f) for f in sim.hazards] == [SysexCommand.PROJECT_READ, SysexCommand.GLOBAL_READ]
    with_token = gate.send([PROJECT_WRITE_3, GLOBAL_WRITE, UNKNOWN_15], issuer=TOKEN)
    assert with_token == [GateResult.SENT, GateResult.SENT, GateResult.REFUSED]
    written = [sysex.command_of(f) for f in sim.hazards]
    assert written.count(SysexCommand.PROJECT_WRITE) == 1 and written.count(SysexCommand.GLOBAL_WRITE) == 1
    assert {e.hazard_line() for e in gate.device_log() if e.hazard} == {
        "HAZARD refused: project write slot 3", "HAZARD refused: global-settings write",
        "HAZARD refused: unknown SysEx"}
