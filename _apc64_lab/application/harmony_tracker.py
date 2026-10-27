"""HarmonyTracker: what is played, folded into the harmony core's HarmonyState (contract pi7; inv15, inv16;
§2.7 q7; s19, s23 consumer; A69, A70, A78, A80; d46–d59).

Sources (§2.7 q7): the APC64's Custom and Notes ports from the host's play stream, and any other MIDI input the
user selects (a keyboard, the MPC), listened to through the host's FeedbackInputs and remembered in the lab's
settings. Session-view bindings are triggers, not played notes, and are skipped (d50, A70). A note the host
ended at a window shift clears it (NOTE_ENDED). Each source keeps its own count per note, so a release from one
source never ends a note another source holds (d46). The analysis itself stays in the pure, device-independent
domain/harmony core; this service only feeds it and publishes each snapshot as it is applied (A78).

Threads: the play stream is read on the host's loop (run(), or pump() from an action); input callbacks may
arrive on a reader thread. Both go through one lock.
"""
import asyncio
import logging
import threading
from collections import Counter

from _apc64_host.domain.effects import NOTE_ENDED, PlayEvent, PlaySourceKind
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.midi import NoteOff, NoteOn

from ..domain.harmony import Harmony, HarmonyState
from .ports import HostLink, LabSettingsStore, LabStatePublisher, MemorySettings, NullPublisher

log = logging.getLogger(__name__)
INPUTS_KEY = "harmony.inputs"
UNIT_KINDS = (PlaySourceKind.CUSTOM, PlaySourceKind.NOTES)
_APC64 = "apc64"


class HarmonyTracker:
    def __init__(self, publisher: LabStatePublisher | None = None, settings: LabSettingsStore | None = None,
                 link: HostLink | None = None):
        self._publisher = publisher or NullPublisher()
        self._settings = settings or MemorySettings()
        self._link = link or HostLink()
        self._lock = threading.RLock()
        self._harmony = Harmony()
        self._counts: Counter = Counter()           # (source key, note) → holds
        self._subscription = None
        self._listeners: dict[str, object] = {}
        self._stopped = False
        self._inputs: list[str] = [str(p) for p in (self._settings.get(INPUTS_KEY, []) or [])]

    # === the play stream ===================================================================================
    def start(self) -> None:
        """Subscribe to the play stream and listen to the remembered inputs (once the host ports are bound)."""
        stream = self._link.stream
        if stream is not None and self._subscription is None:
            self._subscription = stream.subscribe()
        for port in self._inputs:
            self._listen(port)

    async def run(self) -> None:
        """Reads the play stream in played order until stopped; a closed subscription is renewed (s19)."""
        self.start()
        while not self._stopped:
            subscription = self._subscription
            if subscription is None:
                await asyncio.sleep(0.5)
                self.start()
                continue
            item = await subscription.next()
            self._take(item)

    def pump(self) -> None:
        """Everything the stream has delivered so far, now (an action on the loop needs the held notes)."""
        subscription = self._subscription
        if subscription is None:
            return
        for item in subscription.take():
            self._take(item)

    def _take(self, item) -> None:
        if isinstance(item, PlayEvent):
            self.apply(item)
            return
        log.info("lab: the play stream closed (%s); subscribing again", getattr(item, "reason", item))
        self._subscription = None
        if not self._stopped:
            self.start()

    def stop(self) -> None:
        self._stopped = True
        subscription, self._subscription = self._subscription, None
        if subscription is not None:
            subscription.cancel()
        for listener in self._listeners.values():
            listener.cancel()
        self._listeners.clear()

    def apply(self, event: PlayEvent) -> bool:
        """One play-stream event; True when it changed what is held (and a snapshot was published)."""
        source = event.port
        if source is None or not source.played:                                        # A70, d50
            return False
        if source.kind is PlaySourceKind.INPUT and str(source.port) not in self._inputs:
            return False
        key = (str(source.kind), str(source.port))
        if event.kind == "note_on" and (event.velocity is None or event.velocity > 0):
            return self._on(key, event.note)
        if event.kind in ("note_off", NOTE_ENDED) or event.kind == "note_on":
            return self._off(key, event.note)
        return False

    # === other MIDI inputs (§2.7 q7) =======================================================================
    def inputs(self) -> dict:
        return {"apc64": ["APC64 Custom", "APC64 Notes"], "inputs": list(self._inputs)}

    def select_inputs(self, ports) -> dict:
        """The inputs to follow besides the APC64, remembered; the API, CLI and panel set them alike."""
        names = []
        for port in ports or []:
            name = " ".join(str(port).split())
            if not name:
                continue
            if _APC64 in name.casefold():
                raise DomainInvariantError("inputs", f"{name} is the APC64's own port",
                                           "the APC64's Custom and Notes ports are followed already")
            if name not in names:
                names.append(name)
        with self._lock:
            dropped = [p for p in self._inputs if p not in names]
            self._inputs = names
        for port in dropped:
            listener = self._listeners.pop(port, None)
            if listener is not None:
                listener.cancel()
            self._end_source(("input", port))
        for port in names:
            self._listen(port)
        self._settings.put(INPUTS_KEY, list(names))
        return {**self.inputs(), "message": "harmony follows the APC64" + (
            " and " + ", ".join(names) if names else " only")}

    def _listen(self, port: str) -> None:
        inputs = self._link.inputs
        if inputs is None or port in self._listeners:
            return
        try:
            self._listeners[port] = inputs.listen(port, lambda message, port=port: self.on_input(port, message))
        except Exception:
            log.exception("lab: listening to %s failed", port)

    def on_input(self, port: str, message) -> bool:
        key = ("input", str(port))
        if isinstance(message, NoteOn) and int(message.velocity) > 0:
            return self._on(key, int(message.note))
        if isinstance(message, (NoteOn, NoteOff)):
            return self._off(key, int(message.note))
        return False

    # === held notes ========================================================================================
    def _on(self, key, note) -> bool:
        with self._lock:
            self._counts[(key, int(note))] += 1
            state = self._harmony.note_on(int(note))
        self._publish(state)
        return True

    def _off(self, key, note) -> bool:
        with self._lock:
            if self._counts[(key, int(note))] <= 0:
                self._counts.pop((key, int(note)), None)
                return False                    # a release already ended (window shift) or never seen
            self._counts[(key, int(note))] -= 1
            if not self._counts[(key, int(note))]:
                del self._counts[(key, int(note))]
            state = self._harmony.note_off(int(note))
        self._publish(state)
        return True

    def _end_source(self, key) -> None:
        with self._lock:
            held = [(k, n) for (k, n) in self._counts if k == key]
            state = None
            for item in held:
                for _ in range(self._counts.pop(item)):
                    state = self._harmony.note_off(item[1])
        if state is not None:
            self._publish(state)

    def held_notes(self, kind: PlaySourceKind = PlaySourceKind.CUSTOM) -> tuple[int, ...]:
        """The notes a source kind holds now, lowest first (SessionService ends them at a shift, d47)."""
        self.pump()
        with self._lock:
            return tuple(sorted({n for (k, n), c in self._counts.items() if c > 0 and k[0] == str(kind)}))

    def state(self) -> HarmonyState:
        with self._lock:
            return self._harmony.state()

    def _publish(self, state: HarmonyState) -> None:
        try:
            self._publisher.publish(state)
        except Exception:
            log.exception("lab: publishing the harmony state failed")
