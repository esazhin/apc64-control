"""The 'performer:' block of a generated layout's 'lab:' section (contract 2 §2.10): which pattern plays over what is
held, the latch and the tempo.

    lab:
      generator: guitar
      performer:
        pattern: travis               # a pattern in patterns/: its file name (travis.yaml) or its name
        latch: off                    # on: what was held keeps playing after release (Play toggles it)
        play: all                     # override the pattern's play mode: all (unpressed strings ring open) or pressed
        tempo: 96                     # BPM 20–300, or clock: follow the MIDI clock of the 'clock' input
        clock: MPC Live III MIDI 1    # the MIDI input that sends the clock (tempo: clock)
        addressing: strings           # strings (the guitar: a lane per string) or voices; default by the generator
        chords: [maj, min, 7, maj7, m7, sus2, sus4, dim]   # the chord types on the type pads (Phase 2), 1–8
        slots: [travis, strum, waltz, ~, ~, ~, ~, ~]       # the patterns on the slot pads, 1–8 (~: an empty slot)

With the block, the performer is on when the layout is activated, Play toggles the latch and Stop stops the
pattern (the section binds both on the base layer, as it binds the encoder and Tempo). Without it, the layout
plays as before; the page can still turn a performer on for the session.

Chord types and pattern slots (Phase 2): `chords` names the chord types of the type pads in their order (a name
from performer.CHORD_TYPES, default the eight of DEFAULT_TYPES), `slots` the patterns of the slot pads (an empty slot,
~, is silent). Where the pads are and what they send is performer_pads.py. Chords in key (2026-10-29): `key` and
`key 7` are the key's own triad and seventh from the root pressed (performer.diatonic_chord), the key being the
layout's scale (its scheme: scale), or the page's Key for the session.
"""
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Mapping

from _apc64_host.domain.layout import SectionList, SectionMap, SectionScalar
from performer import CHORD_TYPES, DEFAULT_TYPES, KEY_TYPES, chord_type, key_type

KEYS = ("pattern", "latch", "play", "tempo", "clock", "addressing", "chords", "slots")
SLOTS = 8
PLAY_MODES = ("all", "pressed")
ADDRESSING = ("strings", "voices")
DEFAULT_BPM = 100.0
MIN_BPM, MAX_BPM = 20, 300
CLOCK = "clock"
ON_WORDS, OFF_WORDS = ("on", "true", "yes", "1"), ("off", "false", "no", "0")


@dataclass(frozen=True)
class PerformerSettings:
    """A layout's performer block, as written: the pattern (an id or a name), the latch, the play mode (None: the
    pattern's), the tempo (a BPM, or the MIDI clock of `clock`) and the addressing (None: strings when the generator
    sends a string per channel)."""
    pattern: str
    latch: bool = False
    bpm: float = DEFAULT_BPM
    clock: str | None = None
    addressing: str | None = None
    play: str | None = None
    chords: tuple[str, ...] = DEFAULT_TYPES        # the type pads' chord types, in order
    slots: tuple[str | None, ...] = ()             # the slot pads' patterns (None: an empty slot)

    @property
    def follows_clock(self) -> bool:
        return self.clock is not None

    def to_json(self) -> dict:
        return {"pattern": self.pattern, "latch": self.latch, "play": self.play,
                "tempo": CLOCK if self.follows_clock else self.bpm, "clock": self.clock, "addressing": self.addressing,
                "chords": list(self.chords), "slots": list(self.slots)}


@dataclass(frozen=True)
class BlockIssue:
    line: int
    field: str | None
    problem: str
    fix: str | None
    warning: bool = False


def on_off(value) -> bool | None:
    word = str(value).strip().lower() if value is not None else ""
    return True if word in ON_WORDS else False if word in OFF_WORDS else None


def parse_performer(entry, strings: bool, patterns: Mapping[str, str] | None = None
                    ) -> tuple[PerformerSettings | None, list[BlockIssue], dict[str, int]]:
    """The block (a SectionEntry) → (settings or None, issues, field lines). `strings`: the generator sends each
    string on its own channel; `patterns`: {id: name} of the patterns available (None: not checked)."""
    issues: list[BlockIssue] = []
    lines: dict[str, int] = {}
    body = entry.value
    if not isinstance(body, SectionMap):
        issues.append(BlockIssue(entry.line, "performer", "the performer block is a mapping",
                                 "write 'performer:' then '    pattern: travis'"))
        return None, issues, lines
    values: dict = {}
    for item in body.entries:
        key = item.key.strip().lower()
        lines[f"lab.performer.{key}"] = item.line
        if key not in KEYS:
            near = get_close_matches(key, KEYS, n=1)
            issues.append(BlockIssue(item.line, "performer", f"unknown key '{item.key}'",
                                     (f"did you mean {near[0]}? " if near else "") + "the performer block takes "
                                     + ", ".join(KEYS)))
            continue
        values[key] = (item.line, item.value)
    pattern = _pattern(values, entry.line, patterns, issues)
    latch = False
    if "latch" in values:
        line, node = values["latch"]
        latch = on_off(_scalar(node))
        if latch is None:
            issues.append(BlockIssue(line, "latch", f"'{_scalar(node)}' is not on or off", "write 'latch: on' or 'latch: off'"))
            latch = False
    play = None
    if "play" in values:
        line, node = values["play"]
        play = str(_scalar(node)).strip().lower()
        if play not in PLAY_MODES:
            issues.append(BlockIssue(line, "play", f"'{_scalar(node)}' is not all or pressed",
                                     "all: every lane plays at its hits, an unpressed string open; pressed: only "
                                     "pressed strings play; leave it out for the pattern's own"))
            play = None
    bpm, clock = _tempo(values, issues)
    addressing = None
    if "addressing" in values:
        line, node = values["addressing"]
        addressing = str(_scalar(node)).strip().lower()
        if addressing not in ADDRESSING:
            issues.append(BlockIssue(line, "addressing", f"'{_scalar(node)}' is not strings or voices",
                                     "strings: lane k is string k (a guitar layout); voices: the k-th held note from the top"))
            addressing = None
        elif addressing == "strings" and not strings:
            issues.append(BlockIssue(line, "addressing", "strings needs a generator that sends each string on its "
                                     "own channel (the guitar)", "write 'addressing: voices' or leave it out"))
            addressing = None
    chords = _chords(values, issues)
    slots = _slots(values, patterns, issues)
    if any(not issue.warning for issue in issues) or pattern is None:
        return None, issues, lines
    return PerformerSettings(pattern, latch, bpm, clock, addressing, play, chords, slots), issues, lines


def _items(node) -> list:
    if isinstance(node, SectionList):
        return [_scalar(item) for item in node.items]
    value = _scalar(node)
    return [] if value is None else [value]


def _chords(values, issues) -> tuple[str, ...]:
    if "chords" not in values:
        return DEFAULT_TYPES
    line, node = values["chords"]
    names, found = _items(node), []
    if not 1 <= len(names) <= SLOTS:
        issues.append(BlockIssue(line, "chords", f"{len(names)} chord types", f"write 1–{SLOTS}, e.g. "
                                 f"[{', '.join(DEFAULT_TYPES)}]"))
        return DEFAULT_TYPES
    for name in names:
        kind = chord_type(name) if name is not None else None
        chosen = kind.name if kind is not None else key_type(name) if name is not None else None
        if chosen is None:
            near = get_close_matches(str(name), [*KEY_TYPES, *CHORD_TYPES], n=1)
            issues.append(BlockIssue(line, "chords", f"no chord type '{name}'",
                                     (f"did you mean {near[0]}? " if near else "") + "chord types: "
                                     + ", ".join([*KEY_TYPES, *CHORD_TYPES])))
            continue
        if chosen in found:
            issues.append(BlockIssue(line, "chords", f"chord type {chosen} is listed twice", "keep one"))
            continue
        found.append(chosen)
    return tuple(found)


def _slots(values, patterns, issues) -> tuple[str | None, ...]:
    if "slots" not in values:
        return ()
    line, node = values["slots"]
    names = _items(node)
    if not 1 <= len(names) <= SLOTS:
        issues.append(BlockIssue(line, "slots", f"{len(names)} pattern slots",
                                 f"write 1–{SLOTS} patterns, ~ for an empty slot, e.g. [travis, strum, ~, waltz]"))
        return ()
    found: list[str | None] = []
    for name in names:
        text = " ".join(str(name).split()) if name is not None else ""
        if not text or text == "-":
            found.append(None)
            continue
        if patterns is not None and find_pattern(text, patterns) is None:
            near = get_close_matches(text.lower(), sorted(patterns), n=1)
            issues.append(BlockIssue(line, "slots", f'no pattern "{text}"',
                                     (f"did you mean {near[0]}? " if near else "")
                                     + "available: " + ", ".join(sorted(patterns))))
            continue
        found.append(text)
    return tuple(found)


def _pattern(values, line, patterns, issues) -> str | None:
    if "pattern" not in values:
        issues.append(BlockIssue(line, "performer", "the performer block names no pattern",
                                 "add 'pattern: <name>'" + (f"; available: {', '.join(sorted(patterns))}" if patterns else "")))
        return None
    at, node = values["pattern"]
    name = " ".join(str(_scalar(node) or "").split())
    if not name:
        issues.append(BlockIssue(at, "pattern", "the pattern is empty", "write a pattern's file name, e.g. 'pattern: travis'"))
        return None
    if patterns is not None and find_pattern(name, patterns) is None:
        near = get_close_matches(name.lower(), sorted(patterns), n=1)
        issues.append(BlockIssue(at, "pattern", f'no pattern "{name}"',
                                 (f"did you mean {near[0]}? " if near else "")
                                 + ("available: " + ", ".join(sorted(patterns)) if patterns
                                    else "add a pattern file to patterns/ (docs/performer-format.md)")))
        return None
    return name


def find_pattern(name: str, patterns: Mapping[str, str]) -> str | None:
    """The pattern id that `name` names: an id (the file name without .yaml), or a display name, any case."""
    wanted = " ".join(str(name).split()).casefold()
    for pattern_id, display in patterns.items():
        if str(pattern_id).casefold() == wanted or str(pattern_id).casefold() == wanted.removesuffix(".yaml"):
            return str(pattern_id)
    for pattern_id, display in patterns.items():
        if display is not None and " ".join(str(display).split()).casefold() == wanted:
            return str(pattern_id)
    return None


def _tempo(values, issues) -> tuple[float, str | None]:
    bpm, follows = DEFAULT_BPM, False
    if "tempo" in values:
        line, node = values["tempo"]
        value = _scalar(node)
        if isinstance(value, str) and value.strip().lower() == CLOCK:
            follows = True
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not MIN_BPM <= value <= MAX_BPM:
            issues.append(BlockIssue(line, "tempo", f"'{value}' is not a tempo",
                                     f"write a BPM {MIN_BPM}–{MAX_BPM} (quarter notes a minute), or 'tempo: clock' with "
                                     "'clock: <MIDI input>'"))
        else:
            bpm = float(value)
    clock = None
    if "clock" in values:
        line, node = values["clock"]
        clock = " ".join(str(_scalar(node) or "").split()) or None
        if clock is None:
            issues.append(BlockIssue(line, "clock", "the clock input is empty",
                                     "write the MIDI input that sends the clock, as 'apc64 ports' lists it"))
        elif "tempo" in values and not follows:
            issues.append(BlockIssue(line, "clock", "the clock input is unused with a BPM",
                                     "write 'tempo: clock' to follow it, or remove 'clock:'", warning=True))
            clock = None
    elif follows:
        issues.append(BlockIssue(values["tempo"][0], "tempo", "tempo: clock names no clock input",
                                 "add 'clock: <MIDI input>', e.g. the MPC's port as 'apc64 ports' lists it"))
    return bpm, clock


def _scalar(node):
    if isinstance(node, SectionScalar):
        return node.value
    if isinstance(node, SectionList):
        return [_scalar(item) for item in node.items]
    return None
