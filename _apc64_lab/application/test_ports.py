"""T22: the lab application ports. In-memory fakes implement them; the 'lab:' section compiler entry point gives
compile_lab_section's result shape; the lab-wide default note target joins a generated layout unless the layout
routes Custom view itself (§2.7 q2, s4 supplier)."""
import pytest

from _apc64_host.domain.controls import Encoder
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.layout import (
    AftertouchPolicy, ModuleAction, SectionEntry, SectionMap, SectionScalar, UnitPortRole,
)
from _apc64_host.notation.compiler import compile_text
from _apc64_lab.application.conftest import FakeBackups, FakeLibrary, FakeMemory, RecordingPublisher
from _apc64_lab.application.ports import (
    BackupStore, GeneratorSource, HostLink, LabSettingsStore, LabState, LabStatePublisher, LibraryStore,
    MalformedReply, MemorySettings, NotHeld, UnitControl, UnitMemory, WrongFirmware,
)
from _apc64_lab.application.section_compiler import LabSectionCompiler, layout_id_of_file
from _apc64_lab.domain.generators import BUILTIN_GENERATORS, BUILTIN_SCHEMES
from _apc64_lab.domain.lab_section import LAB_MODULE, WINDOW_SHIFT, LabDefinition, compile_lab_section
from _apc64_lab.domain.memory_sysex import Malformed
from _apc64_lab.domain.note_target import NOT_ROUTED_TEXT, NoteTarget

GENERATORS = {g.name: g for g in BUILTIN_GENERATORS}
SCHEMES = {s.name: s for s in BUILTIN_SCHEMES}
TONNETZ_C = "name: Tonnetz C\nlab:\n  generator: tonnetz\n  base: C2\n"
MPC = NoteTarget.parse("MPC Live III MIDI 1 ch 2 aftertouch pass")


class Source:
    def discover(self):
        return []


def compiler(target=None, seen=None):
    return LabSectionCompiler(lambda: GENERATORS, lambda: SCHEMES, target,
                              (lambda layout, d: seen.append((layout, d))) if seen is not None else None)


def test_the_fakes_implement_the_ports():
    memory = FakeMemory()
    assert isinstance(memory, UnitMemory) and isinstance(memory, UnitControl)
    assert isinstance(FakeBackups(), BackupStore) and isinstance(FakeLibrary(), LibraryStore)
    assert isinstance(Source(), GeneratorSource) and isinstance(RecordingPublisher(), LabStatePublisher)
    assert isinstance(MemorySettings(), LabSettingsStore)


def test_memory_faults_carry_the_contract_texts():   # s6.c3, A6, A51, a32
    assert str(NotHeld()) == "take control of the APC64 first"
    assert MalformedReply(Malformed(700, 880)).text("slot 7") == "slot 7 read returned 700 bytes, expected 880"
    assert str(WrongFirmware("1.2.1.7", "1.2.1.6")) == (
        "the APC64 reports firmware 1.2.1.7; memory writes are verified only on 1.2.1.6")


def test_the_section_compiler_gives_compile_lab_sections_result_shape():   # s4.c2
    section = SectionEntry("lab", 2, SectionMap((SectionEntry("generator", 3, SectionScalar("tonnetz", 3)),
                                                 SectionEntry("base", 4, SectionScalar("C2", 4))), 3))
    seen = []
    ours = compiler(seen=seen).compile(section, "tonnetz-c.yaml", {})
    domain = compile_lab_section(section, "tonnetz-c.yaml", {}, GENERATORS, SCHEMES)
    assert ours == domain and isinstance(ours.value, LabDefinition)
    assert ours.bindings[Encoder()].module_action == ModuleAction(LAB_MODULE, WINDOW_SHIFT)
    assert ours.routing == {} and ours.devices == {}
    assert seen == [("tonnetz-c", ours.value)] and layout_id_of_file("layouts/tonnetz-c.yaml") == "tonnetz-c"


def test_an_invalid_section_is_reported_and_not_indexed():   # A11 through the entry point
    seen = []
    result = compile_text(TONNETZ_C.replace("tonnetz", "tonetz"), "tonnetz-c.yaml",
                          sections={"lab": compiler(MPC, seen)})
    assert not result.valid and seen == []
    assert [i.message() for i in result.issues] == [
        'tonnetz-c.yaml line 3: no generator "tonetz"; available: isomorphic, tonnetz']


def test_the_default_target_routes_custom_view_of_a_generated_layout():   # §2.7 q2
    layout = compile_text(TONNETZ_C, "tonnetz-c.yaml", sections={"lab": compiler(MPC)}).layout
    rule = layout.routing[UnitPortRole.CUSTOM]
    assert (rule.device, int(rule.channel), rule.aftertouch) == ("lab-default", 2, AftertouchPolicy.PASS)
    assert str(layout.devices["lab-default"].pattern) == "MPC Live III MIDI 1"


def test_a_layouts_own_custom_routing_overrides_the_default():   # §2.7 q2: per-layout override
    text = ("name: Tonnetz C\ndevices: {synth: Synth 1}\nrouting:\n  custom: synth ch 5 aftertouch pressure\n"
            "lab:\n  generator: tonnetz\n  base: C2\n")
    layout = compile_text(text, "tonnetz-c.yaml", sections={"lab": compiler(MPC)}).layout
    rule = layout.routing[UnitPortRole.CUSTOM]
    assert (rule.device, int(rule.channel), rule.aftertouch) == ("synth", 5, AftertouchPolicy.CHANNEL_PRESSURE)
    assert "lab-default" not in layout.devices


def test_with_neither_the_notes_are_only_shown():   # §2.7 q2
    layout = compile_text(TONNETZ_C, "tonnetz-c.yaml", sections={"lab": compiler()}).layout
    assert UnitPortRole.CUSTOM not in layout.routing
    assert NOT_ROUTED_TEXT == "notes are only shown: no default target and no layout target"


def test_note_targets_parse_and_refuse_precisely():
    assert MPC.text() == "MPC Live III MIDI 1 ch 2 aftertouch pass"
    assert NoteTarget.parse("Synth ch 3").aftertouch is AftertouchPolicy.PASS
    with pytest.raises(DomainInvariantError) as error:
        NoteTarget.parse("Synth")
    assert "write '<port> ch <1–16>" in error.value.fix
    with pytest.raises(DomainInvariantError):
        NoteTarget.parse("Synth ch 17")
    with pytest.raises(DomainInvariantError):
        NoteTarget.parse("APC64 Custom ch 1")   # never to the unit's own ports


def test_the_host_link_is_a_no_op_before_bind():
    link = HostLink()
    link.warn("x")
    link.resting(None)
    link.end_notes([48])
    assert link.load("jam") is None and link.tweak("jam", "lab.base", "D2") is None
    calls = []
    link.dispatch(lambda: calls.append(1))
    assert calls == [1]


def test_lab_state_json_is_section_3_5s_shape():
    state = LabState(generators=({"name": "tonnetz", "params": []},), active={"layout": "tonnetz-c"})
    assert state.to_json()["kind"] == "lab" and state.to_json()["active"] == {"layout": "tonnetz-c"}
