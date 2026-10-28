"""Contract 2 T16: section tweaks through notation/splice.py (inv10, pi2; s38 supplier, s39 collaboration).

save_section_field('tonnetz-c', 'lab.base', 'D3') changes the file by one splice, the file re-parses identically
except that field, and it is handed to the pipeline as a new version. A section compiler double stands in for
the lab's (the host never imports the lab)."""
from _apc64_host.application.conftest import MemorySource
from _apc64_host.application.tweaks import Invalid, Saved, Stale, TweakService
from _apc64_host.domain.controls import Encoder, FunctionButton, FunctionName, PadPos
from _apc64_host.domain.issues import LayoutIssue, Severity, SourceRef
from _apc64_host.domain.layout import (
    Binding, ContentHash, Layer, ModuleAction, SectionResult, TweakField, TweakRequest,
)
from _apc64_host.notation.compiler import compile_text

TONNETZ = """\
# Tonnetz C: a generated layout
name: Tonnetz C
devices:
  mpc: MPC Live III MIDI 1
pages:
  1 Lab:
    pad r1c1: note 36 on mpc ch 1
lab:
  generator: tonnetz
  base: C3          # the bottom-left pad
  scheme: fifths
routing:
  custom: mpc ch 1 aftertouch pass
"""
NOTES = {"C3", "D3", "E3", "C2", "D2"}


class LabCompiler:
    """A SectionCompiler double: base must be a known note name, scheme fifths or root-highlight."""

    def compile(self, section, file, existing):
        body = section.value
        issues = []
        values = {e.key: e.value.value for e in body.entries}
        base = body.get("base")
        if base is not None and base.value.value not in NOTES:
            issues.append(LayoutIssue(Severity.ERROR, SourceRef(file, base.line), "base",
                                      f"{base.value.value} is not a note", "write e.g. C3"))
        scheme = body.get("scheme")
        if scheme is not None and scheme.value.value not in ("fifths", "root-highlight"):
            issues.append(LayoutIssue(Severity.ERROR, SourceRef(file, scheme.line), "scheme",
                                      f"no scheme {scheme.value.value}", "use fifths or root-highlight"))
        bindings = {Encoder(): Binding((), label="window shift", module_action=ModuleAction("lab", "window_shift")),
                    FunctionButton(FunctionName.TEMPO): Binding((), label="interval",
                                                                module_action=ModuleAction("lab", "interval_cycle"))}
        return SectionResult(values, bindings, tuple(issues))


SECTIONS = {"lab": LabCompiler()}


def service(text=TONNETZ):
    source = MemorySource({"tonnetz-c": text}, emit_on_write=False)
    handed = []
    tweaks = TweakService(source, sections=SECTIONS, on_saved=handed.append)
    return tweaks, source, handed


def compiled(text):
    return compile_text(text, "tonnetz-c.yaml", sections=SECTIONS)


def test_t16_lab_base_d3_changes_the_file_by_one_splice_and_hands_it_to_the_pipeline():
    # A16 (save half): the saved definition now says base D3
    tweaks, source, handed = service()
    answer = tweaks.save_section_field("tonnetz-c", "lab.base", "D3")
    new = source.files["tonnetz-c"]
    assert answer == Saved(ContentHash.of(new))
    old_lines, new_lines = TONNETZ.splitlines(), new.splitlines()
    assert [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b] == [9]
    assert len(old_lines) == len(new_lines)
    assert new_lines[9] == "  base: D3  # the bottom-left pad"                     # the comment is kept
    before, after = compiled(TONNETZ).layout, compiled(new).layout
    assert after.sections["lab"] == {**before.sections["lab"], "base": "D3"}         # only that field
    assert after.pages == before.pages and after.routing == before.routing and after.devices == before.devices
    assert handed == ["tonnetz-c"]                                                    # a new version (s39)


def test_a_given_comment_replaces_the_lines_comment_and_a_new_line_carries_it():
    # a comment that spells out the value (a guitar tuning's notes) would go stale: the module gives a new one
    tweaks, source, _ = service()
    assert isinstance(tweaks.save_section_field("tonnetz-c", "lab.base", "D3", comment="D3 = 62"), Saved)
    assert source.files["tonnetz-c"].splitlines()[9] == "  base: D3  # D3 = 62"
    assert isinstance(tweaks.save_section_field("tonnetz-c", "lab.base", "D3", comment="the root"), Saved)
    assert source.files["tonnetz-c"].splitlines()[9] == "  base: D3  # the root"   # same value, new comment
    assert isinstance(tweaks.save_section_field("tonnetz-c", "lab.column_step", 2, comment="semitones"), Saved)
    assert source.files["tonnetz-c"].splitlines()[11] == "  column_step: 2  # semitones"


def test_a_field_the_section_lacks_is_added_as_one_line():
    tweaks, source, _ = service()
    assert isinstance(tweaks.save_section_field("tonnetz-c", "lab.column_step", 2), Saved)
    lines = source.files["tonnetz-c"].splitlines()
    assert lines[11] == "  column_step: 2" and lines[12] == "routing:"
    assert compiled(source.files["tonnetz-c"]).layout.sections["lab"]["column_step"] == 2


def test_an_invalid_value_is_refused_with_the_section_compilers_issue_and_nothing_is_written():
    tweaks, source, handed = service()
    answer = tweaks.save_section_field("tonnetz-c", "lab.scheme", "rainbow")
    assert isinstance(answer, Invalid)
    assert answer.issues[0].message() == "tonnetz-c.yaml line 11: no scheme rainbow; use fifths or root-highlight"
    assert source.files["tonnetz-c"] == TONNETZ and source.writes == [] and handed == []


def test_a_stale_hash_an_unknown_section_and_a_block_field_are_refused():
    tweaks, source, _ = service()
    assert isinstance(tweaks.save_section_field("tonnetz-c", "lab.base", "D3", base_hash=ContentHash("0" * 12)), Stale)
    unknown = tweaks.save_section_field("tonnetz-c", "pages.1", "x")
    assert isinstance(unknown, Invalid) and unknown.issues[0].problem == "'pages' is not a module section"
    missing = tweaks.save_section_field("tonnetz-c", "lab", "x")
    assert isinstance(missing, Invalid)
    assert source.writes == []


def test_the_same_value_writes_nothing():
    tweaks, source, handed = service()
    assert tweaks.save_section_field("tonnetz-c", "lab.base", "C3") == Saved(ContentHash.of(TONNETZ))
    assert source.writes == [] and handed == []


def test_a_single_control_tweak_in_a_file_with_a_lab_section_compiles_with_the_sections():
    # contract 1's page tweak keeps working on a generated layout's own page bindings
    tweaks, source, _ = service()
    request = TweakRequest("tonnetz-c", Layer.BASE, PadPos(1, 1), TweakField.LABEL, "Root",
                           ContentHash.of(TONNETZ), page=1)
    assert isinstance(tweaks.apply(request), Saved)
    assert "pad r1c1:" in source.files["tonnetz-c"] and "Root" in source.files["tonnetz-c"]
    assert compiled(source.files["tonnetz-c"]).valid
