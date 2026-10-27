"""Contract 2 (T8, s4 collaboration, s36 supplier): module-owned top-level sections in the compiler.
With no section compiler registered the results are contract 1's (the 'lab:' key is unknown)."""
from _apc64_host.domain.controls import Encoder, FunctionButton, FunctionName, PadPos
from _apc64_host.domain.issues import LayoutIssue, Severity, SourceRef
from _apc64_host.domain.layout import (
    Binding, Layer, ModuleAction, SectionEntry, SectionList, SectionMap, SectionResult, SectionScalar,
)
from _apc64_host.notation.compiler import compile_text

TEMPO = FunctionButton(FunctionName.TEMPO)
LAB_ONLY = """name: Tonnetz C
lab:
  generator: tonnetz
  base: C3
  colours:
    C: [255, 255, 255]
"""
WITH_PAGE = """name: Tonnetz C
devices: {mpc: MPC Live III MIDI 1}
pages:
  1 Main:
    pad r1c1: note 36
    encoder: cc 30
lab:
  generator: tonnetz
"""


class RecordingCompiler:
    """A double SectionCompiler: records what it is sent, answers with canned bindings and issues."""

    def __init__(self, issues=(), bindings=None, value="LabDefinition"):
        self.calls, self.issues, self.value = [], tuple(issues), value
        self.bindings = {Encoder(): Binding((), module_action=ModuleAction("lab", "window_shift")),
                         TEMPO: Binding((), module_action=ModuleAction("lab", "interval_cycle"))} \
            if bindings is None else bindings

    def compile(self, section, file, existing):
        self.calls.append((section, file, existing))
        return SectionResult(self.value, self.bindings, self.issues)


def test_the_section_is_passed_with_its_lines():   # s4.c1
    double = RecordingCompiler()
    compile_text(LAB_ONLY, "tonnetz-c.yaml", sections={"lab": double})
    (section, file, existing), = double.calls
    assert file == "tonnetz-c.yaml" and isinstance(section, SectionEntry)
    assert (section.key, section.line) == ("lab", 2)
    body = section.value
    assert isinstance(body, SectionMap)
    assert [(e.key, e.line) for e in body.entries] == [("generator", 3), ("base", 4), ("colours", 5)]
    assert body.get("base").value == SectionScalar("C3", 4)
    colour = body.get("colours").value.get("C")
    assert colour.line == 6 and isinstance(colour.value, SectionList)
    assert [item.value for item in colour.value.items] == [255, 255, 255]
    assert existing == {}


def test_returned_bindings_join_the_layout_and_the_value_is_kept():   # s4.c2
    result = compile_text(LAB_ONLY, "tonnetz-c.yaml", sections={"lab": RecordingCompiler()})
    assert result.valid
    layout = result.layout
    assert layout.section("lab") == "LabDefinition"
    page = layout.page(1)   # page 1 is made for a layout that has none
    assert page.encoder.module_action == ModuleAction("lab", "window_shift")
    assert page.binding(Layer.BASE, TEMPO).module_action.action == "interval_cycle"
    assert page.layers[Layer.SHIFT] == {}


def test_bindings_join_every_page_beside_its_own():
    text = WITH_PAGE.replace("    encoder: cc 30\n", "")
    result = compile_text(text.replace("pages:\n", "pages:\n  2 Other:\n    pad r1c2: note 37\n"),
                          "tonnetz-c.yaml", sections={"lab": RecordingCompiler()})
    assert result.valid
    for number in (1, 2):
        assert result.layout.page(number).encoder.is_module_action
    assert result.layout.page(1).binding(Layer.BASE, PadPos(1, 1)).actions[0].number == 36


def test_returned_issues_make_the_layout_invalid():   # s4.c2
    issue = LayoutIssue(Severity.ERROR, SourceRef("tonnetz-c.yaml", 3), "generator", 'no generator "tonetz"',
                        "available: isomorphic, tonnetz")
    result = compile_text(LAB_ONLY, "tonnetz-c.yaml", sections={"lab": RecordingCompiler([issue])})
    assert not result.valid and result.layout is None
    assert [i.message() for i in result.issues] == [
        'tonnetz-c.yaml line 3: no generator "tonetz"; available: isomorphic, tonnetz']   # control named in the problem


def test_warnings_stay_warnings():
    warning = LayoutIssue(Severity.WARNING, SourceRef("tonnetz-c.yaml", 1), None, "long name", None)
    result = compile_text(LAB_ONLY, "tonnetz-c.yaml", sections={"lab": RecordingCompiler([warning])})
    assert result.valid and result.warnings == (warning,)


def test_existing_explicit_bindings_are_passed_and_a_clash_is_refused():   # s4.c1, T29's conflict
    double = RecordingCompiler()
    result = compile_text(WITH_PAGE, "tonnetz-c.yaml", sections={"lab": double})
    existing = double.calls[0][2]
    assert existing[Encoder()][0].line == 6 and existing[Encoder()][0].page == 1
    assert existing[PadPos(1, 1)][0].binding.actions[0].number == 36
    assert not result.valid
    assert [i.message() for i in result.issues] == [
        "tonnetz-c.yaml line 6: encoder is also bound by the 'lab:' section; "
        "remove this binding or the 'lab:' section"]


def test_without_a_registered_compiler_the_results_are_contract_1s():   # T8, a29
    plain = compile_text(LAB_ONLY, "tonnetz-c.yaml")
    assert [i.message() for i in plain.issues] == [
        "tonnetz-c.yaml line 2: unknown key 'lab'; the top-level keys are name, device, devices, pages, banks, "
        "routing"]
    assert compile_text(LAB_ONLY, "tonnetz-c.yaml", sections={}) == plain
    jam = "name: Jam\ndevices: {mpc: MPC}\npages:\n  1:\n    pad r1c1: note 36\n"
    assert compile_text(jam, "jam.yaml") == compile_text(jam, "jam.yaml", sections={"lab": RecordingCompiler()})
    assert compile_text(jam, "jam.yaml").layout.sections == {}
