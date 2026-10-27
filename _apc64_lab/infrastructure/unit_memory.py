"""UnitMemory and UnitControl over the host's outbound gate and the session's SysEx tap (contract s6 supplier,
s7–s10 consumer; inv1, inv2, inv4; a1–a3, a32, a33; A51).

- Reads (0x13 project, 0x17 globals) and the view request (0x19) go through the gate with no issuer; the
  writes (0x14, 0x18) carry the WriteCapability GuardedWriter passes in, per call. The adapter keeps no token.
- Replies come through the session's SysEx tap (reassembled even when channel messages arrive between the
  pieces of a 1015-byte dump, a33), filtered by slot (byte 7 of the dump). The tap's callbacks run on the reader
  thread (or inside the gate's send with the simulator); waits here only watch an event.
- Faults map as s6.c3 says: no answer within 2 s → NoReply; not 880/56 raw bytes → MalformedReply (A51); nothing
  held or the gate DROPPED the frame → NotHeld; an unplug during the call (PortGone, or the tap's holding ended)
  → Gone; another firmware than 1.2.1.6 → WrongFirmware for writes (a32); the gate refusing a frame → Refused.
- abort() makes every wait in flight end at once as Gone (the release is under way); resume() undoes it.
"""
import threading
import time
from typing import Callable

from _apc64_host.application.outbound_gate import GateResult
from _apc64_host.application.ports import PortGone
from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.outbound import SysexCommand
from _apc64_host.protocol.sysex import KNOWN_FIRMWARE

from ..application.ports import (
    READ_TIMEOUT, Gone, HostLink, Interrupted, MalformedReply, NoReply, NotHeld, Refused, WrongFirmware,
)
from ..domain.memory import Slot
from ..domain.memory_sysex import (
    Malformed, global_read_frame, global_write_frame, parse_global_dump, parse_project_dump, project_read_frame,
    project_write_frame, view_request_frame,
)
from ..domain.records import GlobalSettings, ProjectRecord

POLL = 0.002


class UnitMemoryAdapter:
    def __init__(self, link: HostLink, timeout: float = READ_TIMEOUT, poll: float = POLL,
                 known_firmware: str = KNOWN_FIRMWARE, monotonic: Callable[[], float] = time.monotonic):
        self._link = link
        self._timeout, self._poll = timeout, poll
        self._known = known_firmware
        self._now = monotonic
        self._aborted = threading.Event()

    # --- holding ----------------------------------------------------------------------------------------
    def _held(self):
        tap = self._link.sysex
        unit = tap.held() if tap is not None else None
        if unit is None or self._link.gate is None:
            raise NotHeld()
        return unit

    def check_writable(self) -> None:
        unit = self._held()
        identity = getattr(unit, "identity", None)
        firmware = str(getattr(identity, "firmware", "") or "unknown")
        if firmware != self._known:
            raise WrongFirmware(firmware, self._known)

    def abort(self) -> None:
        self._aborted.set()

    def resume(self) -> None:
        self._aborted.clear()

    # --- reads ------------------------------------------------------------------------------------------
    def read_project(self, slot: Slot, interrupt: Callable[[], bool] | None = None) -> ProjectRecord:
        slot = Slot(slot)
        frame = self._exchange(project_read_frame(slot), {SysexCommand.PROJECT_WRITE},
                               lambda reply: len(reply) > 8 and reply[7] == slot, interrupt)
        parsed = parse_project_dump(frame)
        if isinstance(parsed, Malformed):
            raise MalformedReply(parsed)
        return parsed[1]

    def read_globals(self, interrupt: Callable[[], bool] | None = None) -> GlobalSettings:
        frame = self._exchange(global_read_frame(), {SysexCommand.GLOBAL_WRITE}, lambda reply: True, interrupt)
        parsed = parse_global_dump(frame)
        if isinstance(parsed, Malformed):
            raise MalformedReply(parsed)
        return parsed

    def _exchange(self, request: bytes, commands, wanted, interrupt) -> bytes:
        if self._aborted.is_set():
            raise Gone("the APC64 is being released")
        self._held()
        tap = self._link.sysex
        arrived = threading.Event()
        box: dict = {}

        def on_frame(frame: bytes) -> None:
            if "frame" not in box and wanted(frame):
                box["frame"] = bytes(frame)
                arrived.set()

        def on_end(reason) -> None:
            box["ended"] = reason
            arrived.set()

        subscription = tap.subscribe(commands, on_frame, on_end)
        try:
            self._send([request])
            deadline = self._now() + self._timeout
            while not arrived.wait(self._poll):
                if self._aborted.is_set():
                    raise Gone("the APC64 is being released")
                if interrupt is not None and interrupt():
                    raise Interrupted("a newer slot-0 write is due")
                if self._now() >= deadline:
                    raise NoReply(f"no answer within {self._timeout:g} s")
            if "frame" not in box:
                raise Gone(f"the holding ended ({box.get('ended')})")
            return box["frame"]
        finally:
            subscription.cancel()

    # --- writes -----------------------------------------------------------------------------------------
    def write_project(self, slot: Slot, record: ProjectRecord, capability) -> None:
        self.check_writable()
        self._send([project_write_frame(Slot(slot), record)], capability)

    def write_globals(self, settings: GlobalSettings, capability) -> None:
        self.check_writable()
        self._send([global_write_frame(settings)], capability)

    def _send(self, frames, capability=None) -> None:
        if self._aborted.is_set():
            raise Gone("the APC64 is being released")
        gate = self._link.gate
        if gate is None:
            raise NotHeld()
        try:
            results = gate.send(frames, issuer=capability) if capability is not None else gate.send(frames)
        except PortGone as error:
            raise Gone(str(error) or "the APC64 went away") from None
        if any(result is GateResult.REFUSED for result in results):
            raise Refused("the outbound gate refused the frame")
        if any(result is GateResult.DROPPED for result in results):
            raise NotHeld()

    # --- UnitControl ------------------------------------------------------------------------------------
    def request_view(self, view: UnitView = UnitView.CUSTOM) -> bool:
        """Through the host when it offers it (the view is then assumed, as the unit never reports a requested
        change, 2026-10-27); else straight through the gate."""
        views = self._link.views
        if views is not None:
            return bool(views.request_view(view))
        try:
            self._send([view_request_frame(view)])
        except (NotHeld, Gone, Refused):
            return False
        return True
