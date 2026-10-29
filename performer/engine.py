"""Performer: what is held, turned into the timed notes of a pattern (docs/performer-format.md, "The engine").

Pure and deterministic: no clock, no thread, no MIDI port. Every call names its time `t` (seconds, any origin,
never going back); advance_to(t) gives every event due up to t, in time order, and next_time() says when the next
one is due, so a scheduler can sleep until then. Inputs first play out everything due before them.

    performer = Performer(pattern, opens={6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}, bpm=96)
    performer.press(lane=5, note=48, velocity=90, t=0.0)      # the pattern starts here, at step 1
    performer.advance_to(0.0)                                  # [Event(0.0, 'on', 5, 48, 90 · 100/127), …]

Lanes. A pattern addresses lanes 1…N. With `strings` addressing (the default) the caller's lane is the string it
was played on (1 the highest), and a hit on lane k plays what is held on string k; one note per lane. With `voices`
addressing (a keyboard, any instrument without strings) a hit on lane k plays the k-th held note counted from the
top; the caller's lane only pairs a release with its press. The manual lanes of a pattern (strings only) are not
the pattern's: a press or release there passes through at once, as played, its aftertouch too.

The rules (docs/performer-format.md):
- The pattern starts at step 1 exactly at the first press on a pattern lane, with the hits of step 1 at once.
  A change of what is held while it runs does not restart it: the next hits play the new notes.
- Play mode (the pattern's `play`, or the caller's override): `all` (the default) plays every pattern lane at its
  hits, an unpressed string its open note (`opens`; with voices addressing an unheld voice rests); `pressed` plays
  only the lanes with a pressed note. Either way the grid is fixed: a missing note leaves its step silent and never
  moves a later step.
- One note per lane: every hit on a lane ends the note sounding there (a hit with nothing to play leaves the lane
  silent), and a press of another note on a pattern lane ends that lane's note at once (the chord changed there).
  A release never cuts a note: it rings until its lane's next hit (or for the pattern's gate, or until a stop).
- Catch: a press within `catch` seconds after a hit on its lane plays that hit again with the new note, so a chord
  pressed a few milliseconds after the first finger (or a change just after the beat) still sounds whole.
- When every pattern lane is released, the pattern stops one step later (a quick chord change with a gap goes on),
  ending its notes; a later press starts it again at step 1. The grace only keeps the time running: with nothing
  held its hits play nothing (no open string rings at the end), and a press within it goes on in phase (catch plays
  a hit that fell just before it). Latch on: releases keep the last held notes playing until stop() or a new press
  (the first after everything was released replaces the whole set).
- Letting go of a chord. A string released while others are still held does not ring open at once: it stays silent
  until `settle` seconds passed without another release, and the chord's root stays the one before the letting go
  began, so a chord let go of string by string (an ending) never rings an open string or wakes the bass strings
  below its root. When the other strings are still held after that, the lift was meant (C → Cmaj7, the finger on
  string 2 lifted) and the string rings open from its next hit. A press ends the settling.
- Velocity: the cell's level (hit or accent) scaled by the press velocity of the note played (an open string: the
  latest pattern-lane press).
- Starting and stopping follow presses on pattern lanes in both modes (an open string is not a press).
- Tempo: set_tempo changes the speed from that moment; the phase stays locked to the start (the press).

Chord-aware lanes (Phase 2). The chord held has a root (the caller's chord recognition, `chord_root`, given the held
notes; by default performer.chords.chord_root): what is pressed (or latched) first, then that with the open notes
the unpressed strings would ring, else none. The root string is the lowest string sounding the root: pressed there,
or open where nothing is pressed and the open note is the root's pitch class (a manual string sounds only when
pressed); without a root, the lowest pressed string. In play `all` an unpressed string below the root string stays
silent (a pressed one still plays), so a C (x32010) never rings the open low E. The lanes R (the root string) and A
(the alternate bass: root on string 6 or 5 → 4, on 4 → 3, else the next string up) follow the chord; with voices
addressing R is the lowest held voice and A the second lowest. A string an R or A hit covers at a step plays once,
even when its own lane hits there too (at the loudest of the two). Strings the caller marks muted (set_muted: a
voicing's x) never ring open; a change of them made while nothing is held (the voicing's root let go) waits for the
next press, so a latched voicing keeps its muted strings. Catch applies to every lane whose note a late press
changes: an open string the new root mutes ends, an R or A hit the new root moves plays again on its new string.
"""
import heapq
import math
import random
from dataclasses import dataclass, field

from .chords import chord_root as default_chord_root
from .pattern import ACCENT, ALT_LANE, HIT, RELATIVE, ROOT_LANE, Pattern

STRINGS, VOICES = "strings", "voices"
ADDRESSING = (STRINGS, VOICES)
ALL, PRESSED = "all", "pressed"
PLAY_MODES = (ALL, PRESSED)
CATCH = 0.03                  # seconds: a press this soon after its lane's hit plays that hit again
SETTLE = 0.12                 # seconds: a string let go of while others are held stays silent this long
MIN_BPM, MAX_BPM = 20.0, 300.0
PATTERN, MANUAL = "pattern", "manual"
ALTERNATE = {6: 4, 5: 4, 4: 3}         # root string → its alternate bass string; any other: the next string up


@dataclass(frozen=True, order=True)
class Event:
    """One output event: a note on or off, or (manual lanes only) aftertouch; `value` is the velocity or pressure."""
    time: float
    kind: str                   # 'on', 'off', 'aftertouch'
    lane: int
    note: int
    value: int = 0
    source: str = PATTERN       # 'pattern' or 'manual'


@dataclass(frozen=True)
class PerformerState:
    running: bool
    step: int | None            # the pattern step playing now, 0-based (None while stopped)
    latch: bool
    bpm: float
    held: tuple[tuple[int, int], ...]      # (lane, note) physically held, lowest lane first
    latched: tuple[tuple[int, int], ...]   # (lane, note) the latch keeps playing
    root: int | None = None                # strings: the root string of what is held (None: nothing held)


@dataclass(order=True)
class _Due:
    time: float
    seq: int
    action: str = field(compare=False)     # 'step', 'hit', 'off', 'stop'
    lane: int | str = field(default=0, compare=False)   # a lane number, or R / A (resolved when the hit is due)
    level: int = field(default=0, compare=False)
    token: int = field(default=0, compare=False)
    step: tuple = field(default=(), compare=False)      # a hit's step identity: (the pattern's generation, step)


class Performer:
    def __init__(self, pattern: Pattern | None = None, *, addressing: str = STRINGS, opens: dict | None = None,
                 bpm: float = 100.0, latch: bool = False, catch: float = CATCH, seed: int = 0,
                 play: str | None = None, chord_root=None, settle: float = SETTLE):
        if addressing not in ADDRESSING:
            raise ValueError(f"addressing is {' or '.join(ADDRESSING)}, not {addressing!r}")
        self.play = _play(play)                                  # None: the pattern's own play mode
        self.pattern = pattern
        self.addressing = addressing
        self.opens = {int(k): int(v) for k, v in (opens or {}).items()}
        self.bpm = _bpm(bpm)
        self.latch = bool(latch)
        self.catch = float(catch)
        self.settle = float(settle)
        self._lifted: set[int] = set()                           # strings let go of while others are held
        self._lift_at: float | None = None                       # … the latest of those releases
        self._settle_root: int | None = None                     # the root string before the letting go began
        self._pending_muted: frozenset[int] | None = None        # set_muted with nothing held: at the next press
        self._random = random.Random(seed)
        self._now = float("-inf")
        self._out: list[Event] = []
        self._due: list[_Due] = []
        self._seq = 0
        self._held: dict[int, list[tuple[int, int]]] = {}       # lane → [(note, velocity)], newest last
        self._latched: dict[int, tuple[int, int]] = {}           # strings: lane → (note, velocity)
        self._latched_voices: list[tuple[int, int]] = []         # voices: (note, velocity)
        self._sounding: dict[int, tuple[int, int]] = {}          # pattern lane → (note, token)
        self._manual: dict[int, int] = {}                        # manual lane → note sounding
        self._last_hit: dict[int, tuple[float, int, int | None]] = {}   # lane → (time, level, note played)
        self._last_relative: dict[str, tuple[float, int, int | None, tuple]] = {}  # R/A → (time, level, lane, step)
        self._played_at: dict[int, tuple] = {}                   # lane → the step identity it last played at
        self._generation = 0                                     # set_pattern counts up: a new pattern's steps are new
        self._muted: frozenset[int] = frozenset()                # strings that never ring open (a voicing's x)
        self.chord_root = chord_root or default_chord_root       # notes → the root's pitch class, or None
        self._roots: dict[tuple, int | None] = {}                # chord_root's answers, by the notes
        self._velocity = 100                                     # the latest pattern-lane press
        self._token = 0
        self._running = False
        self._anchor = (0.0, 0.0)                                # (time, step position) the tempo counts from
        self._next_step = 0
        self._stop_at: float | None = None

    # === inputs ============================================================================================
    def press(self, lane: int, note: int, velocity: int, t: float) -> None:
        self.press_chord([(lane, note, velocity)], t)

    def press_chord(self, notes, t: float) -> None:
        """Several presses at one time t, (lane, note, velocity) each: held together, then the pattern starts (or
        catches up) once, so a chord a program presses at once (a voicing) sounds whole from its first hit."""
        self._advance(t)
        pressed = []
        if self._pending_muted is not None and any(not self._is_manual(int(lane)) for lane, _, _ in notes):
            self._muted, self._pending_muted = self._pending_muted, None
        for lane, note, velocity in notes:
            lane, note, velocity = int(lane), int(note), max(1, min(127, int(velocity)))
            if self._is_manual(lane):
                self._hold(lane, note, velocity)
                if lane in self._manual:
                    self._emit(t, "off", lane, self._manual.pop(lane), 0, MANUAL)
                self._manual[lane] = note
                self._emit(t, "on", lane, note, velocity, MANUAL)
                continue
            if self.latch and not self._pattern_held():
                self._latched.clear()                 # the first press after everything was released: a new set
                self._latched_voices.clear()
            self._hold(lane, note, velocity)
            if self.latch:
                if self.addressing == STRINGS:
                    self._latched[lane] = (note, velocity)
                else:
                    self._latched_voices = [v for v in self._latched_voices if v[0] != note] + [(note, velocity)]
            self._velocity = velocity
            self._stop_at = None
            self._lifted.clear()                          # a press: the chord is what is held again
            self._lift_at = self._settle_root = None
            if self.addressing == STRINGS:
                sounding = self._sounding.get(lane)
                if sounding is not None and sounding[0] != note:      # the chord changed on this lane
                    self._end(lane, t)
            pressed.append(lane)
        if not pressed:
            return
        if not self._running:
            if self.pattern is not None:
                self._start(t)
        else:
            self._catch(t, pressed[-1])
        self._advance(t)

    def release(self, lane: int, note: int, t: float) -> None:
        self._advance(t)
        lane, note = int(lane), int(note)
        lifting = self.addressing == STRINGS and not self._is_manual(lane) and self.holding(lane, note)
        root = self._root_string() if lifting else None
        self._unhold(lane, note)
        if self._is_manual(lane):
            if self._manual.get(lane) == note:
                del self._manual[lane]
                self._emit(t, "off", lane, note, 0, MANUAL)
            return
        if lifting and not self._held.get(lane) and self._pattern_held():
            if not self._settling():
                self._lifted.clear()
                self._settle_root = root                  # the chord's root before the letting go began
            self._lifted.add(lane)
            self._lift_at = t
        if self._running and not self.latch and not self._pattern_held():
            self._stop_at = t + self._step_seconds()      # a grace of one step

    def aftertouch(self, lane: int, note: int, pressure: int, t: float) -> None:
        """Passed through on a manual lane for the note sounding there; the pattern's notes take none."""
        self._advance(t)
        lane, note = int(lane), int(note)
        if self._is_manual(lane) and self._manual.get(lane) == note:
            self._emit(t, "aftertouch", lane, note, max(0, min(127, int(pressure))), MANUAL)

    def set_tempo(self, bpm: float, t: float) -> None:
        """From t on, steps follow `bpm` (quarter notes a minute); the phase stays where it is."""
        self._advance(t)
        self._reanchor(t)
        self.bpm = _bpm(bpm)

    def set_pattern(self, pattern: Pattern, t: float) -> None:
        """A running pattern goes on in the new one at the same place in time from its start (counted in beats, so
        a 1/8 pattern changed for a 1/16 one stays on the beat), from the new pattern's next step; notes on lanes
        that change between pattern and manual end. What is held stays held: a string that became manual plays again
        only when pressed again, one that became a pattern string plays its held note from its next hit. The new
        pattern's steps are new ones (a hit is played once per lane and step, and a step number of the new pattern may
        equal one the old pattern played at: 1/8 → 1/4 halves the numbers)."""
        self._advance(t)
        self._generation += 1                 # step numbers re-mapped (1/8 → 1/4 halves them) never repeat an old one
        if self._running and self.pattern is not None:
            beats = self._position(t) * float(self.pattern.step_quarters)
            position = beats / float(pattern.step_quarters)
            self._anchor = (t, position)
            self._next_step = math.floor(position + 1e-9) + 1    # a step falling on t was played by the old one
        self.pattern = pattern
        for lane in [lane for lane in self._sounding if self._is_manual(lane)]:
            self._end(lane, t)
        for lane in [lane for lane in self._manual if not self._is_manual(lane)]:
            self._emit(t, "off", lane, self._manual.pop(lane), 0, MANUAL)
        if self._running and not self._pattern_held() and not self.latch:
            self._stop_at = t + self._step_seconds()

    def set_play(self, mode: str | None, t: float) -> None:
        """Override the pattern's play mode from t on ('all' or 'pressed'); None goes back to the pattern's."""
        self._advance(t)
        self.play = _play(mode)

    def set_muted(self, lanes, t: float) -> None:
        """Strings that never ring open from t on (a voicing's muted strings); () for none. A pressed one plays. With
        nothing held on a pattern lane (a voicing's root let go) the change waits for the next press."""
        self._advance(t)
        muted = frozenset(int(lane) for lane in lanes)
        if self._pattern_held() or muted >= self._muted:
            self._muted, self._pending_muted = muted, None
        else:
            self._pending_muted = muted

    @property
    def play_mode(self) -> str:
        """The play mode in force: the override, else the pattern's ('all' without a pattern)."""
        return self.play or (self.pattern.play if self.pattern is not None else ALL)

    def set_latch(self, on: bool, t: float) -> None:
        """On: what is held now keeps playing after its release. Off: the latched notes go; with nothing held the
        pattern stops one step later."""
        self._advance(t)
        on = bool(on)
        if on == self.latch:
            return
        self.latch = on
        if on:
            self._latched = {lane: stack[-1] for lane, stack in self._held.items() if stack and not self._is_manual(lane)}
            self._latched_voices = self._held_voices()
            return
        self._latched.clear()
        self._latched_voices.clear()
        if self._running and not self._pattern_held():
            self._stop_at = t + self._step_seconds()

    def stop(self, t: float) -> None:
        """The pattern stops now, its notes off; the latched notes go. Manual notes are the player's: they stay."""
        self._advance(t)
        self._latched.clear()
        self._latched_voices.clear()
        self._halt(t)

    def end_held(self, notes, t: float) -> None:
        """The caller ended these held notes (a window shift): they count as released, and a manual note of one of
        those pitches ends now."""
        self._advance(t)
        wanted = {int(n) for n in notes}
        for lane in list(self._held):
            for note, _ in [v for v in self._held[lane] if v[0] in wanted]:
                self.release(lane, note, t)

    def silence(self, t: float) -> None:
        """Everything ends now: the pattern stops and every manual note goes off; nothing stays held."""
        self._advance(t)
        self._held.clear()
        self._latched.clear()
        self._latched_voices.clear()
        self._lifted.clear()
        self._lift_at = self._settle_root = None
        if self._pending_muted is not None:
            self._muted, self._pending_muted = self._pending_muted, None
        for lane in sorted(self._manual):
            self._emit(t, "off", lane, self._manual.pop(lane), 0, MANUAL)
        self._halt(t)

    # === output ============================================================================================
    def advance_to(self, t: float) -> list[Event]:
        """Every event due up to t, in time order (and those the inputs since the last call made)."""
        self._advance(t)
        out, self._out = self._out, []
        return out

    def next_time(self) -> float | None:
        """When the next event is due (a step, a hit, a gate's end or the grace's stop), or None."""
        times = [self._due[0].time] if self._due else []
        if self._running and self.pattern is not None:
            times.append(self._step_due(self._next_step))
        if self._stop_at is not None:
            times.append(self._stop_at)
        return min(times) if times else None

    def state(self, t: float | None = None) -> PerformerState:
        step = None
        if self._running and self.pattern is not None:
            at = self._now if t is None else max(t, self._now)
            step = int(self._position(at)) % self.pattern.length if at >= self._anchor[0] else 0
        shown = (lambda stack: stack[-1:]) if self.addressing == STRINGS else (lambda stack: stack)
        held = tuple(sorted((lane, note) for lane, stack in self._held.items() for note, _ in shown(stack)))
        latched = tuple(sorted((lane, v[0]) for lane, v in self._latched.items())) if self.addressing == STRINGS \
            else tuple((k + 1, v[0]) for k, v in enumerate(sorted(self._latched_voices, reverse=True)))
        return PerformerState(self._running, step, self.latch, self.bpm, held, latched,
                              self._root_string() if self.addressing == STRINGS else None)

    @property
    def running(self) -> bool:
        return self._running

    def holding(self, lane: int, note: int) -> bool:
        """Whether the caller's lane holds that note (a press seen, its release not yet)."""
        return any(v[0] == int(note) for v in self._held.get(int(lane), ()))

    def pressed(self) -> tuple[tuple[int, int], ...]:
        """Every (lane, note) held, lowest lane first (all of a lane's notes, not only the one it plays)."""
        return tuple(sorted((lane, note) for lane, stack in self._held.items() for note, _ in stack))

    # === time ==============================================================================================
    def _step_seconds(self) -> float:
        quarters = float(self.pattern.step_quarters) if self.pattern is not None else 0.5
        return 60.0 / self.bpm * quarters

    def _position(self, t: float) -> float:
        anchor_time, anchor_position = self._anchor
        return anchor_position + (t - anchor_time) / self._step_seconds()

    def _time_of(self, position: float) -> float:
        anchor_time, anchor_position = self._anchor
        return anchor_time + (position - anchor_position) * self._step_seconds()

    def _reanchor(self, t: float) -> None:
        if self._running:
            self._anchor = (t, self._position(t))

    def _early(self) -> float:
        return self.pattern.timing / 1000.0 if self.pattern is not None else 0.0

    def _step_due(self, k: int) -> float:
        """When step k's hits are worked out: at its time, earlier by the humanize range (a hit may come early)."""
        return max(self._time_of(k) - self._early(), self._anchor[0] if k == 0 else float("-inf"))

    # === the loop ==========================================================================================
    def _advance(self, t: float) -> None:
        t = float(t)
        if t < self._now:
            t = self._now                                   # time never goes back
        while True:
            candidates = []
            if self._due:
                candidates.append((self._due[0].time, 1))
            if self._running and self.pattern is not None:
                candidates.append((self._step_due(self._next_step), 0))
            if self._stop_at is not None:
                candidates.append((self._stop_at, 2))
            if not candidates:
                break
            when, kind = min(candidates)
            if when > t:
                break
            self._now = max(self._now, when)
            if kind == 0:
                self._materialise(self._next_step)
                self._next_step += 1
            elif kind == 1:
                self._fire(heapq.heappop(self._due))
            else:
                self._stop_at = None
                if not self._pattern_held() and not self.latch:
                    self._halt(when)
        self._now = max(self._now, t)

    def _start(self, t: float) -> None:
        self._running = True
        self._anchor = (t, 0.0)
        self._next_step = 0
        self._last_hit.clear()
        self._last_relative.clear()
        self._played_at.clear()

    def _halt(self, t: float) -> None:
        for lane in sorted(self._sounding):
            self._end(lane, t)
        self._due = [d for d in self._due if d.action not in ("hit", "off")]
        heapq.heapify(self._due)
        self._running = False
        self._stop_at = None
        self._last_hit.clear()
        self._last_relative.clear()

    def _materialise(self, k: int) -> None:
        """Step k's hits go into the queue: swing, strum spread and humanize applied; notes are chosen when each
        hit is due."""
        pattern = self.pattern
        index = k % pattern.length
        hits = []                                    # (lane or R/A, level, the lane it falls on now)
        for lane, level in pattern.hits_at(index):
            target = self._resolve(lane)
            if target is None and lane in RELATIVE:
                continue
            if not self._is_manual(target if target is not None else lane):
                hits.append((lane, level, target if target is not None else lane))
        if not hits:
            return
        loudest: dict[int, int] = {}                 # a lane an R or A hit covers plays once, at the louder level
        for _, level, target in hits:
            loudest[target] = max(level, loudest.get(target, 0))
        swing = (2 * pattern.swing / 100.0 - 1.0) if index % 2 else 0.0
        base = self._time_of(k + swing)
        strum = pattern.strum_at(index)
        order = sorted(hits, key=lambda h: (h[2], lane_rank(h[0])), reverse=(strum == "down"))   # down: low first
        floor = self._anchor[0] if k == 0 else self._now
        seen: set[int] = set()
        for lane, _, target in order:
            offset = len(seen) * pattern.spread / 1000.0 if strum else 0.0
            if target not in seen:
                seen.add(target)
            jitter = self._random.uniform(-pattern.timing, pattern.timing) / 1000.0 if pattern.timing else 0.0
            self._push(max(base + offset + jitter, floor), "hit", lane, loudest[target], step=(self._generation, k))

    def _fire(self, due: _Due) -> None:
        if due.action == "off":
            sounding = self._sounding.get(due.lane)
            if sounding is not None and sounding[1] == due.token:
                self._end(due.lane, due.time)
            return
        if due.action == "hit" and self._running:
            lane = self._resolve(due.lane)
            if due.lane in RELATIVE:
                self._last_relative[due.lane] = (due.time, due.level, lane, due.step)
            if lane is None or self._is_manual(lane) or self._played_at.get(lane) == due.step:
                return                               # no chord to follow, a manual string, or played at this step
            self._played_at[lane] = due.step
            self._hit(lane, due.level, due.time)

    def _hit(self, lane: int, level: int, t: float) -> None:
        self._end(lane, t)
        chosen = self._note_for(lane)
        self._last_hit[lane] = (t, level, chosen[0] if chosen else None)
        if chosen is None:
            return
        note, pressed = chosen
        pattern = self.pattern
        cell = pattern.accent if level == ACCENT else pattern.hit if level == HIT else 0
        velocity = round(cell * pressed / 127)
        if pattern.jitter:
            velocity += self._random.randint(-pattern.jitter, pattern.jitter)
        velocity = max(1, min(127, velocity))
        self._token += 1
        self._sounding[lane] = (note, self._token)
        self._emit(t, "on", lane, note, velocity, PATTERN)
        if pattern.gate is not None:
            self._push(self._time_of(self._position(t) + pattern.gate), "off", lane, token=self._token)

    def _catch(self, t: float, lane: int) -> None:
        """A press just after a hit plays that hit again with what is held now (see the module text): every lane
        whose note changed (an open string the new root mutes ends), and an R or A hit on the string it moved to."""
        for name, (when, level, before, step) in sorted(self._last_relative.items()):
            now = self._resolve(name)
            if t - when > self.catch or now is None or now == before or self._is_manual(now):
                continue
            self._last_relative[name] = (when, level, now, step)
            if self._played_at.get(now) != step:
                self._played_at[now] = step
                self._hit(now, level, t)
        for k in sorted(self._last_hit):
            last = self._last_hit.get(k)
            if last is None or t - last[0] > self.catch:
                continue
            chosen = self._note_for(k)
            if chosen is not None and chosen[0] != last[2]:
                self._hit(k, last[1], t)
            elif chosen is None and last[2] is not None and k in self._sounding:
                self._end(k, t)
                self._last_hit[k] = (last[0], last[1], None)

    def _end(self, lane: int, t: float) -> None:
        sounding = self._sounding.pop(lane, None)
        if sounding is not None:
            self._emit(t, "off", lane, sounding[0], 0, PATTERN)

    # === what is held ======================================================================================
    def _is_manual(self, lane: int) -> bool:
        return self.addressing == STRINGS and self.pattern is not None and lane in self.pattern.manual

    def _hold(self, lane: int, note: int, velocity: int) -> None:
        stack = [v for v in self._held.get(lane, []) if v[0] != note]
        self._held[lane] = stack + [(note, velocity)]

    def _unhold(self, lane: int, note: int) -> None:
        stack = [v for v in self._held.get(lane, []) if v[0] != note]
        if stack:
            self._held[lane] = stack
        else:
            self._held.pop(lane, None)

    def _pattern_held(self) -> bool:
        return any(stack for lane, stack in self._held.items() if not self._is_manual(lane))

    def _held_voices(self) -> list[tuple[int, int]]:
        voices: dict[int, int] = {}
        for lane, stack in self._held.items():
            for note, velocity in stack:
                voices[note] = velocity
        return list(voices.items())

    def _note_for(self, lane: int) -> tuple[int, int] | None:
        """(note, its press velocity) a hit on `lane` plays now, or None (a rest)."""
        if self.addressing == VOICES:
            ordered = sorted(self._voices(), reverse=True)
            return ordered[lane - 1] if 0 < lane <= len(ordered) else None
        stack = self._held.get(lane)
        if stack:
            return stack[-1]
        if self.latch and lane in self._latched:
            return self._latched[lane]
        if self.play_mode == ALL and lane in self.opens and lane not in self._muted:
            if not self.latch and not self._pattern_held():
                return None                          # nothing held (the grace step): no open string rings
            if lane in self._lifted and self._settling():
                return None                          # let go of a moment ago, the chord still held: not yet open
            root = self._root_string()
            if root is not None and lane > root:
                return None                          # below the chord's root string: silent (a C's low E)
            return self.opens[lane], self._velocity
        return None

    def _voices(self) -> list[tuple[int, int]]:
        return self._latched_voices if self.latch else self._held_voices()

    # --- the chord: its root string and the lanes that follow it ------------------------------------------
    def _chord(self) -> dict[int, int]:
        """strings: lane → the note it holds (pressed, else latched), manual lanes too."""
        chord = {lane: v[0] for lane, v in self._latched.items()} if self.latch else {}
        chord.update({lane: stack[-1][0] for lane, stack in self._held.items() if stack})
        return chord

    def _root_of(self, notes) -> int | None:
        key = tuple(sorted(notes))
        if key not in self._roots:
            if len(self._roots) > 256:
                self._roots.clear()
            self._roots[key] = self.chord_root(list(key))
        return self._roots[key]

    def _settling(self) -> bool:
        """Whether a chord is being let go of: a string was released within `settle` while others are held."""
        return self._lift_at is not None and self._now - self._lift_at < self.settle

    def _root_string(self) -> int | None:
        """The root string of what is held (the module text), or None when nothing is held; while a chord is being
        let go of (_settling), the root string it had before."""
        if self._settle_root is not None and self._settling() and (self._pattern_held() or self.latch):
            return self._settle_root
        chord = self._chord()
        if not chord:
            return None
        ringing = {lane: note for lane, note in self.opens.items() if lane not in chord and not self._is_manual(lane)
                   and lane not in self._muted} if self.play_mode == ALL else {}
        root = self._root_of(chord.values())
        if root is None and ringing:
            root = self._root_of([*chord.values(), *ringing.values()])
        if root is not None:
            sounding = {**ringing, **chord}
            for lane in sorted(sounding, reverse=True):          # the lowest string first
                if sounding[lane] % 12 == root:
                    return lane
        return max(chord)

    def _resolve(self, lane) -> int | None:
        """The lane a hit on `lane` plays: a number is itself; R and A follow what is held (None: nothing to)."""
        if lane not in RELATIVE:
            return lane
        if self.addressing == VOICES:
            count = len(self._voices())
            found = count if lane == ROOT_LANE else count - 1
            return found if found >= 1 else None
        root = self._root_string()
        if root is None:
            return None
        if lane == ROOT_LANE:
            return root
        alternate = ALTERNATE.get(root, root - 1)
        return alternate if alternate >= 1 else None

    # === plumbing ==========================================================================================
    def _push(self, t: float, action: str, lane: int | str = 0, level: int = 0, token: int = 0, step: tuple = ()) -> None:
        self._seq += 1
        heapq.heappush(self._due, _Due(t, self._seq, action, lane, level, token, step))

    def _emit(self, t: float, kind: str, lane: int, note: int, value: int, source: str) -> None:
        self._out.append(Event(t, kind, lane, note, value, source))


def lane_rank(lane) -> int:
    """Among hits on one string: its own lane first, then R, then A."""
    return 0 if lane not in RELATIVE else 1 + RELATIVE.index(lane)


def _play(mode: str | None) -> str | None:
    if mode is None:
        return None
    if mode not in PLAY_MODES:
        raise ValueError(f"play is {' or '.join(PLAY_MODES)}, not {mode!r}")
    return mode


def _bpm(value: float) -> float:
    bpm = float(value)
    if not MIN_BPM <= bpm <= MAX_BPM:
        raise ValueError(f"tempo {bpm:g} BPM is outside {MIN_BPM:g}–{MAX_BPM:g}")
    return bpm
