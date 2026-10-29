"""Chord types and pattern slots (contract 2 §2.10, Phase 2): the control pads on the guitar's free rows, Shift + pad
on 7 and 8 strings, a single root voiced on the strings, several notes fretted, the harmony views shown the voicing."""
import pytest

from _apc64_host.application.ports import HostPorts
from _apc64_host.domain.effects import PlayedMidi
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.layout import UnitPortRole
from _apc64_host.domain.midi import NoteOff, NoteOn, PolyAftertouch
from _apc64_host.infrastructure.memory_ports import MemoryPorts
from _apc64_lab.application.ports import TAKEN, TAKEN_CONTROL, TAKEN_VOICED, HostLink
from _apc64_lab.application.performer_service import PerformerService
from _apc64_lab.application.test_performer import MPC, PATTERNS, REGISTRY, STEP, FakeTimer, Player, Publisher, compiled
from _apc64_lab.domain.lab_section import compile_lab_section
from _apc64_lab.domain.performer_pads import (
    CONTROL_CHANNEL, SLOT_ON, SLOT_REST, TYPE_ON, TYPE_REST, control_pads, control_rows, with_controls,
)

PICKER = """name: Guitar picker
lab:
  generator: guitar
  tuning: {tuning}
  performer:
    pattern: travis
    tempo: 100
    chords: [maj, min, 7, maj7, m7, sus2, sus4, dim]
    slots: [arpeggio-manual-bass, travis, ~, strum]
"""


class Nav:
    shift = False


class Views:
    def __init__(self):
        self.nav = Nav()


class ChordRig:
    def __init__(self, tuning="e-standard", window=0):
        self.timer, self.player, self.publisher = FakeTimer(), Player(), Publisher()
        self.flashes, self.repaints, self.shown, self.views = [], [], [], Views()
        link = HostLink(HostPorts(player=self.player, inputs=MemoryPorts([MPC]), views=self.views))
        self.service = PerformerService(PATTERNS, link, self.publisher, self.timer, REGISTRY.generators,
                                        flash=self.flashes.append, repaint=lambda: self.repaints.append(1),
                                        window=lambda layout_id: window, show=self.shown.append)
        self.service.start()
        result = compiled(PICKER.format(tuning=tuning))
        assert result.valid, [i.message() for i in result.issues]
        self.definition = result.layout.section("lab")
        self.service.on_layout_loaded(result.layout, self.definition)

    def play(self, message):
        return self.service.take_played(PlayedMidi(UnitPortRole.CUSTOM, message))

    def held(self):
        return self.service._core.pressed()

    def sent(self):
        out, self.player.sent = self.player.sent, []
        return out


def test_the_free_rows_hold_the_chord_types_and_the_slots_on_channel_16():
    rig = ChordRig()
    pads = rig.service.control_pads(rig.definition)
    top = {i - 56: pad for i, (pad, _) in pads.items() if i >= 56}
    bottom = {i: pad for i, (pad, _) in pads.items() if i < 8}
    assert sorted(top) == list(range(8)) and sorted(bottom) == [0, 1, 3]                # slot 3 is empty: silent
    assert {pad.channel for pad, _ in pads.values()} == {CONTROL_CHANNEL} and not any(p.aftertouch for p, _ in pads.values())
    assert [top[c].note for c in range(8)] == list(range(8)) and [bottom[c].note for c in (0, 1, 3)] == [8, 9, 11]
    assert top[0].rest == TYPE_REST and bottom[1].rest == SLOT_ON and bottom[0].rest == SLOT_REST   # travis plays
    assert [label for i, (_, label) in sorted(pads.items()) if i < 8] == ["1-2-3 + bass", "Travis pick", "Strum d-u"]
    assert control_rows(7) == {"slots": 7} and control_rows(8) == {}
    state = rig.service.state()
    assert state["slot"] == 2 and state["chords"]["selected"] is None
    assert state["pads"] == "top row: chord types · bottom row: pattern slots"


def test_a_type_pad_latches_its_chord_type_and_the_same_pad_again_lets_go():
    rig = ChordRig()
    assert rig.play(NoteOn(CONTROL_CHANNEL, 4, 100)) == TAKEN_CONTROL                # m7
    assert rig.play(NoteOff(CONTROL_CHANNEL, 4)) == TAKEN_CONTROL
    assert rig.service.state()["chords"]["selected"] == "m7" and rig.flashes[-1] == "Type m7" and rig.repaints
    lit = rig.service.control_pads(rig.definition)
    assert lit[56 + 4][0].rest == TYPE_ON and lit[56][0].rest == TYPE_REST
    rig.play(NoteOn(CONTROL_CHANNEL, 4, 100))
    assert rig.service.state()["chords"]["selected"] is None and rig.flashes[-1] == "Type off"
    assert rig.sent() == []                                                         # nothing goes to the target


def test_one_root_is_voiced_on_the_strings_and_plays_the_pattern_from_that_press():
    rig = ChordRig()
    rig.service.select_type("min")
    assert rig.play(NoteOn(5, 45, 100)) == TAKEN_VOICED                            # A on string 5: Am x02210
    assert rig.held() == ((1, 64), (2, 60), (3, 57), (4, 52), (5, 45))
    state = rig.service.state()
    assert state["running"] and (state["voicing"]["symbol"], state["voicing"]["shape"]) == ("Am", "x02210")
    assert rig.flashes[-1] == "Am" and rig.shown[-1] == ((1, 64), (2, 60), (3, 57), (4, 52), (5, 45))
    assert [(m.channel, m.note) for m in rig.sent() if isinstance(m, NoteOn)] == [(1, 64), (5, 45)]   # 1 and R
    assert rig.service._core._muted == {6}


def test_a_type_changed_while_the_root_is_held_re_voices_and_several_notes_are_fretted():
    rig = ChordRig()
    rig.service.select_type("min")
    rig.play(NoteOn(5, 45, 100))
    rig.sent()
    rig.service.select_type("m7")                                                   # Am7 x02010: string 3 A → G
    assert rig.held() == ((1, 64), (2, 60), (3, 55), (4, 52), (5, 45)) and rig.flashes[-1] == "Am7"
    rig.timer.t = STEP * 1.2                                                        # swing 54: a bit later
    rig.service.tick(rig.timer.t)                                                   # step 2: string 3 plays the G
    assert [(m.channel, m.note) for m in rig.sent() if isinstance(m, NoteOn)] == [(3, 55)]
    assert rig.play(NoteOn(2, 61, 90)) == TAKEN                                     # a second note: fretted
    assert rig.held() == ((2, 61), (5, 45)) and rig.service.state()["voicing"] is None
    assert rig.shown[-1] == ((5, 45),)                                              # the root still shown (not counted)
    assert rig.play(NoteOff(2, 61)) == TAKEN                                        # one note again: voiced again
    assert rig.service.state()["voicing"]["symbol"] == "Am7"
    assert rig.play(NoteOff(5, 45)) == TAKEN_VOICED and rig.held() == () and rig.shown[-1] == ()
    rig.service.select_type(None)
    rig.play(NoteOn(5, 48, 100))
    assert rig.held() == ((5, 48),)                                                 # off: what you fret


def test_manual_strings_stay_manual_and_a_slot_pad_chooses_its_pattern():
    rig = ChordRig()
    assert rig.play(NoteOn(CONTROL_CHANNEL, 8, 100)) == TAKEN_CONTROL               # slot 1: 1-2-3 + bass
    state = rig.service.state()
    assert state["pattern"]["id"] == "arpeggio-manual-bass" and state["slot"] == 1 and rig.flashes[-1] == "1-2-3 + bass"
    assert rig.play(NoteOn(CONTROL_CHANNEL, 10, 100)) == TAKEN_CONTROL              # slot 3 is empty: nothing
    assert rig.service.state()["slot"] == 1
    rig.service.select_type("maj")
    assert rig.play(NoteOn(5, 48, 90)) == TAKEN                                     # a manual string: through, no root
    assert rig.sent() == [NoteOn(5, 48, 90)]
    assert rig.play(NoteOn(3, 55, 100)) == TAKEN_VOICED                             # G on string 3: xxx003
    assert rig.held() == ((1, 67), (2, 59), (3, 55), (5, 48))
    with pytest.raises(DomainInvariantError):
        rig.service.select_slot(3)
    with pytest.raises(DomainInvariantError):
        rig.service.select_type("polka")


def test_shift_and_a_pad_on_eight_strings_choose_a_type_by_column_and_a_slot_on_the_top_row():
    rig = ChordRig("fs-standard-8", window=2)
    assert rig.service.control_pads(rig.definition) == {}
    assert rig.service.state()["pads"] == ("Shift + a pad: the chord type of its column · Shift + a top-row pad: "
                                           "the pattern slot")
    rig.views.nav.shift = True
    assert rig.play(NoteOn(3, 55 + 2 + 4, 100)) == TAKEN_CONTROL                    # string 3, column 5: m7
    assert rig.service.state()["chords"]["selected"] == "m7"
    rig.views.nav.shift = False                                                     # Shift let go first
    assert rig.play(NoteOff(3, 61)) == TAKEN_CONTROL and rig.sent() == []           # its release is taken too
    rig.views.nav.shift = True
    assert rig.play(NoteOn(1, 64 + 2 + 3, 100)) == TAKEN_CONTROL                    # the top row, column 4: slot 4
    assert rig.service.state()["pattern"]["id"] == "strum"
    rig.views.nav.shift = False
    assert rig.play(NoteOn(4, 52, 100)) == TAKEN_VOICED                             # without Shift: a root (m7)


def test_seven_strings_have_the_slots_on_the_top_row_and_the_types_on_shift():
    rig = ChordRig("b-standard-7")
    pads = rig.service.control_pads(rig.definition)
    assert sorted(pads) == [56, 57, 59] and rig.play(NoteOn(CONTROL_CHANNEL, 9, 100)) == TAKEN_CONTROL
    rig.views.nav.shift = True
    assert rig.play(NoteOn(7, 35, 100)) == TAKEN_CONTROL and rig.service.state()["chords"]["selected"] == "maj"


def test_control_pads_overlay_the_grid_and_a_string_on_channel_16_is_refused():
    grid = compiled(PICKER.format(tuning="e-standard")).layout.section("lab").grid(REGISTRY.generators(),
                                                                                    REGISTRY.schemes())
    painted = with_controls(grid, {i: pad for i, pad in control_pads(6, ["maj"], ["travis"], "maj", 0).items()})
    assert painted.pads[56].channel == CONTROL_CHANNEL and painted.pads[0].note == 8 and painted.pads[8] == grid.pads[8]

    from _apc64_lab.domain.generators import Neck, NeckString, ParamKind, ParamSpec

    class Sixteen:
        name = "sixteen"
        params = (ParamSpec("base", ParamKind.NOTE, 40, 0, 127),)

        def notes(self, params):
            return tuple(40 + x if r == 1 else None for r in range(8) for x in range(8))

        def channels(self, params):
            return tuple(16 if r == 1 else None for r in range(8) for x in range(8))

        def neck(self, params):
            return Neck((NeckString(1, 40, 16),), 24)
    from _apc64_host.notation.compiler import compile_text
    from _apc64_lab.application.section_compiler import LabSectionCompiler
    compiler = LabSectionCompiler(lambda: {"sixteen": Sixteen()}, REGISTRY.schemes, patterns=PATTERNS.names)
    result = compile_text("name: S\nlab:\n  generator: sixteen\n  performer:\n    pattern: travis\n", "s.yaml",
                          sections={"lab": compiler})
    assert [i.message() for i in result.issues] == [
        "s.yaml line 4: string 1 sends on channel 16, the performer's control pads' channel; give the "
        "strings channels 1–15"]



def test_a_block_may_offer_the_keys_own_chords_and_is_warned_without_a_key():
    keyed = compiled("name: K\nlab:\n  generator: guitar\n  scheme: scale\n  scale: major\n  root: C\n  performer:\n"
                     "    pattern: travis\n    chords: [key, Key 7, maj]\n")
    assert keyed.valid and keyed.warnings == () and keyed.layout.section("lab").performer.chords == ("key", "key 7", "maj")
    plain = compiled("name: K\nlab:\n  generator: guitar\n  performer:\n    pattern: travis\n    chords: [key, maj]\n")
    assert plain.valid and [w.message() for w in plain.warnings] == [
        "guitar-picker.yaml line 6, chords: key and key 7 need a key: this scheme lights no scale; write 'scheme: scale' with "
        "'scale:' and 'root:', or choose a Key on the page"]
