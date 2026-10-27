from pathlib import Path

from _apc64_host.application.conftest import MemorySource, RecordingFeedback
from _apc64_host.application.learn import CAPTURED, PASS, LearnKind, LearnMode, LearnService, LearnOk, UnknownPort
from _apc64_host.application.tweaks import Saved, TweakService
from _apc64_host.domain.controls import PadPos, SceneButton, Shift, Strip, StripTouch, TrackButton
from _apc64_host.domain.layout import ContentHash, Layer, NavState, TweakField
from _apc64_host.domain.midi import ControlChange, NoteOff, NoteOn, PitchBend, PolyAftertouch
from _apc64_host.notation.compiler import compile_text

JAM = (Path(__file__).resolve().parents[2] / "layouts" / "jam.yaml").read_text()
LAYOUT = compile_text(JAM, "jam.yaml").layout


class Tweaks:
    def __init__(self):
        self.requests = []

    def current_hash(self, layout):
        return ContentHash.of(JAM)

    def apply(self, request):
        self.requests.append(request)
        return Saved(ContentHash.of("new"))


def service(nav=NavState("jam", 1, 1, False), tweaks=None):
    feedback = RecordingFeedback()
    learn = LearnService(tweaks or Tweaks(), feedback, context=lambda: (LAYOUT, nav))
    return learn, feedback


def test_touch_learn_selects_the_control_and_captures_the_press():   # A132
    learn, _ = service()
    seen = []
    learn.subscribe(seen.append)
    assert learn.intercept(TrackButton(3)) == PASS            # learn is off
    assert learn.set_mode(LearnMode.touch()) == LearnOk(learn.status())
    assert learn.intercept(TrackButton(3)) == CAPTURED
    assert learn.status().selected == TrackButton(3) and learn.status().mode is LearnKind.TOUCH
    assert learn.intercept(StripTouch(4)) == CAPTURED and learn.status().selected == Strip(4)
    assert learn.intercept(SceneButton(2)) == PASS and learn.intercept(Shift()) == PASS   # navigation still works
    assert seen and seen[-1].selected == Strip(4)


def test_midi_learn_saves_the_first_message_from_the_chosen_port_as_one_tweak():   # A133 (s65, s66)
    tweaks = Tweaks()
    learn, feedback = service(tweaks=tweaks)
    learn.set_mode(LearnMode.touch())
    learn.intercept(PadPos(2, 1))
    assert isinstance(learn.set_mode(LearnMode.midi("mpc")), LearnOk)
    assert [s.port for s in feedback.active()] == ["MPC Live III MIDI 1"]
    feedback.deliver("MPC Live III MIDI 1", NoteOff(1, 40))          # not a binding: ignored
    feedback.deliver("MPC Live III MIDI 1", PolyAftertouch(1, 40, 3))
    feedback.deliver("MPC Live III MIDI 1", ControlChange(1, 74, 10))
    feedback.deliver("MPC Live III MIDI 1", ControlChange(1, 75, 10))   # only the first is captured
    [request] = tweaks.requests
    assert (request.layout, request.page, request.layer, request.control, request.field, request.value) == (
        "jam", 1, Layer.BASE, PadPos(2, 1), TweakField.ASSIGNMENT, "cc 74 on mpc ch 1")
    assert request.base_hash == ContentHash.of(JAM)
    assert feedback.active() == [] and learn.status().mode is LearnKind.TOUCH
    assert learn.status().last == "pad r2c1: cc 74 on mpc ch 1 saved"


def test_midi_learn_writes_the_binding_into_the_file():   # A133 end to end through the real tweak service
    source = MemorySource({"jam": JAM})
    learn, feedback = service(tweaks=TweakService(source))
    learn.set_mode(LearnMode.touch())
    learn.intercept(PadPos(2, 1))
    learn.set_mode(LearnMode.midi("MPC Live III MIDI 1"))   # a port name finds its device too
    feedback.deliver("MPC Live III MIDI 1", ControlChange(1, 74, 10))
    new = source.files["jam"]
    assert [line for line in new.splitlines() if line not in JAM.splitlines()] == [
        "    pad r2c1: cc 74 on mpc ch 1 colour red"]
    assert str(compile_text(new, "jam.yaml").layout.page(1).binding(Layer.BASE, PadPos(2, 1)).actions[0].number) == "74"


def test_leaving_midi_learn_before_anything_arrives_changes_nothing():   # A134
    tweaks = Tweaks()
    learn, feedback = service(tweaks=tweaks)
    learn.set_mode(LearnMode.touch())
    learn.intercept(PadPos(2, 1))
    learn.set_mode(LearnMode.midi("mpc"))
    learn.set_mode(LearnMode.off())
    feedback.deliver("MPC Live III MIDI 1", ControlChange(1, 74, 10))
    assert tweaks.requests == [] and feedback.active() == []
    assert learn.status().mode is LearnKind.OFF and learn.status().selected is None


def test_an_unknown_port_is_refused_naming_the_devices():
    learn, feedback = service()
    assert learn.set_mode(LearnMode.midi("nope")) == UnknownPort("nope", ("mpc",))
    assert feedback.active() == [] and learn.status().mode is LearnKind.OFF


def test_strips_learn_into_the_bank_and_notes_and_bends_make_phrases():
    tweaks = Tweaks()
    learn, feedback = service(nav=NavState("jam", 1, 1, True), tweaks=tweaks)
    learn.set_mode(LearnMode.touch())
    learn.intercept(StripTouch(2))
    learn.set_mode(LearnMode.midi("mpc"))
    feedback.deliver("MPC Live III MIDI 1", PitchBend(3, 8192))
    learn.intercept(PadPos(1, 1))
    learn.set_mode(LearnMode.midi("mpc"))
    feedback.deliver("MPC Live III MIDI 1", NoteOn(10, 38, 99))
    strip, pad = tweaks.requests
    assert (strip.bank, strip.page, strip.layer, strip.control, strip.value) == (
        1, None, Layer.SHIFT, Strip(2), "pitchbend on mpc ch 3")
    assert (pad.page, pad.value) == (1, "note 38 on mpc ch 10")
