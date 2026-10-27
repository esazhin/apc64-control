"""The attended live spike for the lab's slot-0 path (APC64_LIVE=1 pytest -m live; contract T30, s10; a1–a3, a16).

Run only with someone at the unit (contract §2.5: live checks enter DAW mode and write slot 0 only after backing it
up, restore slot 0 at the end and leave DAW mode; slots 1–24 and the globals are never touched here). It uses the
lab's own codec through the host's gate and session tap, never tools/.

    1. checks that Bitwig and Chrome do not hold the unit's ports (a busy port fails the test, nothing is freed)
    2. takes the unit (DAW mode on) and asks for Custom view
    3. reads slot 0 and keeps it as the backup (also saved under the test's tmp_path)
    4. writes slot 0 with pad r1c1 recoloured (odd RGB 1, 127, 128) and the aftertouch flag set (a16: press r1c1
       hard and watch the Custom port with amidi), reads it back byte for byte (a1, a3)
    5. restores the backup, reads it back, releases the unit (DAW mode off)
"""
import asyncio
import os

import pytest

from _apc64_host.application.ports import ConsentAnswer
from _apc64_host.application.session import DeviceSession
from _apc64_host.application.test_session import AGENT, Engine
from _apc64_host.application.outbound_gate import OutboundGate
from _apc64_host.application.ports import HostPorts
from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.outbound import WriteCapability
from _apc64_host.domain.unit_status import ReleaseReason
from _apc64_lab.application.guarded_writer import GuardedWriter
from _apc64_lab.application.ports import HostLink
from _apc64_lab.domain.memory import EDIT_BUFFER
from _apc64_lab.domain.pads import Rgb
from _apc64_lab.infrastructure.conftest import lab_policy
from _apc64_lab.infrastructure.unit_memory import UnitMemoryAdapter

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(os.environ.get("APC64_LIVE") != "1", reason="needs the APC64 (APC64_LIVE=1)")]


class NoPrompt:
    async def ask(self, text):
        return ConsentAnswer.DISMISSED

    def withdraw(self):
        pass


class Store:
    def __init__(self):
        self.marker = False

    def marker_set(self):
        self.marker = True

    def marker_clear(self):
        self.marker = False

    def marker_present(self):
        return self.marker

    def calibration_get(self):
        return None

    def calibration_put(self, calibration):
        pass

    def nav_get(self):
        return None

    def nav_put(self, nav, positions):
        pass


def test_slot_0_backed_up_written_read_back_and_restored_in_custom_view(tmp_path):
    from _apc64_host.infrastructure.alsa_rawmidi import AlsaRawMidi
    from _apc64_host.infrastructure.alsa_seq import AlsaSequencer
    from _apc64_host.infrastructure.clock import AsyncioClock
    from _apc64_host.infrastructure.unit_locator import AmidiUnitLocator
    from _apc64_lab.infrastructure.backup_files import BackupFiles

    async def spike():
        loop = asyncio.get_running_loop()
        dispatch = lambda fn, *args: loop.call_soon_threadsafe(fn, *args)   # noqa: E731
        seq = AlsaSequencer(dispatch=dispatch)
        locator = AmidiUnitLocator(dispatch=dispatch)
        seq.start()
        locator.start()
        capability = WriteCapability("lab live spike")
        gate = OutboundGate(lab_policy(capability))
        session = DeviceSession(locator=locator, holders=seq, port=AlsaRawMidi(holders=seq), prompt=NoPrompt(),
                                store=Store(), gate=gate, engine=Engine(), clock=AsyncioClock(), dispatch=dispatch)
        link = HostLink(HostPorts(sysex=session.sysex_tap, gate=gate))
        memory = UnitMemoryAdapter(link)
        writer = GuardedWriter(memory, BackupFiles(tmp_path / "backups"), capability, link)
        backup = saved = None
        try:
            session.start()
            await asyncio.sleep(0.5)
            answer = await session.take(AGENT)
            assert answer.result.value == "taken", f"could not take the APC64: {answer.text()} (close Bitwig/Chrome)"
            memory.request_view(UnitView.CUSTOM)
            await asyncio.sleep(0.5)
            backup = await asyncio.to_thread(writer.session_read)
            saved = writer.save_backup(EDIT_BUFFER, backup.raw)
            pad = backup.pads[0].with_fields(rest=Rgb(1, 127, 128), aftertouch=True)
            changed = backup.with_pad_records({0: pad})
            await asyncio.to_thread(writer.session_write, changed)
            assert await asyncio.to_thread(writer.session_read) == changed, "read-back differs (a3)"
            await asyncio.sleep(5)            # at the unit: pad r1c1 is the odd colour; press it hard (a16)
        finally:
            if backup is not None:
                await asyncio.to_thread(writer.session_write, backup)
                assert await asyncio.to_thread(writer.session_read) == backup, f"slot 0 not restored; see {saved}"
            await session.release(ReleaseReason.RELEASE)
            session.stop()
            locator.stop()
            seq.stop()

    asyncio.run(spike())
