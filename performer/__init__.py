"""The performer: strumming and fingerpicking patterns played over what is held (docs/performer-format.md).

A pure, deterministic core with no MIDI port, thread or clock of its own, shared with other projects: the pattern
format (pattern.py), the engine that turns presses into timed notes (engine.py), the follower of an external
MIDI clock (clock.py), the chord types with a chord's root (chords.py) and the voicing of a root and a chord type on
the strings (voicing.py). Standard library only; nothing here knows the APC64 (README.md).
"""
from .chords import CHORD_TYPES, DEFAULT_TYPES, KEY, KEY_7, KEY_TYPES, ChordType, chord_root, chord_type, diatonic_chord, key_type
from .clock import ClockFollower
from .engine import (
    ADDRESSING, ALL, ALTERNATE, MANUAL, PATTERN, PLAY_MODES, PRESSED, STRINGS, VOICES, Event, Performer,
    PerformerState,
)
from .pattern import (
    ACCENT, ALT_LANE, HIT, KEYS, MAX_LANE, MAX_LENGTH, RELATIVE, REST, ROOT_LANE, STEPS, Issue, Meter, Pattern,
    PatternError, check_pattern, lane_key, lane_order, parse_pattern, row_cells, row_text, to_data,
)
from .voicing import Voicing, VoicingError, build_voicing

__all__ = ["ACCENT", "ADDRESSING", "ALL", "ALTERNATE", "ALT_LANE", "CHORD_TYPES", "DEFAULT_TYPES", "HIT", "KEYS",
           "MANUAL", "MAX_LANE", "MAX_LENGTH", "PATTERN", "PLAY_MODES", "PRESSED", "RELATIVE", "REST", "ROOT_LANE",
           "STEPS", "STRINGS", "VOICES", "KEY", "KEY_7", "KEY_TYPES", "ChordType", "ClockFollower", "Event", "Issue", "Meter", "Pattern",
           "PatternError", "Performer", "PerformerState", "Voicing", "VoicingError", "build_voicing", "check_pattern",
           "chord_root", "chord_type", "diatonic_chord", "key_type", "lane_key", "lane_order", "parse_pattern", "row_cells", "row_text", "to_data"]
