"""In-memory MIDI ports for the simulated run (TargetPorts, FeedbackInputs and PortCatalog without ALSA).

`python -m _apc64_host --simulate` uses these with the simulated APC64 so a development run touches no ALSA
device at all. Ports are names; a device's pattern resolves as the sequencer adapter does it (exact name, any
case, else the one name containing it; none or several → MISSING). Every send is recorded in `sent`;
deliver() plays a message into the listeners of a port (feedback, MIDI-learn); plug()/unplug() change
presence like a port appearing or vanishing (d61). listen_realtime()/deliver_realtime() do the same for MIDI clock
bytes with their arrival times (the performer's clock input, contract 2 §2.10).
"""
import threading
import time
from typing import Callable

from ..application.ports import PortDirection, PortInfo, SendResult
from ..domain.midi import MidiMessage

# example ports for the simulated rig (the author's gear); a real run lists the machine's own ALSA ports
DEFAULT_PORTS = ("MPC Live III MIDI 1", "Bitwig Studio In", "USB MIDI Interface MIDI 1")


class _Listener:
    def __init__(self, owner: "MemoryPorts", pattern: str, callback: Callable, realtime: bool = False):
        self.owner, self.pattern, self.callback = owner, pattern, callback
        self.realtime = realtime
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        with self.owner._lock:
            if self in self.owner._listeners:
                self.owner._listeners.remove(self)


class MemoryPorts:
    def __init__(self, names=DEFAULT_PORTS, keep: int = 1000):
        self._names = list(names)
        self._keep = keep
        self._lock = threading.Lock()
        self._listeners: list[_Listener] = []
        self._presence: list[Callable[[str, bool], None]] = []
        self.sent: list[tuple[str, MidiMessage]] = []

    # --- PortCatalog ----------------------------------------------------------------------------------
    def list(self) -> list[PortInfo]:
        with self._lock:
            return [PortInfo(name, PortDirection.BOTH, True) for name in self._names]

    def resolve(self, pattern: str) -> str | None:
        with self._lock:
            names = list(self._names)
        wanted = str(pattern).casefold()
        exact = [n for n in names if n.casefold() == wanted]
        if exact:
            return exact[0]
        part = [n for n in names if wanted in n.casefold()]
        return part[0] if len(part) == 1 else None

    # --- TargetPorts ----------------------------------------------------------------------------------
    def send(self, port: str, message: MidiMessage) -> SendResult:
        name = self.resolve(port)
        if name is None:
            return SendResult.MISSING
        with self._lock:
            self.sent.append((name, message))
            del self.sent[:-self._keep]
        return SendResult.SENT

    def subscribe_presence(self, callback: Callable[[str, bool], None]) -> None:
        self._presence.append(callback)

    # --- FeedbackInputs -------------------------------------------------------------------------------
    def listen(self, port: str, callback: Callable[[MidiMessage], None]) -> _Listener:
        listener = _Listener(self, str(port), callback)
        with self._lock:
            self._listeners.append(listener)
        return listener

    def listen_realtime(self, port: str, callback: Callable[[int, float], None]) -> _Listener:
        """MIDI clock bytes from `port`: callback(status, time)."""
        listener = _Listener(self, str(port), callback, realtime=True)
        with self._lock:
            self._listeners.append(listener)
        return listener

    # --- the simulated world --------------------------------------------------------------------------
    def deliver_realtime(self, port: str, status: int, at: float | None = None) -> int:
        """A clock (0xF8), Start, Continue or Stop byte arriving on `port` at `at` (default: now)."""
        at = time.monotonic() if at is None else float(at)
        with self._lock:
            listeners = [l for l in self._listeners if l.realtime and not l.cancelled]
        heard = 0
        for listener in listeners:
            if self.resolve(listener.pattern) == port:
                listener.callback(int(status), at)
                heard += 1
        return heard

    def deliver(self, port: str, message: MidiMessage) -> int:
        """Plays `message` as arriving on `port`; returns how many listeners heard it."""
        with self._lock:
            listeners = [l for l in self._listeners if not l.cancelled and not l.realtime]
        heard = 0
        for listener in listeners:
            if self.resolve(listener.pattern) == port:
                listener.callback(message)
                heard += 1
        return heard

    def plug(self, name: str) -> None:
        with self._lock:
            if name in self._names:
                return
            self._names.append(name)
        for callback in list(self._presence):
            callback(name, True)

    def unplug(self, name: str) -> None:
        with self._lock:
            if name not in self._names:
                return
            self._names.remove(name)
        for callback in list(self._presence):
            callback(name, False)
