"""The performer in the lab (contract 2 §2.10): the layout's performer block, the pattern files with their lines, and
PerformerService over a fake timer and a recording host link (what goes to the target, the OLED flashes)."""
from pathlib import Path

import pytest

from _apc64_host.application.ports import HostPorts
from _apc64_host.domain.controls import Transport, TransportName
from _apc64_host.domain.effects import PlayedMidi, UnitView
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.layout import Layer, ModuleAction, UnitPortRole
from _apc64_host.domain.midi import ControlChange, NoteOff, NoteOn, PolyAftertouch
from _apc64_host.infrastructure.memory_ports import MemoryPorts
from _apc64_host.notation.compiler import compile_text
from _apc64_lab.application.pattern_library import PatternLibrary, pattern_json
from _apc64_lab.application.performer_service import (
    CONTROLS, NO_CONTROLS, TAKEN, PerformerService, PerformerUnavailable,
)
from _apc64_lab.application.ports import HostLink
from _apc64_lab.application.registry import GeneratorRegistry
from _apc64_lab.application.section_compiler import LabSectionCompiler
from _apc64_lab.infrastructure.pattern_files import PatternFiles
from _apc64_lab.infrastructure.plugin_discovery import PluginDiscovery

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = GeneratorRegistry(PluginDiscovery()).load()
PATTERNS = PatternLibrary(PatternFiles(ROOT / "patterns"))
MPC = "MPC Live III MIDI 1"
GUITAR = """name: Guitar picker
lab:
  generator: guitar
  tuning: e-standard
  performer:
    pattern: arpeggio-manual-bass
    tempo: 100
"""
STEP = 0.3                                 # one 1/8 step at 100 BPM


def compiled(text, file="guitar-picker.yaml", patterns=PATTERNS):
    compiler = LabSectionCompiler(REGISTRY.generators, REGISTRY.schemes, patterns=patterns.names)
    return compile_text(text, file, [MPC], sections={"lab": compiler})


def messages(result):
    return [i.message() for i in (*result.issues, *result.warnings)]


# --- the performer block -------------------------------------------------------------------------------------
def test_a_performer_block_compiles_and_binds_play_and_stop():
    result = compiled(GUITAR)
    assert result.valid, messages(result)
    settings = result.layout.section("lab").performer
    assert (settings.pattern, settings.latch, settings.bpm, settings.clock, settings.play) == (
        "arpeggio-manual-bass", False, 100.0, None, None)
    base = result.layout.page(1).layers[Layer.BASE]
    assert base[Transport(TransportName.PLAY)].module_action == ModuleAction("lab", "performer_latch")
    assert base[Transport(TransportName.STOP)].module_action == ModuleAction("lab", "performer_stop")
    plain = compiled(GUITAR.split("  performer:")[0])
    assert Transport(TransportName.PLAY) not in plain.layout.page(1).layers[Layer.BASE]


@pytest.mark.parametrize("block,expected", [
    ("    pattern: travs\n", 'guitar-picker.yaml line 6: no pattern "travs"; did you mean travis? available: '
                           'arpeggio, arpeggio-manual-bass, strum, travis, waltz'),
    ("    latch: maybe\n    pattern: travis\n", "guitar-picker.yaml line 6, latch: 'maybe' is not on or off; write 'latch: on' or 'latch: off'"),
    ("    pattern: travis\n    tempo: 400\n", "guitar-picker.yaml line 7: '400' is not a tempo; write a BPM 20–300 (quarter notes a minute), or 'tempo: clock' with 'clock: <MIDI input>'"),
    ("    pattern: travis\n    tempo: clock\n", "guitar-picker.yaml line 7: tempo: clock names no clock input; add 'clock: <MIDI input>', e.g. the MPC's port as 'apc64 ports' lists it"),
    ("    pattern: travis\n    play: some\n", "guitar-picker.yaml line 7, play: 'some' is not all or pressed; all: every lane plays at its hits, an unpressed string open; pressed: only pressed strings play; leave it out for the pattern's own"),
    ("    pattern: travis\n    swing: 60\n", "guitar-picker.yaml line 7, performer: unknown key 'swing'; the performer block takes pattern, latch, play, tempo, clock, addressing, chords, slots"),
    ("    latch: on\n", "guitar-picker.yaml line 5: the performer block names no pattern; add 'pattern: <name>'; available: arpeggio, arpeggio-manual-bass, strum, travis, waltz"),
])
def test_every_refusal_of_the_block_names_its_line_and_a_fix(block, expected):
    result = compiled("name: Guitar picker\nlab:\n  generator: guitar\n  tuning: e-standard\n  performer:\n" + block)
    assert not result.valid and messages(result) == [expected]


def test_strings_addressing_needs_a_string_per_channel_and_play_on_a_page_clashes():
    result = compiled("name: T\nlab:\n  generator: tonnetz\n  performer:\n    pattern: travis\n    addressing: strings\n",
                      "tonnetz-c.yaml")
    assert messages(result) == ["tonnetz-c.yaml line 6, addressing: strings needs a generator that sends each string "
                                "on its own channel (the guitar); write 'addressing: voices' or leave it out"]
    voices = compiled("name: T\nlab:\n  generator: tonnetz\n  performer:\n    pattern: travis\n", "tonnetz-c.yaml")
    assert voices.valid, messages(voices)
    clash = compiled("name: T\ndevices:\n  mpc: MPC Live III MIDI 1\nlab:\n  generator: guitar\n  performer:\n"
                     "    pattern: travis\npages:\n  1:\n    play: cc 118 on mpc\n")
    assert "line 10, play: the lab section's performer toggles the latch with Play; remove this play binding, or the " \
           "performer block" in messages(clash)[0]
    leftover = compiled(GUITAR + "    clock: MPC Live III MIDI 1\n")
    assert leftover.valid and messages(leftover) == [
        "guitar-picker.yaml line 8: the clock input is unused with a BPM; write 'tempo: clock' to follow it, "
        "or remove 'clock:'"]


# --- pattern files -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("pattern_id", PatternFiles(ROOT / "patterns").ids())
def test_every_shipped_pattern_is_valid_without_warnings(pattern_id):
    result = PATTERNS.find(pattern_id)[1]
    assert result.valid and result.issues == (), [i.message() for i in result.issues]
    assert len(result.pattern.name) <= 14
    assert (ROOT / "patterns" / result.file).read_text().startswith("# ")       # commented like the layouts


def test_issues_carry_the_file_line():
    text = "name: Bad\nstep: 1/5\nlength: 8\nlanes:\n  1: x . . .\n  2: . y . . . . . .\n"
    result = PATTERNS.compile_text(text, "bad.yaml")
    assert [i.message() for i in result.errors] == [
        "bad.yaml line 2: '1/5' is not a step; write one of 1/4, 1/8, 1/16, 1/8t, 1/16t",
        "bad.yaml line 5, lane 1: 4 steps; length is 8; write one cell per step: . (rest), x (hit) or X (accent); "
        "spaces and | are ignored",
        "bad.yaml line 6, lane 2: 'y' at step 2 is not a cell; write one cell per step: . (rest), x (hit) or X "
        "(accent); spaces and | are ignored"]
    assert PATTERNS.compile_text("", "e.yaml").errors[0].message() == \
        "e.yaml line 1: the pattern is empty; start with 'name:' and 'lanes:' (docs/performer-format.md)"
    assert PATTERNS.compile_text('{"name": "J", "lanes": {"1": "x . x ."}}', "j.json").valid


def test_the_grid_json_for_the_page():
    pattern_id, pattern = PATTERNS.get("1-2-3 + bass")
    shown = pattern_json(pattern_id, pattern, 6)
    assert pattern_id == "arpeggio-manual-bass" and shown["bar"] == 8 and shown["play"] == "all"
    assert [(l["lane"], l["manual"], l["cells"]) for l in shown["lanes"]] == [
        (1, False, "...x...x"), (2, False, ".x...x.."), (3, False, "..x...x."), (4, True, ""), (5, True, ""),
        (6, True, ""), ("R", False, "........"), ("A", False, "........")]
    assert shown["data"]["manual"] == [4, 5, 6] and shown["strum"] is None


# --- the service -----------------------------------------------------------------------------------------------
class FakeTimer:
    def __init__(self):
        self.t, self.ticker, self.wakes = 0.0, None, 0

    def now(self):
        return self.t

    def start(self, tick):
        self.ticker = tick

    def wake(self):
        self.wakes += 1

    def stop(self):
        self.ticker = None

    def timing(self):
        return {"ticks": 0}


class Player:
    def __init__(self):
        self.sent = []

    def perform(self, messages, role=UnitPortRole.CUSTOM):
        self.sent += list(messages)


class Publisher:
    def __init__(self):
        self.states = []

    def publish(self, snapshot):
        self.states.append(snapshot)


class Rig:
    def __init__(self, text=GUITAR, patterns=PATTERNS, **extra):
        self.timer, self.player, self.publisher, self.flashes = FakeTimer(), Player(), Publisher(), []
        self.inputs = MemoryPorts([MPC])
        self.patterns = patterns
        link = HostLink(HostPorts(player=self.player, inputs=self.inputs))
        self.service = PerformerService(patterns, link, self.publisher, self.timer, REGISTRY.generators,
                                        flash=self.flashes.append, **extra)
        self.service.start()
        self.load(text)

    def load(self, text):
        result = compiled(text, patterns=self.patterns)
        assert result.valid, messages(result)
        self.service.on_layout_loaded(result.layout, result.layout.section("lab"))

    def play(self, message):
        return self.service.take_played(PlayedMidi(UnitPortRole.CUSTOM, message))

    def until(self, t):
        """The timer's ticks up to t, as the thread would make them."""
        due = self.timer.ticker(self.timer.t)
        while due is not None and due <= t:
            self.timer.t = due
            due = self.timer.ticker(due)
        self.timer.t = t

    def sent(self):
        out, self.player.sent = self.player.sent, []
        return out


def test_a_layout_with_a_block_plays_its_pattern_on_the_strings_unpressed_ones_open():
    rig = Rig()
    state = rig.service.state()
    assert (state["available"], state["enabled"], state["addressing"], state["from_layout"]) == (True, True, "strings", True)
    assert [l["label"] for l in state["lanes"]] == ["1 E", "2 B", "3 G", "4 D", "5 A", "6 E", "R root", "A alt bass"]
    assert state["pattern"]["id"] == "arpeggio-manual-bass" and state["controls"] == CONTROLS and state["play"] == "all"
    assert rig.play(NoteOn(3, 57, 100)) == TAKEN               # A on string 3 (fret 2): the pattern starts
    assert rig.sent() == [] and rig.service.state()["running"]  # step 1 of 1-2-3 has no hit
    rig.until(3 * STEP + 0.01)
    assert rig.sent() == [NoteOn(2, 59, 79), NoteOn(3, 57, 79), NoteOn(1, 64, 79)]   # 2 open, 3, 1 open; all ring
    assert rig.service.state()["step"] == 4


def test_manual_strings_pass_straight_through_with_their_aftertouch():
    rig = Rig()
    assert rig.play(NoteOn(5, 48, 90)) == TAKEN               # C on string 5 (fret 3)
    assert rig.play(PolyAftertouch(5, 48, 40)) == TAKEN
    assert rig.play(NoteOff(5, 48)) == TAKEN
    assert rig.sent() == [NoteOn(5, 48, 90), PolyAftertouch(5, 48, 40), NoteOff(5, 48)]
    assert not rig.service.state()["running"]                # a manual string never starts the pattern
    assert rig.play(ControlChange(1, 16, 40)) is None           # a strip stays the router's


def test_a_release_pressed_before_the_performer_played_goes_to_the_router():
    rig = Rig()
    assert rig.play(NoteOff(2, 60)) is None and rig.play(PolyAftertouch(2, 60, 3)) is None


def test_a_window_shift_ends_held_notes_and_takes_their_later_release():
    rig = Rig()
    rig.play(NoteOn(3, 57, 100))
    rig.play(NoteOn(5, 48, 90))
    rig.sent()
    rig.service.end_held([57, 48])
    assert rig.sent() == [NoteOff(5, 48)]                    # the manual note now; the pattern's at its grace end
    assert rig.play(NoteOff(3, 57)) == TAKEN and rig.play(NoteOff(5, 48)) == TAKEN and rig.sent() == []
    rig.until(2.0)
    assert not rig.service.state()["running"]


def test_play_toggles_the_latch_and_stop_stops_with_a_flash_each():
    rig = Rig()
    rig.service.play_button()
    assert rig.service.state()["latch"] and rig.flashes == ["Latch on"]
    rig.play(NoteOn(3, 57, 100))
    rig.play(NoteOff(3, 57))
    rig.until(5.0)
    assert rig.service.state()["running"]                    # latched
    rig.service.stop_button()
    assert not rig.service.state()["running"] and rig.flashes[-1] == "Stopped"
    rig.service.play_button()
    assert rig.flashes[-1] == "Latch off"


def test_the_session_settings_change_live_and_are_checked():
    rig = Rig()
    answer = rig.service.change(pattern="Travis pick", bpm=96, play="pressed", latch=True)
    assert answer["message"] == "pattern Travis pick; play pressed; tempo 96 BPM; latch on"
    assert (answer["pattern"]["id"], answer["tempo"], answer["play"], answer["play_override"]) == (
        "travis", {"source": "bpm", "bpm": 96.0, "clock": None, "measured": None, "following": None, "stopped": False,
                   "heard": []}, "pressed", "pressed")
    assert rig.flashes[-1] == "Travis pick"
    assert rig.service.change(play=None, play_given=True)["play"] == "all"
    with pytest.raises(DomainInvariantError) as error:
        rig.service.change(pattern="polka")
    assert (error.value.problem, error.value.fix) == (
        'no pattern "polka"', "available: arpeggio, arpeggio-manual-bass, strum, travis, waltz")
    with pytest.raises(DomainInvariantError):
        rig.service.change(bpm=500)
    off = rig.service.change(enabled=False)
    assert not off["enabled"] and rig.play(NoteOn(3, 57, 100)) is None and rig.flashes[-1] == "Performer off"


def test_a_layout_without_a_block_is_off_until_turned_on_and_leaves_play_and_stop_alone():
    rig = Rig(GUITAR.split("  performer:")[0])
    state = rig.service.state()
    assert not state["enabled"] and state["controls"] == NO_CONTROLS and state["pattern"]["id"] == "arpeggio"
    assert rig.play(NoteOn(3, 57, 100)) is None
    rig.service.change(enabled=True)
    assert rig.play(NoteOn(3, 57, 100)) == TAKEN


def test_a_reload_of_the_same_block_keeps_the_session_and_another_layout_resets_it():
    rig = Rig()
    rig.service.change(latch=True, bpm=120)
    rig.load(GUITAR.replace("tuning: e-standard", "tuning: drop-d"))          # a tuning tweak: same block
    assert rig.service.state()["latch"] and rig.service.state()["tempo"]["bpm"] == 120.0
    rig.load(GUITAR.replace("tempo: 100", "tempo: 90"))                       # the block changed: its settings
    assert not rig.service.state()["latch"] and rig.service.state()["tempo"]["bpm"] == 90.0


def test_leaving_custom_view_or_the_generated_layout_ends_every_note():
    rig = Rig()
    rig.play(NoteOn(5, 48, 90))
    rig.sent()
    rig.service.on_view(UnitView.SESSION)
    assert rig.sent() == [NoteOff(5, 48)]
    rig.play(NoteOn(5, 48, 90))
    rig.sent()
    rig.service.on_layout_loaded(object(), None)
    assert rig.sent() == [NoteOff(5, 48)] and not rig.service.state()["available"]
    with pytest.raises(PerformerUnavailable):
        rig.service.change(latch=True)


def test_the_tempo_follows_a_midi_clock_input():
    rig = Rig()
    answer = rig.service.change(clock=MPC)
    assert answer["tempo"]["source"] == "clock" and answer["tempo"]["clock"] == MPC
    for k in range(30):
        rig.inputs.deliver_realtime(MPC, 0xF8, k * 60 / 120 / 24)
    state = rig.service.state()
    assert state["tempo"]["measured"] == 120.0 and state["tempo"]["bpm"] == 120.0
    rig.service.change(bpm=100)                               # back to the internal tempo: the clock is let go
    assert rig.inputs.deliver_realtime(MPC, 0xF8, 2.0) == 0


def clock(rig, port, bpm, start, beats, jitter=0.0, seed=0):
    """A MIDI clock on `port` for `beats` quarter notes from `start` (each tick ±jitter s); answers the end time."""
    import random
    rng, interval = random.Random(seed), 60.0 / bpm / 24
    for k in range(int(beats * 24)):
        rig.timer.t = start + k * interval
        rig.inputs.deliver_realtime(port, 0xF8, rig.timer.t + rng.uniform(-jitter, jitter))
    return start + int(beats * 24) * interval


def test_a_jittery_clock_sets_the_engines_tempo_only_when_its_held_value_moves():
    rig = Rig()
    rig.service.change(clock=MPC)
    given = []
    real = rig.service._core.set_tempo
    rig.service._core.set_tempo = lambda bpm, t: (given.append(bpm), real(bpm, t))
    clock(rig, MPC, 125, 0.0, 60, jitter=0.003)                       # 30 s of a USB clock at 125 BPM
    assert abs(rig.service.state()["tempo"]["measured"] - 125) <= 0.2
    assert len(given) <= 8 and len([bpm for bpm in given[1:] if abs(bpm - 125) > 0.2]) <= 2, given


def test_auto_follows_the_first_input_that_sends_a_clock_and_says_when_it_stopped():
    rig = Rig()
    rig.inputs.plug("Midi Through Port-0")
    answer = rig.service.change(clock="auto")
    assert answer["message"] == "tempo from the MIDI clock of the first input that sends one"
    tempo = answer["tempo"]
    assert (tempo["source"], tempo["clock"], tempo["following"], tempo["measured"]) == ("clock", "auto", None, None)
    end = clock(rig, "Midi Through Port-0", 98, 0.0, 2)
    tempo = rig.service.state()["tempo"]
    assert (tempo["following"], tempo["measured"], tempo["bpm"], tempo["heard"]) == (
        "Midi Through Port-0", 98.0, 98.0, ["Midi Through Port-0"])
    clock(rig, MPC, 125, end, 1)                                      # another input: heard, not followed
    tempo = rig.service.state()["tempo"]
    assert tempo["following"] == "Midi Through Port-0" and tempo["heard"] == [MPC, "Midi Through Port-0"]
    rig.inputs.deliver_realtime("Midi Through Port-0", 0xFC, rig.timer.t)   # Stop: the clock followed is gone
    tempo = rig.service.state()["tempo"]
    assert tempo["stopped"] and tempo["measured"] is None and tempo["bpm"] == 98.0   # its tempo is kept
    clock(rig, MPC, 125, rig.timer.t + 0.02, 2)                       # the MPC goes on: followed instead
    tempo = rig.service.state()["tempo"]
    assert (tempo["following"], tempo["measured"], tempo["stopped"]) == (MPC, 125.0, False)
    rig.inputs.plug("USB MIDI Interface MIDI 1")                      # a port plugged in later is listened to
    assert "USB MIDI Interface MIDI 1" in rig.service._clock_listeners
    rig.service.change(bpm=100)
    assert rig.service._clock_listeners == {} and rig.service.state()["tempo"]["source"] == "bpm"


def test_a_named_clock_input_that_sends_nothing_is_named_as_followed_and_a_block_may_say_auto():
    rig = Rig()
    tempo = rig.service.change(clock=MPC)["tempo"]
    assert (tempo["following"], tempo["measured"], tempo["stopped"], tempo["heard"]) == (MPC, None, False, [])
    rig.load(GUITAR.replace("tempo: 100", "tempo: clock\n    clock: auto"))
    assert rig.service.state()["tempo"]["clock"] == "auto" and set(rig.service._clock_listeners) == {MPC}
