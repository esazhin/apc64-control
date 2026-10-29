"""HarmonyTracker: what is played, folded into the harmony core's HarmonyState (contract pi7; inv15, inv16;
§2.7 q7; s19, s23 consumer; A69, A70, A78, A80; d46–d59).

Sources (§2.7 q7): the APC64's Custom and Notes ports from the host's play stream, and any other MIDI input the
user selects (a keyboard, the MPC), listened to through the host's FeedbackInputs and remembered in the lab's
settings. Session-view bindings are triggers, not played notes, and are skipped (d50, A70). A note the host
ended at a window shift clears it (NOTE_ENDED). Each source keeps its own count per note, so a release from one
source never ends a note another source holds (d46).

The guitar amendment (2026-10-27): each held voice is also kept with the channel it arrived on when the source is
the APC64's Custom port (a guitar layout sends each string on its own channel), and published as the state's
`played`, so the neck view puts a played note on its string. Other sources carry no string identity (None). The analysis itself stays in the pure, device-independent
domain/harmony core; this service only feeds it and publishes each snapshot as it is applied (A78).

The performer (Phase 2): a note it takes as a chord's root (TAKEN_VOICED) or as a control pad (TAKEN_CONTROL) is not
counted; the performer shows the voicing it plays instead (show_voicing: its notes with their strings' channels, as
the Custom port's), which never counts as held at a window shift.

After the guitar live test (2026-10-27): the trail can be cleared (clear_trail: the API, CLI and panel), the layout's
key spelling reaches the core through set_key (SessionService gives the active layout's scale overlay), and the
inputs followed are published too (kind 'inputs'), so every open page shows a choice made elsewhere.

Threads: the play stream is read on the host's loop (run(), or pump() from an action); input callbacks may
arrive on a reader thread. Both go through one lock.
"""
import asyncio
import logging
import threading
from collections import Counter
from dataclasses import replace

from _apc64_host.domain.effects import NOTE_ENDED, PlayEvent, PlaySourceKind
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.midi import NoteOff, NoteOn

from ..domain.harmony import Harmony, HarmonyState
from .ports import NOT_HELD_REASONS, HostLink, LabSettingsStore, LabStatePublisher, MemorySettings, NullPublisher

log = logging.getLogger(__name__)
INPUTS_KEY = "harmony.inputs"
INPUTS = "inputs"   # the publisher kind of the inputs followed
UNIT_KINDS = (PlaySourceKind.CUSTOM, PlaySourceKind.NOTES)
_APC64 = "apc64"
VOICING = (str(PlaySourceKind.CUSTOM), "performer voicing")   # the performer's voicing, shown on the strings


class HarmonyTracker:
    def __init__(self, publisher: LabStatePublisher | None = None, settings: LabSettingsStore | None = None,
                 link: HostLink | None = None):
        self._publisher = publisher or NullPublisher()
        self._settings = settings or MemorySettings()
        self._link = link or HostLink()
        self._lock = threading.RLock()
        self._harmony = Harmony()
        self._counts: Counter = Counter()           # (source key, note) → holds
        self._voices: Counter = Counter()           # (source key, channel or None, note) → holds (the neck view)
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
        if event.reason in NOT_HELD_REASONS:          # the performer shows its voicing itself; a control is no note
            return False
        if source.kind is PlaySourceKind.INPUT and str(source.port) not in self._inputs:
            return False
        key = (str(source.kind), str(source.port))
        channel = event.channel if source.kind is PlaySourceKind.CUSTOM else None   # a string per channel
        if event.kind == "note_on" and (event.velocity is None or event.velocity > 0):
            return self._on(key, event.note, channel)
        if event.kind in ("note_off", NOTE_ENDED) or event.kind == "note_on":
            return self._off(key, event.note, channel)
        return False

    def show_voicing(self, voices) -> None:
        """The performer's voicing as held notes on their strings ((channel, note) each; () for none), in place of
        the one shown before."""
        wanted = Counter((int(channel), int(note)) for channel, note in voices)
        with self._lock:
            shown = Counter({(c, n): k for (key, c, n), k in self._voices.items() if key == VOICING})
            if wanted == shown:
                return
            state = None
            for (channel, note), count in (shown - wanted).items():
                for _ in range(count):
                    self._counts[(VOICING, note)] -= 1
                    if self._counts[(VOICING, note)] <= 0:
                        del self._counts[(VOICING, note)]
                    self._voice_off(VOICING, channel, note)
                    state = self._harmony.note_off(note)
            for (channel, note), count in (wanted - shown).items():
                for _ in range(count):
                    self._counts[(VOICING, note)] += 1
                    self._voices[(VOICING, channel, note)] += 1
                    state = self._harmony.note_on(note)
            state = self._with_voices(state if state is not None else self._harmony.state())
        self._publish(state)

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
        self.publish_inputs()
        return {**self.inputs(), "message": "harmony follows the APC64" + (
            " and " + ", ".join(names) if names else " only")}

    def publish_inputs(self) -> None:
        """The inputs followed, on the lab topic as kind 'inputs' (each page's ticks follow a choice made elsewhere)."""
        self._publish({"kind": INPUTS, **self.inputs()})

    # === the trail and the key (2026-10-27) ================================================================
    def clear_trail(self) -> dict:
        with self._lock:
            state = self._with_voices(self._harmony.clear_trail())
        self._publish(state)
        return {"trail": [], "message": "trail cleared"}

    def set_key(self, key) -> None:
        """The active layout's key spelling (pitch class → name), or None: held notes are spelled in it."""
        with self._lock:
            changed = self._harmony.set_key(key)
            state = self._with_voices(self._harmony.state()) if changed else None
        if state is not None:
            self._publish(state)

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
    def _on(self, key, note, channel=None) -> bool:
        with self._lock:
            self._counts[(key, int(note))] += 1
            self._voices[(key, channel, int(note))] += 1
            state = self._with_voices(self._harmony.note_on(int(note)))
        self._publish(state)
        return True

    def _off(self, key, note, channel=None) -> bool:
        with self._lock:
            if self._counts[(key, int(note))] <= 0:
                self._counts.pop((key, int(note)), None)
                return False                    # a release already ended (window shift) or never seen
            self._counts[(key, int(note))] -= 1
            if not self._counts[(key, int(note))]:
                del self._counts[(key, int(note))]
            self._voice_off(key, channel, int(note))
            state = self._with_voices(self._harmony.note_off(int(note)))
        self._publish(state)
        return True

    def _voice_off(self, key, channel, note) -> None:
        """One hold of that voice ends; a release on a channel never seen ends another hold of the note instead."""
        voice = (key, channel, note)
        if self._voices[voice] <= 0:
            self._voices.pop(voice, None)
            voice = next((v for v in self._voices if v[0] == key and v[2] == note), None)
            if voice is None:
                return
        self._voices[voice] -= 1
        if not self._voices[voice]:
            del self._voices[voice]

    def _with_voices(self, state: HarmonyState) -> HarmonyState:
        played = sorted(((key[0], channel, note) for (key, channel, note), n in self._voices.items() for _ in range(n)),
                        key=lambda v: (v[2], v[1] or 0, v[0]))
        return replace(state, played=tuple(played))

    def _end_source(self, key) -> None:
        with self._lock:
            held = [(k, n) for (k, n) in self._counts if k == key]
            state = None
            for item in held:
                for _ in range(self._counts.pop(item)):
                    state = self._harmony.note_off(item[1])
            for voice in [v for v in self._voices if v[0] == key]:
                del self._voices[voice]
            if state is not None:
                state = self._with_voices(state)
        if state is not None:
            self._publish(state)

    def held_notes(self, kind: PlaySourceKind = PlaySourceKind.CUSTOM) -> tuple[int, ...]:
        """The notes a source kind holds now, lowest first (SessionService ends them at a shift, d47)."""
        self.pump()
        with self._lock:
            return tuple(sorted({n for (k, n), c in self._counts.items() if c > 0 and k[0] == str(kind)
                                 and k != VOICING}))

    def state(self) -> HarmonyState:
        with self._lock:
            return self._with_voices(self._harmony.state())

    def _publish(self, state: "HarmonyState | dict") -> None:
        try:
            self._publisher.publish(state)
        except Exception:
            log.exception("lab: publishing the harmony state failed")
