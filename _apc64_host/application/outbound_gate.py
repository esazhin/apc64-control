"""OutboundGate: the only writer to the APC64 (contract §7.1, inv15, inv11, a6, a18).

Every frame offered to the unit is classified (protocol.sysex.command_of) and checked against the injected
OutboundPolicy (CONTRACT1_POLICY plus whatever registered modules add). A refused frame never reaches the
connection and is logged as a hazard, held or not. Allowed frames go to the attached DAW connection one
message per write, under one lock, so frames from different callers never interleave (the single write
queue). While nothing is attached (the unit is not held) allowed frames are dropped silently.

Contract 2 (inv2, a10): send(frames, issuer) takes the caller's WriteCapability. A command the policy scopes to
a capability (the lab's 0x14/0x18) passes only when the frame comes with that very token; every other caller's
frame of it is refused and logged ('HAZARD refused: project write slot 3') and never reaches the connection.
Without an issuer the gate behaves exactly as contract 1 built it.

Only this module calls UnitConnection.write; the layering test enforces it.
"""
import logging
import threading
import time
from collections import deque
from enum import StrEnum
from typing import Callable, Iterable

from ..domain.outbound import DeviceLogEntry, DeviceLogOutcome, OutboundPolicy, WriteCapability
from ..protocol.sysex import command_of
from .ports import PortGone, UnitConnection

log = logging.getLogger(__name__)
DEVICE_LOG_SIZE = 2000


class GateResult(StrEnum):
    SENT = "sent"
    REFUSED = "refused"
    DROPPED = "dropped"


class OutboundGate:
    def __init__(self, policy: OutboundPolicy, log_size: int = DEVICE_LOG_SIZE,
                 wall: Callable[[], float] = time.time):
        self._policy = policy
        self._wall = wall
        self._lock = threading.Lock()
        self._connection: UnitConnection | None = None
        self._log: deque[DeviceLogEntry] = deque(maxlen=log_size)

    @property
    def policy(self) -> OutboundPolicy:
        return self._policy

    # --- the session's side --------------------------------------------------------------------------
    def attach(self, connection: UnitConnection) -> None:
        with self._lock:
            self._connection = connection

    def detach(self) -> None:
        with self._lock:
            self._connection = None

    @property
    def attached(self) -> bool:
        return self._connection is not None

    # --- everyone's side -----------------------------------------------------------------------------
    def send(self, frames: Iterable[bytes], issuer: WriteCapability | None = None) -> list[GateResult]:
        """SENT, REFUSED or DROPPED per frame, in order. A failing write detaches the connection and raises
        PortGone (the frames before it were written; the ones after it are not). `issuer` is the caller's
        WriteCapability, if it holds one; anything else counts as no token."""
        if not isinstance(issuer, WriteCapability):
            issuer = None
        results: list[GateResult] = []
        with self._lock:
            for frame in frames:
                frame = bytes(frame)
                command = command_of(frame)
                if not self._policy.allows(command, issuer):
                    entry = DeviceLogEntry(self._wall(), frame, DeviceLogOutcome.REFUSED, command)
                    self._log.append(entry)
                    log.warning("%s; never sent to the APC64 (%s)", entry.hazard_line(), frame.hex(" "))
                    results.append(GateResult.REFUSED)
                    continue
                if self._connection is None:
                    results.append(GateResult.DROPPED)
                    continue
                try:
                    self._connection.write(frame)
                except PortGone:
                    self._connection = None
                    raise
                self._log.append(DeviceLogEntry(self._wall(), frame, DeviceLogOutcome.SENT, command))
                results.append(GateResult.SENT)
        return results

    def device_log(self) -> list[DeviceLogEntry]:
        """Every frame sent or refused, oldest first (the ring keeps the latest DEVICE_LOG_SIZE)."""
        with self._lock:
            return list(self._log)
