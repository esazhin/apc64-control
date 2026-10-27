from pathlib import Path

from _apc64_host.application.conftest import Catalog, MemorySource
from _apc64_host.application.tweaks import Invalid, Saved, Stale, TweakService
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.issues import LayoutIssue, Severity, SourceRef
from _apc64_host.domain.layout import ContentHash, Layer, TweakField, TweakRequest
from _apc64_host.notation.compiler import compile_text

JAM = (Path(__file__).resolve().parents[2] / "layouts" / "jam.yaml").read_text()
H = ContentHash.of(JAM)


def request(field, value, control=PadPos(1, 1), base=H, layer=Layer.BASE, page=1):
    return TweakRequest("jam", layer, control, field, value, base, page=page)


def test_an_invalid_channel_is_refused_and_the_file_is_untouched():   # A136
    source = MemorySource({"jam": JAM})
    answer = TweakService(source).apply(request(TweakField.ASSIGNMENT, "note 36 on mpc ch 17"))
    assert isinstance(answer, Invalid)
    assert "channel must be 1–16" in answer.issues[0].message()
    assert source.writes == [] and source.files["jam"] == JAM


def test_a_tweak_against_a_stale_base_is_refused_and_the_agents_version_stays():   # A139
    source = MemorySource({"jam": JAM})
    rewritten = JAM.replace("cc 118", "cc 119")
    source.files["jam"] = rewritten
    answer = TweakService(source).apply(request(TweakField.COLOUR, "green"))
    assert answer == Stale() and answer.message == "layout changed, reload"
    assert source.writes == [] and source.files["jam"] == rewritten


def test_a_colour_tweak_inside_a_range_adds_one_entry_and_keeps_every_other_byte():   # A135 via the service
    source = MemorySource({"jam": JAM})
    answer = TweakService(source).apply(request(TweakField.COLOUR, "blue", control=PadPos(1, 3)))
    assert isinstance(answer, Saved)
    new = source.files["jam"]
    assert answer.hash == ContentHash.of(new)
    added = [line for line in new.splitlines() if line not in JAM.splitlines()]
    assert added == ["    pad r1c3: note 38 on mpc ch 10 colour blue"]
    assert [line for line in JAM.splitlines() if line not in new.splitlines()] == []
    assert compile_text(new, "jam.yaml").valid


def test_the_notation_answering_issues_means_invalid_and_no_write():   # s63 collaboration
    problem = LayoutIssue(Severity.ERROR, SourceRef("jam.yaml", 9), "pad r1c1", "no such thing", "fix it")

    def compile_double(text, file, ports=None):
        class Result:
            valid, issues = False, (problem,)
        return Result()

    source = MemorySource({"jam": JAM})
    service = TweakService(source, compile=compile_double)
    assert service.apply(request(TweakField.LABEL, "Kick")) == Invalid((problem,))
    assert source.writes == []


def test_the_full_compile_checks_ports_from_the_catalog():
    text = JAM.replace("mpc: MPC Live III MIDI 1", "mpc: MIDI 1")
    source = MemorySource({"jam": text})
    service = TweakService(source, catalog=Catalog("MPC Live III MIDI 1", "USB MIDI Interface MIDI 1"))
    answer = service.apply(request(TweakField.LABEL, "Kick", base=ContentHash.of(text)))
    assert isinstance(answer, Invalid) and "write the full name" in answer.issues[0].message()
    assert isinstance(TweakService(source).apply(request(TweakField.LABEL, "Kick", base=ContentHash.of(text))), Saved)


def test_a_tweak_that_changes_nothing_saves_without_writing_and_a_missing_file_is_stale():
    source = MemorySource({"jam": JAM})
    service = TweakService(source)
    assert service.apply(request(TweakField.MODE, "momentary")) == Saved(H)
    assert source.writes == []
    assert service.current_hash("jam") == H and service.current_hash("gone") is None
    assert service.apply(TweakRequest("gone", Layer.BASE, PadPos(1, 1), TweakField.LABEL, "x", H, page=1)) == Stale()
