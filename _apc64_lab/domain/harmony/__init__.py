"""The harmony core: pure, device-independent music theory (contract §2.7 q7, binding).

Pitch-class sets, held notes, chord naming, triads and Tonnetz geometry, interval and neighbour hints, the
circle of fifths and note spelling. Standard library only: no import of _apc64_host, the rest of the lab,
ALSA or FastAPI (a layering test enforces it), so it can move into another project unchanged. Spelling and
chord detection follow the author's MusicCat Explorer (§2.7 a25); its own cases are golden tests.
"""
from .chords import CHORD_TEMPLATES, ChordMatch, chord_label, find_chord_matches
from .circle import circle_order, fifths_index
from .held import HeldNotes
from .spelling import (
    DEGREES, NOTE_DISPLAY, PARENT_KEYS, degree_of, diatonic_chords, diatonic_scale, note_label, parse_pitch_class,
    pc_name,
)
from .state import Harmony, HarmonyState, analyse
from .tonnetz import MAJOR, MINOR, Triad, complete_triads, triads_containing
from .trail import ChordTrail

__all__ = [
    "CHORD_TEMPLATES", "ChordMatch", "chord_label", "find_chord_matches", "circle_order", "fifths_index",
    "HeldNotes", "DEGREES", "NOTE_DISPLAY", "PARENT_KEYS", "degree_of", "diatonic_chords", "diatonic_scale",
    "note_label", "parse_pitch_class", "pc_name", "Harmony", "HarmonyState", "analyse", "MAJOR", "MINOR",
    "Triad", "complete_triads", "triads_containing", "ChordTrail",
]
