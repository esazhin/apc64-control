"""The real rawmidi adapter against the attached APC64 (APC64_LIVE=1 pytest -m live; contract s80, a4, a16, A14).

Talks to the unit with the identity request and DAW-mode off only: it never enters DAW mode, never sends
0x13/0x14/0x17/0x18, and sends DAW-mode off on the way out whatever happens. It fails clearly when another
program (Chrome, Bitwig) holds a subdevice (contract a2): close it and run again; nothing is freed for you.
"""
import os
import subprocess
import time

import pytest

from _apc64_host.application.ports import PortBusy
from _apc64_host.domain.layout import UnitPortRole
from _apc64_host.domain.outbound import CONTRACT1_POLICY
from _apc64_host.infrastructure.alsa_rawmidi import AlsaRawMidi
from _apc64_host.protocol import sysex
from _apc64_host.protocol.stream import MidiStreamSplitter

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(os.environ.get("APC64_LIVE") != "1", reason="needs the APC64 (APC64_LIVE=1)")]

ROLES = {"DAW": UnitPortRole.DAW, "Notes": UnitPortRole.NOTES, "Custom": UnitPortRole.CUSTOM}


def apc64_addresses() -> dict:
    listing = subprocess.run(["amidi", "-l"], capture_output=True, text=True, timeout=5).stdout
    found = {}
    for line in listing.splitlines():
        columns = line.split(None, 2)
        if len(columns) == 3 and columns[2].startswith("APC64 "):
            word = columns[2].split()[1]
            if word in ROLES and ROLES[word] not in found:
                found[ROLES[word]] = columns[1]
    return found


def test_three_subdevices_are_held_at_once_a_second_open_is_busy_and_identity_answers():
    addresses = apc64_addresses()
    if UnitPortRole.DAW not in addresses:
        pytest.fail("no APC64 in `amidi -l`: plug the unit in")
    port = AlsaRawMidi()
    connections, written = {}, []
    try:
        for role in (UnitPortRole.DAW, UnitPortRole.NOTES, UnitPortRole.CUSTOM):
            try:
                connections[role] = port.open(role, addresses[role])
            except PortBusy:
                pytest.fail(f"APC64 {role} is busy: close any Web MIDI page or Bitwig, then run again")
        with pytest.raises(PortBusy):   # A14: nobody else can open a held subdevice
            port.open(UnitPortRole.DAW, addresses[UnitPortRole.DAW])

        replies, splitter = [], MidiStreamSplitter()
        connections[UnitPortRole.DAW].listen(lambda chunk: replies.extend(splitter.feed(chunk)), lambda: None)
        written.append(sysex.IDENTITY_REQUEST)
        connections[UnitPortRole.DAW].write(sysex.IDENTITY_REQUEST)
        deadline = time.monotonic() + 2.0
        identity = None
        while identity is None and time.monotonic() < deadline:
            identity = next((i for i in map(sysex.parse_identity, list(replies)) if i), None)
            time.sleep(0.01)
        assert identity is not None, "no identity reply within 2 s"
        assert identity.is_apc64, identity.refusal
    finally:
        daw = connections.get(UnitPortRole.DAW)
        if daw is not None:
            written.append(sysex.daw_off())
            daw.write(sysex.daw_off())
        for connection in connections.values():
            connection.close()
        assert all(CONTRACT1_POLICY.allows(sysex.command_of(frame)) for frame in written)
