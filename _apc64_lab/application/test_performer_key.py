"""Chords in key (contract 2 §2.10, 2026-10-29): the layout's scale is the key; the chord types 'key' and 'key 7'
voice the key's own triad and seventh from the root pressed, an off-key root plays nothing, fretted playing is as
before, and the preset guitar-picker-key.yaml lights its pads in key."""
from pathlib import Path

import pytest

from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.midi import NoteOff, NoteOn
from _apc64_lab.application.ports import TAKEN, TAKEN_VOICED
from _apc64_lab.application.test_performer import REGISTRY, compiled
from _apc64_lab.application.test_performer_chords import PICKER, ChordRig
from _apc64_lab.domain.pads import PadPos
from _apc64_lab.generators.scale import OUT_OF_SCALE

ROOT = Path(__file__).resolve().parents[2]
PRESET = (ROOT / "layouts" / "guitar-picker-key.yaml").read_text()


class KeyRig(ChordRig):
    """The chord rig on the key preset, its key handed over as the session hands it (set_key)."""

    def __init__(self, text=PRESET):
        super().__init__()
        result = compiled(text)
        assert result.valid and result.warnings == (), [i.message() for i in (*result.issues, *result.warnings)]
        self.definition = result.layout.section("lab")
        self.service.on_layout_loaded(result.layout, self.definition)
        self.key(self.definition.overlay(REGISTRY.schemes()))

    def key(self, overlay):
        self.service.set_key(self.service._layout_id, overlay)


def test_the_preset_is_the_picker_in_c_major_with_the_keys_chords_first_and_its_pads_lit_in_key():
    rig = KeyRig()
    settings = rig.definition.performer
    assert settings.chords == ("key", "key 7", "maj", "min", "7", "m7", "sus4", "dim")
    overlay = rig.definition.overlay(REGISTRY.schemes())
    assert (overlay.key, overlay.root) == ("major", 0)
    grid = rig.definition.grid(REGISTRY.generators(), REGISTRY.schemes())
    assert grid.at(PadPos(2, 3)).rest == OUT_OF_SCALE                      # F♯ on the low E: out of key, dark
    assert grid.at(PadPos(2, 4)).rest != OUT_OF_SCALE                      # G (fret 3): in key, lit
    assert rig.service.state()["key"] == {"tonic": "C", "scale": "major", "name": "Major (Ionian)",
                                          "pcs": [0, 2, 4, 5, 7, 9, 11], "chords": True}
    assert (ROOT / "layouts" / "guitar-picker.yaml").read_text().count("scheme: fifths") == 1   # unchanged


@pytest.mark.parametrize("kind,root,string,symbol", [
    ("key", 50, 5, "Dm"), ("key 7", 50, 5, "Dm7"), ("key", 48, 5, "C"), ("key 7", 43, 6, "G7"),
    ("key 7", 47, 5, "Bm7b5"), ("key", 47, 5, "Bdim"), ("key 7", 52, 4, "Em7"),
])
def test_a_root_in_key_plays_the_keys_own_chord_from_it(kind, root, string, symbol):
    rig = KeyRig()
    rig.service.select_type(kind)
    assert rig.play(NoteOn(string, root, 100)) == TAKEN_VOICED
    assert rig.service.state()["voicing"]["symbol"] == symbol and rig.flashes[-1] == symbol
    assert rig.held() and rig.service.state()["running"]


def test_an_off_key_root_plays_nothing_and_two_notes_are_fretted_as_before():
    rig = KeyRig()
    rig.service.select_type("key")
    assert rig.play(NoteOn(5, 49, 100)) == TAKEN_VOICED                    # C# in C major: strict, nothing
    assert rig.held() == () and rig.sent() == [] and rig.service.state()["voicing"] is None
    assert not rig.service.state()["running"] and rig.shown[-1] == ()
    assert rig.play(NoteOn(3, 56, 90)) == TAKEN                            # a second note: fretted, as played
    assert rig.held() == ((3, 56), (5, 49))
    rig.play(NoteOff(3, 56))
    assert rig.held() == ()                                                # one off-key note again: nothing
    rig.play(NoteOff(5, 49))
    rig.service.select_type(None)
    rig.play(NoteOn(5, 49, 100))
    assert rig.held() == ((5, 49),)                                        # type off: what you fret plays


def test_without_a_key_the_keys_chords_are_refused_and_a_key_taken_away_lets_go_of_them():
    rig = ChordRig()                                                       # guitar-picker: scheme fifths, no key
    with pytest.raises(DomainInvariantError) as refused:
        rig.service.select_type("key")
    assert (refused.value.problem, refused.value.fix) == (
        "no key", "choose a Key on the page, or a layout with 'scheme: scale' (its scale and root)")
    keyed = KeyRig()
    keyed.service.select_type("key 7")
    keyed.key(None)                                                        # the page's Key: none
    state = keyed.service.state()
    assert state["chords"]["selected"] is None and state["key"] is None
    pentatonic = compiled(PRESET.replace("scale: major", "scale: major-pentatonic")).layout.section("lab")
    keyed.key(pentatonic.overlay(REGISTRY.schemes()))
    assert keyed.service.state()["key"]["chords"] is False
    with pytest.raises(DomainInvariantError) as five:
        keyed.service.select_type("key")
    assert five.value.problem == "C major pentatonic has 5 notes"


def test_a_changed_key_revoices_the_root_held():
    rig = KeyRig()
    rig.service.select_type("key")
    rig.play(NoteOn(5, 50, 100))                                           # D in C major: Dm
    dorian = compiled(PRESET.replace("scale: major", "scale: mixolydian").replace("root: C", "root: D"))
    rig.key(dorian.layout.section("lab").overlay(REGISTRY.schemes()))       # D Mixolydian: D is the tonic, D major
    assert rig.service.state()["voicing"]["symbol"] == "D" and rig.flashes[-1] == "D"


def test_the_type_pads_of_the_preset_name_the_keys_chords_and_say_when_there_is_no_key():
    from _apc64_lab.domain.performer_pads import CONTROL_CHANNEL
    rig = KeyRig()
    labels = [label for i, (_, label) in sorted(rig.service.control_pads(rig.definition).items()) if i >= 56]
    assert labels == ["key", "key 7", "maj", "min", "7", "m7", "sus4", "dim"]
    rig.key(None)
    rig.play(NoteOn(CONTROL_CHANNEL, 0, 100))                              # the 'key' pad without a key
    assert rig.flashes[-1] == "No key" and rig.service.state()["chords"]["selected"] is None
