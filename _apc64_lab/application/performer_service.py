"""PerformerService: the pure performer (performer/) played over what is held on a generated layout (contract 2
§2.10).

Wiring. The host offers every message played on the unit's Custom port to the lab (take_played) before its router.
While a performer is on for the active generated layout, this service takes the notes and their aftertouch: the
lane is the arrival channel (the guitar sends string n on channel n), the pure engine decides what sounds, and its
events go back to the host as messages on the lane's channel (HostLink.perform), routed like the unit's own playing
to the layout's note target on the rule's channel. Strip CCs and everything else stay the router's. Without a
performer the lab takes nothing, so routing is exactly as before. The harmony views follow what is held: the host
still publishes each taken note, and the performer's own notes come from the PERFORMER source, which is not harmony
input.

Timing. A PerformerTimer (infrastructure: a thread on the monotonic clock) calls tick(now) at the engine's next due
time; an input plays out at once (advance_to(now)) and wakes the timer. The tempo is a BPM or the MIDI clock of a
chosen input (performer.ClockFollower over the sequencer's realtime bytes); the phase stays locked to the press.

Settings. A layout's 'performer:' block (domain/performer_block.py) turns the performer on at activation with its
pattern, latch, play mode and tempo; the page, the API and the CLI change them for the session (not the file), and
may turn a performer on for a generated layout without the block (the unit's Play and Stop then stay unbound). A
reload of the same layout with the same block (a base or scheme tweak) keeps the session's choices.

Edges. A release whose press the engine never saw (held before the performer was on) goes to the router, which
routed the press; a release of a note ended at a window shift (end_held) is taken and sends nothing. Leaving the
layout, leaving Custom view and releasing the unit end every note the performer started.

Editing (Phase 2). The page's editor sends the pattern it edits as data with the id of the pattern it edits
(change(pattern_data=…, edits=id); None for a new one, never saved): it plays at once from the next step, without a
restart. Unsaved edits are kept per pattern for the session (not across a restart of the service): choosing a
pattern by any route (the page, a slot pad, the API, the CLI) plays its kept edit, marked edited; an edit of a
pattern other than the one playing (a stale page) is refused; Save writes the edit and drops it, Revert drops it and
plays the file, Delete drops it; one new pattern may be kept too (new_pattern plays it again). The state lists the
kept edits and counts every change of the pattern playing (pattern_revision), so a page's draft can follow changes
made elsewhere. save_pattern, delete_pattern and restore_pattern write through the PatternLibrary (validated first,
every replaced text kept as a version); a written file that is the one playing unedited plays from its next step,
and a write from elsewhere keeps a kept edit, whose base hash then refuses its Save as stale.

Chord types and pattern slots (Phase 2). The block's `chords` and `slots` are on the guitar's free rows
(domain/performer_pads.py: notes on channel 16, taken here and never forwarded; a selection rewrites slot 0, latest
wins, through the session's repaint), and on 7 or 8 strings on Shift + a pad (the engine's Shift state, read on the
loop; the note still arrives on the Custom port and is taken, its release too). A chosen chord type latches until
another is chosen or the same pad pressed again (off: fretted). With one, a single note held on a pattern string is
the root: the voicing (performer.build_voicing: the strings, the root's string and fret, the type) is what the engine
holds, one note per string pressed together, its muted strings marked; several notes held are fretted as before; a
type changed while the root is held re-voices (the strings that change end at once, the next hits play the new
notes). Manual strings stay the player's. What the player holds is one record over every string (_physical): a press
on a manual string goes to the engine at once, as played; what the engine holds on the pattern strings is kept in
step with the rest by one diff (_sync), so fretted playing reaches the engine press for press as in Phase 1. Every
pattern change partitions the record again (_set_pattern), since the new pattern's manual strings may differ: a held
string that became manual stays silent until plucked again, one that became a pattern string plays its held note from
its next hit, and every release finds its note, so nothing sticks and the pattern stops once all is let go. The harmony
views show the voicing: the root press is taken as TAKEN_VOICED (not counted) and the voicing's notes go to the
tracker's voicing source (show_voicing) with their strings' channels. The chord's root for the engine's chord-aware
lanes is the voicing's root, else the harmony core's chord of what is held (find_chord_matches).

Chords in key (2026-10-29). The key is the active layout's scale (its scheme: scale, scale and root), as the session
plays it: the page's Key changes it for the session (SessionService.set_key), and the session hands it over at every
change (set_key). The chord types 'key' and 'key 7' voice the key's own triad or seventh from the root held
(performer.diatonic_chord: a seven-note scale's thirds, named by their intervals: Dm7, Bm7b5); strict: a root out of
key plays nothing, and without a key (or with a scale of another size) they cannot be chosen; a key taken away lets
go of them. Several notes held are fretted, as with every type.

Threads: take_played and the actions arrive on the host's loop, tick on the timer's thread, clock bytes on the
sequencer's reader thread; one lock guards the engine. Publishing and sending happen outside it. The state published
at every step reads no file: the pattern list is read again only at a change, a layout load or an API read
(state(fresh=True)), and the pattern shown is the engine's own.
"""
import logging
import threading
import time
from collections import Counter
from typing import Callable

from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.layout import UnitPortRole
from _apc64_host.domain.midi import NoteOff, NoteOn, PolyAftertouch
from performer import (
    ALT_LANE, CHORD_TYPES, DEFAULT_TYPES, KEY_7, KEY_TYPES, PLAY_MODES, ROOT_LANE, STRINGS, VOICES, ClockFollower,
    Performer, VoicingError, build_voicing, chord_type, diatonic_chord, key_type,
)
from performer.clock import TICK
from performer.engine import MAX_BPM, MIN_BPM

from ..domain.harmony.chords import find_chord_matches
from ..domain.harmony.spelling import pc_name
from ..domain.lab_section import LabDefinition
from ..domain.performer_block import DEFAULT_BPM, PerformerSettings, find_pattern
from ..domain.performer_pads import CONTROL_CHANNEL, SLOTS, TYPES, control_of, control_pads, control_rows
from .pattern_library import PatternLibrary, PatternRefused, content_hash, pattern_json
from .ports import TAKEN, TAKEN_CONTROL, TAKEN_VOICED, HostLink, NullPublisher, PerformerTimer

log = logging.getLogger(__name__)
KIND = "performer"
CONTROLS = "Play: latch on/off · Stop: stop the pattern"
NO_CONTROLS = "the unit's Play and Stop control a performer written in the layout (a 'performer:' block)"
NOT_ACTIVE = "no generated layout is active"
NO_EDIT = object()           # save_pattern: a write that is not the editor's save of a kept edit
AUTO = "auto"                # the clock choice that follows whichever input sends a clock
HEARD = 5.0                  # seconds: the inputs a clock was heard from this recently are listed
ROWS_TEXT = {(TYPES, SLOTS): "top row: chord types · bottom row: pattern slots",
             (SLOTS,): "Shift + a pad: the chord type of its column · top row: pattern slots",
             (): "Shift + a pad: the chord type of its column · Shift + a top-row pad: the pattern slot"}


def ascii_name(pc: int) -> str:
    """A pitch class for the OLED (ASCII): C, C#, Eb …"""
    return pc_name(pc).replace("♯", "#").replace("♭", "b")


class PerformerUnavailable(Exception):
    """No generated layout is active: there is nothing to play a pattern over."""


class PerformerService:
    def __init__(self, patterns: PatternLibrary, link: HostLink, publisher=None, timer: PerformerTimer | None = None,
                 generators: Callable[[], dict] | None = None, flash: Callable[[str], None] | None = None,
                 repaint: Callable[[], None] | None = None, window: Callable[[str], int | None] | None = None,
                 show: Callable[[tuple], None] | None = None):
        self._patterns, self._link = patterns, link
        self._publisher = publisher or NullPublisher()
        self._timer = timer
        self._generators = generators or (lambda: {})
        self._flash = flash
        self._lock = threading.RLock()
        self._now = timer.now if timer is not None else time.monotonic
        self._layout_id: str | None = None
        self._layout_name: str | None = None
        self._settings: PerformerSettings | None = None
        self._strings: list[tuple[int, int, int]] = []        # (string number, open note, channel), highest first
        self._channel_lane: dict[int, int] = {}
        self._core: Performer | None = None
        self._enabled = False
        self._pattern_id: str | None = None
        self._latch = False
        self._play: str | None = None                          # None: the pattern's own play mode
        self._bpm = DEFAULT_BPM
        self._clock_port: str | None = None                    # None: the BPM; an input; or AUTO
        self._clock_listeners: dict[str, object] = {}          # input → its realtime listener
        self._listening_for: str | None = None                 # the clock choice the listeners are for
        self._followers: dict[str, ClockFollower] = {}         # input → the tempo of its clock
        self._following: str | None = None                     # the input whose clock sets the tempo
        self._heard: dict[str, float] = {}                     # input → when its latest clock tick came
        self._measured: float | None = None                    # the tempo the clock last gave the engine
        self._alive = False                                    # the clock followed is ticking now
        self._watching = False                                 # a check for the clock stopping is due
        self._presence = False                                 # subscribed to the inputs appearing and going
        self._ended: Counter = Counter()                       # (lane, note) ended at a window shift, still pressed
        self._message: str | None = None
        self._shown: tuple | None = None                       # (running, step) last published
        self._started = False
        self._listing: list[dict] = []                         # the pattern files, as last read
        self._shown_pattern: tuple | None = None               # (Pattern, lanes, id, hash, its JSON): computed once
        self._edits: dict[str | None, tuple] = {}              # id (None: a new one) → (its unsaved Pattern, base hash)
        self._revision = 0                                     # counts the changes of the pattern playing
        self._shown_after = None                               # the voicing to show after _play_kept
        self._repaint = repaint or (lambda: None)              # the session writes slot 0 again (the control pads)
        self._window = window or (lambda layout_id: None)      # the window's transposition of a layout (Shift + pad)
        self._show_voices = show or (lambda voices: None)      # the harmony tracker's show_voicing
        self._frets = 24
        self._types: tuple[str, ...] = DEFAULT_TYPES          # the chord types on the type pads
        self._slots: tuple[str | None, ...] = ()               # the patterns on the slot pads
        self._rows: dict[str, int] = {}                        # the control rows the layout has (performer_pads)
        self._type: str | None = None                          # the chord type chosen (None: fretted)
        self._slot: int | None = None                          # the slot of the pattern playing, 0-based
        self._physical: dict[int, list[tuple[int, int]]] = {}  # strings: what the player holds, on every string
        self._fed: dict[int, list[tuple[int, int]]] = {}       # what the engine holds on the pattern strings (the diff)
        self._uncounted: set[tuple[int, int]] = set()          # presses taken as a voiced root (not harmony input)
        self._voicing = None                                   # the Voicing the engine holds, or None
        self._commands: set[tuple[int, int]] = set()           # (channel, note) of Shift + pad commands still held
        self._said: str | None = None                          # a chord to flash once the lock is let go
        self._key: dict | None = None                          # the layout's key: {root, pcs, scale, name}, or None
        self._kind = None                                      # the ChordType of the voicing held (a key's own too)

    # === the timer =========================================================================================
    def start(self) -> None:
        if self._timer is not None and not self._started:
            self._started = True
            self._timer.start(self.tick)

    def stop(self) -> None:
        self.silence()
        self._unfollow()
        if self._timer is not None and self._started:
            self._started = False
            self._timer.stop()

    def tick(self, now: float) -> float | None:
        """The timer's call: every event due by now goes out; answers when the next one is due."""
        with self._lock:
            core = self._core
            if core is None:
                return None
            events = core.advance_to(now)
            due = core.next_time()
        self._send(events)
        self._publish_if_moved()
        return due

    def _wake(self) -> None:
        if self._timer is not None:
            self._timer.wake()

    # === the host's events =================================================================================
    def on_layout_loaded(self, layout, section) -> None:
        if not isinstance(section, LabDefinition):
            self._unload()
            return
        layout_id = str(getattr(layout, "id", "") or "")
        strings = self._strings_of(section)
        frets = self._frets_of(section)
        with self._lock:
            self._frets = frets
            same = layout_id == self._layout_id and section.performer == self._settings
            self._layout_name = getattr(layout, "display_name", None) or layout_id
            if same and strings == self._strings and self._core is not None:
                return
            events = self._silenced()
            self._layout_id, self._strings = layout_id, strings
            self._channel_lane = {channel: number for number, _, channel in strings}
            if not same:
                self._fresh(section.performer)
            self._rows = self._control_rows()
            self._build()
        self._send(events)
        self._show_voices(())
        self._apply_clock()
        self.refresh_patterns()
        self.publish()

    def on_view(self, view) -> None:
        """Outside Custom view the pads play nothing here: every note the performer started ends."""
        if view is not UnitView.CUSTOM:
            self.silence()

    def on_release(self) -> None:
        self.silence()

    def end_held(self, notes) -> None:
        """A window shift ended these held notes (the host ended their sound): they count as released, and the
        unit's later release of each is taken and sends nothing."""
        notes = {int(n) for n in notes}
        shown = None
        with self._lock:
            core = self._core
            if core is None or not notes:
                return
            now = self._now()
            if self._addressing() == STRINGS:
                for lane, stack in list(self._physical.items()):
                    for note, _ in [v for v in stack if v[0] in notes and (lane, v[0]) not in self._uncounted]:
                        self._ended[(lane, note)] += 1
                        self._unpress(lane, note)
                        if self._is_manual(lane) and core.holding(lane, note):
                            core.release(lane, note, now)
                shown = self._sync(now)
            else:
                for lane, note in core.pressed():
                    if note in notes:
                        self._ended[(lane, note)] += 1
                core.end_held(notes, now)
            events = core.advance_to(now)
        self._send(events)
        if shown is not None:
            self._show_voices(shown)
        self._wake()

    def silence(self) -> None:
        with self._lock:
            events = self._silenced()
            self._ended.clear()
        self._send(events)
        self._show_voices(())
        self._publish_if_moved()

    def take_played(self, played) -> str | None:
        """The host's take_played: a Custom-port note or aftertouch while the performer plays, else None."""
        if played.role is not UnitPortRole.CUSTOM:
            return None
        message = played.message
        if not isinstance(message, (NoteOn, NoteOff, PolyAftertouch)):
            return None
        channel, note = int(message.channel), int(message.note)
        on = isinstance(message, NoteOn) and message.velocity > 0
        shifted = on and self._link.shift_held() and len(self._strings) >= 7
        transposition = self._window(self._layout_id) if shifted and self._layout_id else None
        command = None
        with self._lock:
            if channel == CONTROL_CHANNEL and self._rows and self._core is not None:
                if not on:
                    return TAKEN_CONTROL                # a control pad's release or aftertouch: nothing to do
                command = control_of(note)
                if command is None:
                    return TAKEN_CONTROL
            elif (channel, note) in self._commands:
                if not on and not isinstance(message, PolyAftertouch):
                    self._commands.discard((channel, note))
                return TAKEN_CONTROL
            elif shifted and self._engaged() and self._addressing() == STRINGS:
                command = self._shift_command(channel, note, transposition or 0)
                if command is not None:
                    self._commands.add((channel, note))
            if command is None:
                if not self._engaged():
                    return None
                reason, events, shown = self._played(message, channel, note, on)
                said, self._said = self._said, None
        if command is not None:
            self._command(*command)
            return TAKEN_CONTROL
        if reason is None:
            return None
        self._send(events)
        if shown is not None:
            self._show_voices(shown)
        if said:
            self._show(said)
        self._wake()
        self._publish_if_moved()
        return reason

    def _played(self, message, channel: int, note: int, on: bool):
        """A note played (under the lock): (the reason it is taken, or None for the router; the events; the voicing
        to show, or None)."""
        core, now = self._core, self._now()
        lane = self._lane_of(channel)
        if self._addressing() != STRINGS:
            if on:
                core.press(lane, note, int(message.velocity), now)
            elif not core.holding(lane, note):
                if isinstance(message, PolyAftertouch) or not self._ended[(lane, note)]:
                    return None, [], None              # pressed before the performer played: the router has it
                self._ended[(lane, note)] -= 1
                return TAKEN, [], None
            elif isinstance(message, PolyAftertouch):
                core.aftertouch(lane, note, int(message.pressure), now)
            else:
                core.release(lane, note, now)
            return TAKEN, core.advance_to(now), None
        held = any(n == note for n, _ in self._physical.get(lane, ()))
        manual = self._is_manual(lane)
        reason = TAKEN_VOICED if (lane, note) in self._uncounted else TAKEN
        if on:
            alone = not self._pattern_physical()
            velocity = max(1, min(127, int(message.velocity)))
            stack = [v for v in self._physical.get(lane, []) if v[0] != note]
            self._physical[lane] = stack + [(note, velocity)]
            if manual:
                core.press(lane, note, velocity, now)  # the player's string: through at once, as played
                return TAKEN, core.advance_to(now), None
            if self._type is not None and alone:
                self._uncounted.add((lane, note))      # a root: the harmony views show its voicing instead
                reason = TAKEN_VOICED
        elif not held:
            if isinstance(message, PolyAftertouch) or not self._ended[(lane, note)]:
                return None, [], None
            self._ended[(lane, note)] -= 1
            return TAKEN, [], None
        elif isinstance(message, PolyAftertouch):
            if not manual:
                return reason, [], None                # pattern notes take none
            core.aftertouch(lane, note, int(message.pressure), now)
            return reason, core.advance_to(now), None
        else:
            self._unpress(lane, note)
            self._uncounted.discard((lane, note))
            if manual:
                if core.holding(lane, note):           # not when it was pressed on a pattern string: its sound
                    core.release(lane, note, now)      # ended when the string became manual; nothing more goes
        shown = self._sync(now)
        return reason, core.advance_to(now), shown

    def _pattern_physical(self) -> list[tuple[int, int, int]]:
        """(lane, note, velocity) the player holds on the pattern strings (the manual ones are the player's)."""
        return [(lane, n, v) for lane, stack in self._physical.items() if not self._is_manual(lane) for n, v in stack]

    def _set_pattern(self, pattern, now: float):
        """The engine plays `pattern` from its next step, and what the player holds is partitioned again between the
        pattern strings and the manual ones (under the lock); answers the voicing to show (None: voices addressing).

        A string that became manual: the pattern's note there ended (the engine's set_pattern); the player's held note
        stays held in the engine, silent (its attack was earlier: it sounds again when plucked again), and its release
        sends nothing; a voicing's note there the player does not hold is let go. A string that became a pattern
        string: its manual note ended (the engine's); the engine already holds what the player holds there (manual
        presses go to it as played), which the pattern plays from its next hit: it becomes the diff's own."""
        core = self._core
        before = core.pattern.manual if core.pattern is not None else frozenset()
        core.set_pattern(pattern, now)
        if self._addressing() != STRINGS:
            return None
        after = pattern.manual
        for lane in [lane for lane in self._fed if lane in after]:
            for note, _ in self._fed.pop(lane):
                if not any(n == note for n, _ in self._physical.get(lane, ())):
                    core.release(lane, note, now)
        for lane in before - after:
            if self._physical.get(lane):
                self._fed[lane] = list(self._physical[lane])
        return self._sync(now)

    def _pattern_named(self, name, valid: bool = True) -> str:
        """The id of the pattern a name names (under the lock); DomainInvariantError when none (or, `valid`, when its
        file is invalid and no edit of it is kept)."""
        found = self._patterns.find(str(name))
        if found is None:
            names = [row["id"] for row in self._patterns.listing()]
            raise DomainInvariantError("pattern", f'no pattern "{name}"',
                                       "available: " + (", ".join(names) or "none (add one to patterns/)"))
        pattern_id, result = found
        if valid and not result.valid and pattern_id not in self._edits:
            raise DomainInvariantError("pattern", f"{result.file} is invalid", result.errors[0].message())
        return pattern_id

    def _play_kept(self, pattern_id: str | None, now: float):
        """Pattern `pattern_id` plays (under the lock): its kept edit if it has one, else its file (a new pattern is
        only an edit). Answers the Pattern; the voicing to show is left in _shown_after."""
        if pattern_id in self._edits:
            playing = self._edits[pattern_id][0]
        else:
            found = self._patterns.get(pattern_id)
            if found is None:
                raise DomainInvariantError("pattern", f'pattern "{pattern_id}" is not valid now', "choose another")
            playing = found[1]
        self._pattern_id = pattern_id
        self._shown_after = self._set_pattern(playing, now) if self._core is not None else None
        self._revision += 1
        return playing

    def _hash_of(self, pattern_id: str | None) -> str | None:
        read = self._patterns.read(pattern_id) if pattern_id else None
        return read[1] if read else None

    def _unpress(self, lane: int, note: int) -> None:
        stack = [v for v in self._physical.get(lane, []) if v[0] != note]
        if stack:
            self._physical[lane] = stack
        else:
            self._physical.pop(lane, None)

    def _sync(self, now: float) -> tuple:
        """What the engine holds on the pattern strings made what it should be (under the lock): the voicing of the
        one note held when a chord type is chosen, else what the player holds. Releases first, then the presses
        together; answers the voicing to show ((channel, note) of the notes the harmony views do not count)."""
        core = self._core
        physical = self._pattern_physical()
        voicing = kind = None
        silent = False                                         # a root out of key: strict, nothing plays
        if self._type is not None and len(physical) == 1:
            lane, root, velocity = physical[0]
            kind = self._chord_kind(root)
            silent = kind is None
            try:
                voicing = build_voicing(self._opens(), root, lane, kind, self._frets) if kind is not None else None
            except (VoicingError, ValueError):
                voicing = None
        if silent:
            desired, muted = {}, []
        elif voicing is not None:
            desired = {s: [(n, velocity)] for s, n in voicing.sounding.items() if not self._is_manual(s)}
            muted = [s for s in voicing.muted if not self._is_manual(s)]
            key = (voicing.root, voicing.root_string, voicing.chord)
            before = self._voicing
            if before is None or (before.root, before.root_string, before.chord) != key:
                self._said = kind.symbol(ascii_name(voicing.root))
        else:
            desired = {lane: list(stack) for lane, stack in self._physical.items() if stack and not self._is_manual(lane)}
            muted = []
        self._voicing, self._kind = voicing, kind if voicing is not None else None
        for lane, stack in list(self._fed.items()):
            keep = {n for n, _ in desired.get(lane, ())}
            for n, _ in stack:
                if n not in keep:
                    core.release(lane, n, now)
        presses = [(lane, n, v) for lane, stack in desired.items() for n, v in stack
                   if n not in {m for m, _ in self._fed.get(lane, ())}]
        core.set_muted(muted, now)
        if presses:
            core.press_chord(presses, now)
        self._fed = desired
        counted = {(lane, n) for lane, n, _ in physical if (lane, n) not in self._uncounted}
        channels = {number: channel for number, _, channel in self._strings}
        return tuple(sorted((channels.get(lane, lane), stack[-1][0]) for lane, stack in desired.items()
                            if (lane, stack[-1][0]) not in counted))

    # === chord types and pattern slots (Phase 2) ===========================================================
    def _shift_command(self, channel: int, note: int, transposition: int):
        """Shift + a pad on 7 or 8 strings: ('types' | 'slots', column), or None (not a pad of the window)."""
        lane = self._lane_of(channel)
        opens = self._opens()
        if lane not in opens:
            return None
        column = note - opens[lane] - transposition
        if not 0 <= column < 8:
            return None
        if len(self._strings) >= 8 and lane == 1:                  # 8 strings: string 1 is the top row
            return SLOTS, column
        return TYPES, column

    def _command(self, kind: str, column: int) -> None:
        """A control pad (or Shift + pad): a chord type chosen or let go, a pattern slot chosen."""
        try:
            if kind == TYPES:
                with self._lock:
                    name = self._types[column] if column < len(self._types) else None
                    current = self._type
                if name is not None:
                    self.select_type(None if name == current else name)
            else:
                with self._lock:
                    filled = column < len(self._slots) and self._slots[column] is not None
                if filled:
                    self.select_slot(column + 1)
        except (DomainInvariantError, PerformerUnavailable, PatternRefused) as error:
            log.info("lab: performer control %s %d: %s", kind, column + 1, error)
            if isinstance(error, DomainInvariantError) and error.field == "chord_type":
                self._show("No key" if error.problem == "no key" else "No 7-note key")   # a key type without one

    def select_type(self, name) -> dict:
        """The chord type chosen (a name from CHORD_TYPES, or None: fretted again); the page, the API, the pads."""
        events, shown = [], None
        with self._lock:
            if self._layout_id is None:
                raise PerformerUnavailable(NOT_ACTIVE)
            if name is not None:
                kind = chord_type(name)
                own = key_type(name) if kind is None else None
                if kind is None and own is None:
                    raise DomainInvariantError("chord_type", f"no chord type '{name}'",
                                               "chord types: " + ", ".join([*KEY_TYPES, *CHORD_TYPES]))
                if self._addressing() != STRINGS:
                    raise DomainInvariantError("chord_type", "chord types are voiced on strings",
                                               "activate a guitar layout (a lane per string)")
                if own is not None:
                    self._check_key()
                name = kind.name if kind is not None else own
            self._type = name
            if self._core is not None and self._engaged():
                now = self._now()
                shown = self._sync(now)
                events = self._core.advance_to(now)
            said, self._said = self._said, None
            if name is None:
                flash, message = "Type off", "chord type off: what you fret plays"
            else:
                flash = said or f"Type {name}"
                message = (f"chord type {name}: one note held is its root" if name not in KEY_TYPES else
                           f"chord type {name}: one note held in {self._key['tonic']} {_scale_word(self._key)} is the root "
                           f"of the key's own {'seventh' if name == KEY_7 else 'triad'}")
        self._send(events)
        if shown is not None:
            self._show_voices(shown)
        self._wake()
        self._repaint()
        self._show(flash)
        self.publish()
        return {**self.state(), "message": message}

    def _chord_kind(self, root: int):
        """The ChordType a root is voiced as (under the lock): the chosen type's, or for 'key' and 'key 7' the key's
        own chord from that root (None: out of key, or no key: nothing plays)."""
        if self._type not in KEY_TYPES:
            return chord_type(self._type)
        if self._key is None:
            return None
        return diatonic_chord(self._key["pcs"], root, self._type == KEY_7)

    def _check_key(self) -> None:
        """The key's chords need a key of seven notes (under the lock); DomainInvariantError otherwise."""
        if self._key is None:
            raise DomainInvariantError("chord_type", "no key",
                                       "choose a Key on the page, or a layout with 'scheme: scale' (its scale and root)")
        if len(self._key["pcs"]) != 7:
            raise DomainInvariantError("chord_type", f"{self._key['tonic']} {_scale_word(self._key)} has "
                                       f"{len(self._key['pcs'])} notes",
                                       "the key's chords stack thirds in a seven-note scale: choose one (major, "
                                       "dorian, harmonic minor …)")

    def set_key(self, layout_id, overlay) -> None:
        """The key of the layout playing (the session's, at every change): a ScaleOverlay (its root and pitch
        classes) or None. A root held under a key type is voiced again in the new key; a key taken away (or one the
        key's chords cannot use) lets go of a key type (fretted again)."""
        key = None
        if overlay is not None:
            key = {"root": int(overlay.root) % 12, "pcs": tuple(sorted(overlay.pitch_classes)),
                   "scale": overlay.key, "name": overlay.name,
                   "tonic": dict(overlay.names).get(overlay.root) or pc_name(overlay.root)}
        events, shown, flash = [], None, None
        with self._lock:
            if layout_id != self._layout_id or key == self._key:
                return
            self._key = key
            if self._type in KEY_TYPES and (key is None or len(key["pcs"]) != 7):
                self._type, flash = None, "Type off"
            if self._core is not None and self._engaged() and self._addressing() == STRINGS:
                now = self._now()
                shown = self._sync(now)
                events = self._core.advance_to(now)
            said, self._said = self._said, None
        self._send(events)
        if shown is not None:
            self._show_voices(shown)
        self._wake()
        if flash:
            self._repaint()
        if said or flash:
            self._show(said or flash)
        self.publish()

    def _key_json(self) -> dict | None:
        key = self._key
        if key is None:
            return None
        return {"tonic": ascii_name(key["root"]) if "♯" in key["tonic"] or "♭" in key["tonic"] else key["tonic"],
                "scale": key["scale"], "name": key["name"], "pcs": list(key["pcs"]), "chords": len(key["pcs"]) == 7}

    def select_slot(self, slot: int) -> dict:
        """Pattern slot `slot` (1–8) plays: its pattern, as change(pattern=…) does, its pad lit."""
        with self._lock:
            if self._layout_id is None:
                raise PerformerUnavailable(NOT_ACTIVE)
            slots = self._slots
        listed = ", ".join(f"{k + 1} {name}" for k, name in enumerate(slots) if name) or "none (the block's slots:)"
        if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= max(len(slots), 1) \
                or slot > len(slots) or slots[slot - 1] is None:
            raise DomainInvariantError("slot", f"slot {slot} holds no pattern", f"slots: {listed}")
        return self.change(pattern=slots[slot - 1])

    def control_pads(self, definition) -> dict:
        """The control pads of a generated layout (SessionService's render): {pad index: (PadAssignment, label)};
        the active layout's with the chosen type and slot lit."""
        settings = getattr(definition, "performer", None)
        if settings is None or settings.addressing == VOICES:
            return {}
        try:
            neck = definition.neck(self._generators())
        except Exception:   # a nicety for a generator without a neck
            neck = None
        if neck is None or not control_rows(len(neck.strings)):
            return {}
        with self._lock:
            active = settings == self._settings
            chosen, slot = (self._type, self._slot) if active else (None, None)
            names = {row["id"]: row["name"] for row in self._listing if row.get("valid")}
        pads = control_pads(len(neck.strings), settings.chords, settings.slots, chosen, slot)
        labels = {}
        for index, pad in pads.items():
            kind, column = control_of(pad.note)
            if kind == TYPES:
                labels[index] = settings.chords[column]
            else:
                wanted = settings.slots[column]
                found = find_pattern(wanted, names)
                labels[index] = names.get(found, wanted) if found else wanted
        return {index: (pad, labels[index]) for index, pad in pads.items()}

    def _control_rows(self) -> dict:
        if self._settings is None or self._addressing() != STRINGS or not self._strings:
            return {}
        return control_rows(len(self._strings))

    def _chord_root(self, notes) -> int | None:
        """The root of what is held, for the engine's chord-aware lanes: the voicing's, else the harmony core's."""
        if self._voicing is not None:
            return self._voicing.root % 12
        matches = find_chord_matches(notes)
        return matches[0].root if matches else None

    def _opens(self) -> dict[int, int]:
        return {number: open_note for number, open_note, _ in self._strings}

    def _is_manual(self, lane: int) -> bool:
        core = self._core
        return core is not None and core.pattern is not None and lane in core.pattern.manual

    # === the unit's Play and Stop (the layout's performer block binds them) ================================
    def play_button(self) -> None:
        """Play: the latch on or off."""
        if not self._engaged():
            self._show("Performer off")
            return
        self.change(latch=not self._latch)
        self._show("Latch on" if self._latch else "Latch off")

    def stop_button(self) -> None:
        """Stop: the pattern stops now, its notes off (and the latched notes go)."""
        if not self._engaged():
            self._show("Performer off")
            return
        self.stop_pattern()
        self._show("Stopped")

    # === the page, the API and the CLI =====================================================================
    def stop_pattern(self) -> dict:
        with self._lock:
            if self._core is None:
                raise PerformerUnavailable(NOT_ACTIVE)
            self._core.stop(self._now())
            events = self._core.advance_to(self._now())
        self._send(events)
        self._wake()
        self.publish()
        return {**self.state(), "message": "pattern stopped"}

    def change(self, *, enabled=None, pattern=None, latch=None, bpm=None, clock=None, play=None,
               play_given: bool = False, pattern_data=None, edits=None, revert=None, new_pattern=False) -> dict:
        """The session's performer settings, each one given; the file is not changed. `play_given` with play None
        goes back to the pattern's own play mode. A pattern chosen plays its kept edit if it has one.

        The editor's edits: `pattern_data` is the pattern `edits` (its id; None: a new pattern, never saved) as
        edited; it plays at once from the next step and is kept, unsaved, for the session (equal to its file, it is
        the file again). An edit of a pattern other than the one playing is refused (a stale page). `revert` (an id)
        drops that pattern's edit (its file plays, if it played); `new_pattern` plays the session's new pattern
        again. Raises DomainInvariantError (PatternRefused for pattern data) for a value it refuses."""
        said = []
        repaint = False
        shown = None
        with self._lock:
            if self._layout_id is None:
                raise PerformerUnavailable(NOT_ACTIVE)
            now = self._now()
            events = []
            chosen = None                                       # the pattern id chosen to play, if one is
            if revert is not None:
                pattern_id = self._pattern_named(revert, valid=False)
                dropped = self._edits.pop(pattern_id, None)
                if self._pattern_id == pattern_id:
                    chosen = pattern_id
                said.append(f"{pattern_id}: the unsaved edit dropped" if dropped else f"{pattern_id} has no unsaved edit")
            if new_pattern:
                if None not in self._edits:
                    raise DomainInvariantError("new_pattern", "no new pattern is kept",
                                               "start one with New in the pattern editor")
                chosen = None
                self._play_kept(None, now)
                said.append(f"pattern {self._edits[None][0].name} (new, not saved)")
            if pattern is not None:
                chosen = self._pattern_named(pattern)
            if chosen is not None:
                playing = self._play_kept(chosen, now)
                if pattern is not None:
                    said.append(f"pattern {playing.name}" + (" (edited, not saved)" if chosen in self._edits else ""))
            if chosen is not None or new_pattern:
                shown = self._shown_after
            if pattern_data is not None:
                if edits is not None and edits != self._pattern_id:
                    raise PatternRefused(409, f'this edit is of "{edits}", but '
                                         + (f'"{self._pattern_id}"' if self._pattern_id else "a new pattern")
                                         + " plays now", "the editor shows what plays now: make the edit there again",
                                         code="stale")
                edited, _ = self._patterns.check_data(pattern_data)
                found = self._patterns.get(edits) if edits is not None else None
                if found is not None and found[1] == edited:
                    self._edits.pop(edits, None)               # edited back to its file: the file again
                    said.append(f"playing {edited.name} as its file")
                else:
                    base = self._edits[edits][1] if edits in self._edits else self._hash_of(edits)
                    self._edits[edits] = (edited, base)
                    said.append(f"playing {edited.name} as edited (not saved)")
                self._pattern_id = edits
                if self._core is not None:
                    shown = self._set_pattern(edited, now)
                self._revision += 1
            if chosen is not None or new_pattern or pattern_data is not None:
                slot = self._slot_of(self._pattern_id)
                repaint = slot != self._slot
                self._slot = slot
            if play is not None or play_given:
                if play is not None and play not in PLAY_MODES:
                    raise DomainInvariantError("play", f"'{play}' is not all or pressed",
                                               "all: an unpressed string rings open; pressed: only pressed strings play")
                self._play = play
                if self._core is not None:
                    self._core.set_play(play, now)
                said.append(f"play {self._play_mode()}")
            if bpm is not None:
                value = _number(bpm)
                if value is None or not MIN_BPM <= value <= MAX_BPM:
                    raise DomainInvariantError("bpm", f"'{bpm}' is not a tempo",
                                               f"write a BPM {MIN_BPM:g}–{MAX_BPM:g} (quarter notes a minute)")
                self._bpm, self._clock_port = value, None
                if self._core is not None:
                    self._core.set_tempo(value, now)
                said.append(f"tempo {value:g} BPM")
            if clock is not None:
                port = " ".join(str(clock).split())
                if not port:
                    raise DomainInvariantError("clock", "the clock input is empty",
                                               "name the MIDI input that sends the clock, as 'apc64 ports' lists it, "
                                               "or 'auto': whichever input sends one")
                if port.casefold() == AUTO:
                    port = AUTO
                self._clock_port = port
                said.append("tempo from the MIDI clock of the first input that sends one" if port == AUTO
                            else f"tempo from the MIDI clock of {port}")
            if latch is not None:
                self._latch = bool(latch)
                if self._core is not None:
                    self._core.set_latch(self._latch, now)
                said.append("latch " + ("on" if self._latch else "off"))
            if enabled is not None:
                if not enabled and self._core is not None:
                    events += self._silenced()
                self._enabled = bool(enabled)
                said.append("performer " + ("on" if self._enabled else "off"))
            if self._core is not None:
                events += self._core.advance_to(now)
        self._send(events)
        if shown is not None:
            self._show_voices(shown)
        if bpm is not None or clock is not None:
            self._apply_clock()
        self._wake()
        if repaint:
            self._repaint()
        if pattern is not None or new_pattern or enabled is not None:
            self._show(self._pattern_name() if self._enabled else "Performer off")
        if enabled is False:
            self._show_voices(())
        self.refresh_patterns()
        self.publish()
        return {**self.state(), "message": "; ".join(said) if said else "nothing changed"}

    # --- the pattern files (the editor, the API, the CLI) ---------------------------------------------------
    def save_pattern(self, pattern_id: str, *, text=None, data=None, base=None, create=False, edits=NO_EDIT) -> dict:
        """Write a pattern (PatternLibrary.save); the one playing plays the file from its next step. `edits`: the
        editor saves the kept edit of that pattern (None: the new one), which is dropped, and when it was playing the
        written file plays instead (Save, or Save as under another name). A write from elsewhere (the CLI) keeps the
        edit, whose base hash then refuses the editor's later Save as stale. PatternRefused when refused."""
        answer = self._patterns.save(pattern_id, text=text, data=data, base=base, create=create)
        self._after_write(answer["id"], edits)
        return answer

    def restore_pattern(self, pattern_id: str, version: str) -> dict:
        answer = self._patterns.restore(pattern_id, version)
        self._after_write(answer["id"])
        return answer

    def delete_pattern(self, pattern_id: str, base=None) -> dict:
        """Delete a pattern file (PatternLibrary.delete) and its kept edit; a performer playing it goes on with the
        first valid one."""
        answer = self._patterns.delete(pattern_id, base)
        events, shown = [], None
        with self._lock:
            if self._pattern_id == answer["id"]:
                rows = [row for row in self._patterns.listing() if row["valid"]]
                found = self._patterns.get(rows[0]["id"]) if rows else None
                self._pattern_id = found[0] if found else None
                if self._core is not None:
                    now = self._now()
                    if found is not None:
                        self._play_kept(found[0], now)
                        shown = self._shown_after
                    else:
                        self._core.stop(now)
                    events = self._core.advance_to(now)
                self._slot = self._slot_of(self._pattern_id)
            if self._edits.pop(answer["id"], None) is not None:
                self._revision += 1
        self._send(events)
        if shown is not None:
            self._show_voices(shown)
        self.refresh_patterns()
        self.publish()
        return answer

    def _after_write(self, pattern_id: str, edits=NO_EDIT) -> None:
        found = self._patterns.get(pattern_id)
        events, shown = [], None
        with self._lock:
            core = self._core
            if edits is not NO_EDIT and edits in self._edits:
                del self._edits[edits]                                     # the edit, saved
                if self._pattern_id == edits:
                    self._pattern_id = pattern_id                          # … and its file plays now
                self._revision += 1
            if found is not None and core is not None and self._pattern_id == pattern_id \
                    and pattern_id not in self._edits and core.pattern != found[1]:
                shown = self._set_pattern(found[1], self._now())           # its file changed: from the next step
                events = core.advance_to(self._now())
            self._slot = self._slot_of(self._pattern_id)
            self._shown_pattern = None
        self._send(events)
        if shown is not None:
            self._show_voices(shown)
        self._wake()
        self.refresh_patterns()
        self.publish()

    def refresh_patterns(self) -> None:
        """The pattern files read again (they may have changed on disk)."""
        listing = self._patterns.listing()
        with self._lock:
            self._listing = listing

    def state(self, fresh: bool = False) -> dict:
        if fresh:
            self.refresh_patterns()
        with self._lock:
            core = self._core
            pattern = core.pattern if core is not None else None
            run = core.state(self._now()) if core is not None else None
            addressing = self._addressing() if self._layout_id else None
            lanes = len(self._strings) if addressing == STRINGS else None
            edited = self._pattern_id in self._edits
            base = self._edits[self._pattern_id][1] if edited else None
            if pattern is None:
                shown = None
            elif self._shown_pattern is not None and self._shown_pattern[:4] == (pattern, lanes, self._pattern_id,
                                                                                  (edited, base)):
                shown = self._shown_pattern[4]
            else:
                if not edited:
                    base = self._hash_of(self._pattern_id)
                shown = {**pattern_json(self._pattern_id, pattern, lanes), "hash": base}
                self._shown_pattern = (pattern, lanes, self._pattern_id, (edited, shown["hash"] if edited else None),
                                       shown)
            if shown is not None:
                shown = {**shown, "edited": edited, "new": edited and self._pattern_id is None}
            return {
                "kind": KIND, "available": self._layout_id is not None, "layout": self._layout_id,
                "name": self._layout_name, "from_layout": self._settings is not None, "enabled": self._enabled,
                "addressing": addressing, "lanes": self._lane_labels(pattern),
                "pattern": shown, "patterns": [{**row, "edited": row["id"] in self._edits} for row in self._listing],
                "edits": [{"id": key, "name": edit[0].name, "new": key is None}
                          for key, edit in sorted(self._edits.items(), key=lambda kv: (kv[0] is None, kv[0] or ""))],
                "pattern_revision": self._revision, "latch": self._latch,
                "play": self._play_mode(pattern),
                "play_override": self._play,
                "tempo": self._tempo_json(core),
                "running": bool(run and run.running), "step": run.step + 1 if run and run.step is not None else None,
                "length": pattern.length if pattern is not None else None,
                "controls": (CONTROLS if self._settings is not None else NO_CONTROLS) if self._layout_id else None,
                "chords": {"types": list(self._types), "selected": self._type,
                           "available": addressing == STRINGS},
                "slots": [self._slot_json(k, name) for k, name in enumerate(self._slots)],
                "slot": self._slot + 1 if self._slot is not None else None,
                "pads": ROWS_TEXT.get(tuple(self._rows)) if self._settings is not None and addressing == STRINGS
                else None,
                "voicing": self._voicing_json(),
                "key": self._key_json(),
                "timing": self._timer.timing() if self._timer is not None else None,
                "message": self._message if self._layout_id else NOT_ACTIVE,
            }

    def _slot_json(self, k: int, name: str | None) -> dict | None:
        if name is None:
            return None
        names = {row["id"]: row["name"] for row in self._listing if row.get("valid")}
        found = find_pattern(name, names)
        return {"slot": k + 1, "pattern": name, "id": found, "name": names.get(found, name), "valid": found is not None,
                "edited": found is not None and found in self._edits}

    def _slot_of(self, pattern_id: str | None) -> int | None:
        names = {row["id"]: row["name"] for row in self._listing if row.get("valid")}
        for k, name in enumerate(self._slots):
            if name and pattern_id and find_pattern(name, names or {pattern_id: None}) == pattern_id:
                return k
        return None

    def _voicing_json(self) -> dict | None:
        voicing = self._voicing
        if voicing is None:
            return None
        return {"root": pc_name(voicing.root), "string": voicing.root_string, "chord": voicing.chord,
                "symbol": (self._kind or CHORD_TYPES[voicing.chord]).symbol(pc_name(voicing.root)),
                "shape": voicing.shape(),
                "notes": [{"string": s, "note": n} for s, n in voicing.notes if n is not None]}

    def publish(self) -> None:
        try:
            state = self.state()
            with self._lock:
                self._shown = (state["running"], state["step"])
            self._publisher.publish(state)
        except Exception:
            log.exception("lab: publishing the performer state failed")

    # === internals =========================================================================================
    def _silenced(self) -> list:
        """Every note the engine started ends now (under the lock): the events to send."""
        self._physical, self._fed, self._uncounted, self._voicing, self._kind = {}, {}, set(), None, None
        if self._core is None:
            return []
        now = self._now()
        self._core.silence(now)
        self._core.set_muted((), now)
        return self._core.advance_to(now)

    def _engaged(self) -> bool:
        return self._core is not None and self._enabled and self._core.pattern is not None

    def _fresh(self, settings: PerformerSettings | None) -> None:
        """A new layout (or a changed block): the block's settings, or off with the defaults."""
        self._settings = settings
        self._enabled = settings is not None
        self._latch = settings.latch if settings else False
        self._play = settings.play if settings else None
        self._bpm = settings.bpm if settings else DEFAULT_BPM
        self._clock_port = settings.clock if settings else None
        self._ended.clear()
        self._message = None
        self._types = settings.chords if settings else DEFAULT_TYPES
        self._slots = settings.slots if settings else ()
        self._type = None
        wanted = settings.pattern if settings else None
        found = self._patterns.get(wanted) if wanted else None
        if found is None and wanted:
            self._message = f'pattern "{wanted}" is not available now; choose another'
        if found is None:
            rows = [row for row in self._patterns.listing() if row["valid"]]
            found = self._patterns.get(rows[0]["id"]) if rows else None
        self._pattern_id = found[0] if found else None
        self._listing = self._patterns.listing()
        self._slot = self._slot_of(self._pattern_id)

    def _build(self) -> None:
        found = self._patterns.get(self._pattern_id) if self._pattern_id else None
        if self._pattern_id in self._edits:
            found = (self._pattern_id, self._edits[self._pattern_id][0])     # a kept edit plays, as when chosen
        opens = {number: open_note for number, open_note, _ in self._strings}
        self._revision += 1
        self._core = Performer(found[1] if found else None, addressing=self._addressing(), opens=opens,
                               bpm=self._bpm, latch=self._latch, play=self._play, chord_root=self._chord_root)
        if found is None:
            self._message = self._message or "no valid pattern in patterns/ (docs/performer-format.md)"

    def _unload(self) -> None:
        with self._lock:
            events = self._silenced()
            self._core = None
            self._layout_id = self._layout_name = self._settings = None
            self._strings, self._channel_lane = [], {}
            self._enabled = False
            self._ended.clear()
            self._rows, self._type, self._slot, self._slots = {}, None, None, ()
        self._send(events)
        self._show_voices(())
        self._unfollow()
        self.publish()

    def _addressing(self) -> str:
        wanted = self._settings.addressing if self._settings else None
        if wanted == VOICES or not self._strings:
            return VOICES
        return STRINGS

    def _frets_of(self, definition: LabDefinition) -> int:
        try:
            neck = definition.neck(self._generators())
        except Exception:   # a nicety: without a neck, the default length
            neck = None
        return neck.frets if neck is not None else 24

    def _strings_of(self, definition: LabDefinition) -> list[tuple[int, int, int]]:
        try:
            neck = definition.neck(self._generators())
        except Exception:   # a nicety: without a neck the lanes are voices
            neck = None
        return [(s.number, s.open, s.channel) for s in neck.strings] if neck is not None else []

    def _lane_of(self, channel: int) -> int:
        return self._channel_lane.get(channel, channel) if self._addressing() == STRINGS else channel

    def _lane_labels(self, pattern) -> list[dict]:
        if self._addressing() == STRINGS and self._strings:
            labels = [{"lane": number, "label": f"{number} {pc_name(open_note)}", "open": open_note}
                      for number, open_note, _ in sorted(self._strings)]
        else:
            lanes = sorted({lane for lane, _ in pattern.lanes if isinstance(lane, int)}) if pattern is not None else []
            labels = [{"lane": lane, "label": f"voice {lane}", "open": None} for lane in lanes]
        return labels + [{"lane": ROOT_LANE, "label": "R root", "open": None},
                         {"lane": ALT_LANE, "label": "A alt bass", "open": None}]

    def _play_mode(self, pattern=None) -> str | None:
        if self._play is not None:
            return self._play
        if pattern is None and self._core is not None:
            pattern = self._core.pattern
        return pattern.play if pattern is not None else None

    def _pattern_name(self) -> str:
        core = self._core
        return core.pattern.name if core is not None and core.pattern is not None else "No pattern"

    def _send(self, events) -> None:
        messages = []
        for event in events:
            if event.kind == "on":
                messages.append(NoteOn(event.lane, event.note, event.value))
            elif event.kind == "off":
                messages.append(NoteOff(event.lane, event.note))
            elif event.kind == "aftertouch":
                messages.append(PolyAftertouch(event.lane, event.note, event.value))
        if messages:
            try:
                self._link.perform(messages)
            except Exception:
                log.exception("lab: the performer's notes could not be handed to the host")

    def _publish_if_moved(self) -> None:
        with self._lock:
            core = self._core
            run = core.state(self._now()) if core is not None else None
            now = (bool(run and run.running), run.step + 1 if run and run.step is not None else None)
            moved = now != self._shown
        if moved:
            self.publish()

    def _show(self, text: str) -> None:
        if self._flash is not None:
            try:
                self._flash(str(text)[:14])
            except Exception:
                log.exception("lab: the performer's OLED flash failed")

    # --- the MIDI clock --------------------------------------------------------------------------------
    def _tempo_json(self, core) -> dict:
        """The tempo (under the lock): the BPM, or the clock followed with what it measures now; `stopped` once the
        clock followed went quiet (the tempo it gave is kept), `heard` the inputs a clock came from lately."""
        now = self._now()
        follower = self._followers.get(self._following) if self._following else None
        measured = follower.bpm(now) if follower is not None else None
        return {"source": "clock" if self._clock_port else "bpm", "bpm": core.bpm if core else self._bpm,
                "clock": self._clock_port, "measured": measured, "following": self._following,
                "stopped": bool(self._clock_port and measured is None and self._measured is not None),
                "heard": sorted(port for port, at in self._heard.items() if now - at <= HEARD)}

    def _clock_inputs(self) -> list[str]:
        """Every input a clock could come from (the APC64's are never listed): for the AUTO choice."""
        listing = getattr(self._link.inputs, "list", None)
        if not callable(listing):
            return []
        try:
            ports = listing()
        except Exception:
            log.exception("lab: listing the MIDI inputs for the clock failed")
            return []
        return sorted({str(p.name) for p in ports if getattr(p, "present", True)
                       and str(getattr(p, "direction", "both")) in ("input", "both") and "apc64" not in p.name.casefold()})

    def _apply_clock(self) -> None:
        """Listen to the chosen clock input, or to every input for AUTO (and to none for a BPM); a new choice starts
        the measurement afresh."""
        with self._lock:
            wanted = self._clock_port if self._layout_id else None
            changed = wanted != self._listening_for
        if changed:
            self._unfollow()
        if wanted is None:
            return
        inputs = self._link.inputs
        listen = getattr(inputs, "listen_realtime", None)
        if not callable(listen):
            with self._lock:
                self._message = "MIDI clock input is not available here"
            return
        if wanted == AUTO and not self._presence and callable(getattr(inputs, "subscribe_presence", None)):
            self._presence = True
            inputs.subscribe_presence(lambda name, present: self._apply_clock())
        ports = self._clock_inputs() if wanted == AUTO else [wanted]
        with self._lock:
            self._listening_for = wanted
            if wanted != AUTO:
                self._following = wanted
            gone = [self._clock_listeners.pop(port) for port in list(self._clock_listeners) if port not in ports]
            new = [port for port in ports if port not in self._clock_listeners]
        for listener in gone:
            _cancel(listener)
        for port in new:
            try:
                listener = listen(port, lambda status, at, port=port: self._on_clock(port, status, at))
            except Exception:
                log.exception("lab: listening to the clock of %s failed", port)
                continue
            with self._lock:
                if self._listening_for == wanted and port not in self._clock_listeners:
                    self._clock_listeners[port] = listener
                    continue
            _cancel(listener)

    def _unfollow(self) -> None:
        with self._lock:
            listeners, self._clock_listeners = list(self._clock_listeners.values()), {}
            self._listening_for = self._following = self._measured = None
            self._followers, self._heard, self._alive = {}, {}, False
        for listener in listeners:
            _cancel(listener)

    def _on_clock(self, port: str, status: int, at: float) -> None:
        """A clock byte from the sequencer's reader thread. With AUTO the first input that sends a clock is followed
        (another once it went quiet); the tempo of the one followed (ClockFollower: smoothed, held within 0.2 BPM)
        sets the engine's speed only when it changes."""
        with self._lock:
            if self._clock_port is None or port not in self._clock_listeners:
                return
            follower = self._followers.setdefault(port, ClockFollower())
            follower.message(status, at)
            fresh = port not in self._heard or at - self._heard[port] > HEARD
            if status == TICK:
                self._heard[port] = at
            followed = self._followers.get(self._following) if self._following else None
            if self._clock_port == AUTO and port != self._following and follower.bpm(at) is not None \
                    and (followed is None or followed.bpm(at) is None):
                self._following, self._measured = port, None
                fresh = True
            moved = fresh and status == TICK
            arm = False
            if port == self._following:
                bpm = follower.bpm(at)
                alive = bpm is not None
                moved = moved or alive != self._alive
                self._alive = alive
                if alive and MIN_BPM <= bpm <= MAX_BPM and bpm != self._measured:
                    self._measured, moved = bpm, True
                    if self._core is not None:
                        self._core.set_tempo(bpm, self._now())
                arm = alive and not self._watching
                self._watching = self._watching or arm
        if arm:
            self._link.call_later(ClockFollower().timeout + 0.1, self._watch_clock)
        if moved:
            self._wake()
            self.publish()

    def _watch_clock(self) -> None:
        """While a clock is followed: once it went quiet, the page is told (the tempo it gave is kept)."""
        with self._lock:
            follower = self._followers.get(self._following) if self._following else None
            alive = follower is not None and follower.bpm(self._now()) is not None
            stopped = self._alive and not alive
            self._alive = alive
            self._watching = alive
        if alive:
            self._link.call_later(ClockFollower().timeout + 0.1, self._watch_clock)
        if stopped:
            self.publish()


def _cancel(listener) -> None:
    try:
        listener.cancel()
    except Exception:   # a listener of a port that went away
        pass


def _scale_word(key: dict) -> str:
    """A key's scale as a word after its tonic: 'major', 'harmonic minor'."""
    return key["scale"].replace("-", " ")


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
