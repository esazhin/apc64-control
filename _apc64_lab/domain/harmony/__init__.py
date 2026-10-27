"""The harmony core: pure, device-independent music theory (contract §2.7 q7, binding).

Pitch-class sets, held notes, chord naming, triads and Tonnetz geometry, interval and neighbour hints, the
circle of fifths with its keys, the scale library and note spelling. Standard library only: no import of _apc64_host, the rest of the lab,
ALSA or FastAPI (a layering test enforces it), so it can move into another project unchanged. Spelling and
chord detection follow the author's MusicCat Explorer (§2.7 a25); its own cases are golden tests.
"""
from .chords import CHORD_TEMPLATES, ChordMatch, SpelledChord, chord_label, find_chord_matches, spell_chord
from .circle import CircleKey, circle_keys, circle_order, fifths_index
from .held import HeldNotes
from .spelling import (
    DEGREES, NOTE_DISPLAY, PARENT_KEYS, degree_of, diatonic_chords, diatonic_scale, note_label, parse_pitch_class,
    pc_name,
)
from .scales import (
    MODE_NAMES, MODES_BY_BRIGHTNESS, SCALE_KEYS, SCALES, Scale, closest_scale, find_scale, mode_steps, spell_scale,
)
from .state import Harmony, HarmonyState, Spelling, analyse, spell_held
from .tonnetz import MAJOR, MINOR, Triad, complete_triads, triads_containing
from .trail import ChordTrail, TrailEntry

__all__ = [
    "CHORD_TEMPLATES", "ChordMatch", "SpelledChord", "chord_label", "find_chord_matches", "spell_chord", "CircleKey", "circle_keys", "circle_order",
    "fifths_index", "MODE_NAMES", "MODES_BY_BRIGHTNESS", "SCALE_KEYS", "SCALES", "Scale", "closest_scale",
    "find_scale", "mode_steps", "spell_scale",
    "HeldNotes", "DEGREES", "NOTE_DISPLAY", "PARENT_KEYS", "degree_of", "diatonic_chords", "diatonic_scale",
    "note_label", "parse_pitch_class", "pc_name", "Harmony", "HarmonyState", "Spelling", "analyse", "spell_held", "MAJOR", "MINOR",
    "Triad", "complete_triads", "triads_containing", "ChordTrail", "TrailEntry",
]
