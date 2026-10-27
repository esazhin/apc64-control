"""The real sequencer adapter on this machine (APC64_LIVE=1 pytest -m live; contract s82, a14).

Only lists ports, queries subscribers and connects System Announce: it never sends to or connects any port,
and never touches the APC64's ports.
"""
import os
import subprocess

import pytest

from _apc64_host.domain.layout import UnitPortRole
from _apc64_host.infrastructure.alsa_seq import CLIENT_NAME, AlsaSequencer

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(os.environ.get("APC64_LIVE") != "1", reason="needs the APC64 (APC64_LIVE=1)")]


def our_connections() -> list[str]:
    """The `aconnect -l` lines of our client's ports that show a connection."""
    lines, ours = [], False
    for line in subprocess.run(["aconnect", "-l"], capture_output=True, text=True, timeout=5).stdout.splitlines():
        if line.startswith("client "):
            ours = f"'{CLIENT_NAME}'" in line
        elif ours and "Connect" in line:
            lines.append(line.strip())
    return lines


def test_the_catalog_never_lists_the_apc64_and_our_client_never_connects_to_it():
    sequencer = AlsaSequencer()
    sequencer.start()
    try:
        names = [p.name for p in sequencer.list()]
        assert not [n for n in names if "APC64" in n.upper()]
        sequencer.holder_of(UnitPortRole.DAW)   # a query only
        connections = our_connections()
        # the only connection is System Announce into our input port, and it is there (new ports are noticed)
        assert connections and all("0:1" in line for line in connections), connections
    finally:
        sequencer.stop()
