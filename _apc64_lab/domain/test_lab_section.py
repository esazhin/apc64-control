"""The 'lab:' section compiler through the host's compile_text (T5; s4 supplier side for the domain body)."""
from _apc64_host.domain.controls import Encoder, FunctionButton, FunctionName, PadPos
from _apc64_host.domain.layout import Layer, ModuleAction
from _apc64_host.notation.compiler import compile_text
from _apc64_lab.domain.generators import BUILTIN_GENERATORS, BUILTIN_SCHEMES
from _apc64_lab.domain.lab_section import LabDefinition, compile_lab_section
from _apc64_lab.domain.pads import Rgb
from _apc64_lab.generators.root_highlight import SCHEME as ROOT_HIGHLIGHT

TEMPO = FunctionButton(FunctionName.TEMPO)


class LabSection:
    """Stands in for the application's SectionCompiler (T22): the domain body with the shipped generators."""

    def __init__(self, schemes=None):
        self.schemes = schemes

    def compile(self, section, file, existing):
        return compile_lab_section(section, file, existing, schemes=self.schemes)


def lab(text, file="tonnetz-c.yaml", schemes=None):
    return compile_text(text, file, sections={"lab": LabSection(schemes)})


def messages(result):
    return [issue.message() for issue in result.issues]


TONNETZ_C = """name: Tonnetz C
lab:
  generator: tonnetz
  base: 48
"""


def test_a_valid_section_yields_the_definition_and_the_encoder_and_tempo_actions():   # T5, s4.c2
    result = lab(TONNETZ_C)
    assert result.valid, messages(result)
    definition = result.layout.section("lab")
    assert isinstance(definition, LabDefinition)
    assert (definition.generator, definition.parameters, definition.scheme) == (
        "tonnetz", {"base": 48, "channel": 1}, "fifths")
    assert definition.line_of("lab.base") == 4 and definition.file == "tonnetz-c.yaml"
    page = result.layout.page(1)
    assert page.encoder.module_action == ModuleAction("lab", "window_shift")
    assert page.binding(Layer.BASE, TEMPO).module_action == ModuleAction("lab", "interval_cycle")
    assert page.layers[Layer.SHIFT] == {}   # Shift + encoder stays the host's browser (inv12)


def test_the_definition_generates_the_pads():   # A8 through the definition
    definition = lab(TONNETZ_C).layout.section("lab")
    gens, schemes = {g.name: g for g in BUILTIN_GENERATORS}, {s.name: s for s in BUILTIN_SCHEMES}
    grid = definition.grid(gens, schemes)
    assert (grid.note_at(1, 1), grid.note_at(1, 3), grid.note_at(2, 2)) == (48, 55, 52)
    assert grid.at(PadPos(1, 2)).silent and grid.at(PadPos(1, 1)).rest.to_hex() == "#FFFFFF"
    assert definition.grid(gens, schemes, 7).note_at(1, 1) == 55


def test_base_110_is_refused_naming_the_pad_and_the_highest_base():   # A10, d4
    text = "lab:\n  generator: tonnetz\n  base: 110\n"
    result = lab(text)
    assert result.layout is None
    assert messages(result) == ["tonnetz-c.yaml line 3, base: 110 puts pad r8c8 at note 138; the highest base is 99"]


def test_an_unknown_generator_lists_the_available_ones():   # A11, d6
    result = lab("lab:\n  generator: tonetz\n")
    # the host renderer leaves the control out when the problem names it (a contract 1 build decision)
    assert messages(result) == ['tonnetz-c.yaml line 2: no generator "tonetz"; available: isomorphic, tonnetz']
    assert result.issues[0].control == "generator"


def test_a_colour_component_above_255_is_refused():   # A12, d19
    text = "name: Tonnetz C\nlab:\n  generator: tonnetz\n  base: 48\n  colours:\n    C: [300, 0, 0]\n"
    assert messages(lab(text)) == [
        "tonnetz-c.yaml line 6, colour C: 300 is outside 0–255; write each of red, green and blue as 0–255"]


def test_colour_overrides_take_any_spelling():
    text = TONNETZ_C + "  colours:\n    C: '#102030'\n    F#: [1, 2, 3]\n    Bb: blue\n"
    definition = lab(text).layout.section("lab")
    assert dict(definition.colours) == {0: Rgb(16, 32, 48), 6: Rgb(1, 2, 3), 10: Rgb(0, 0, 255)}
    grid = definition.grid({g.name: g for g in BUILTIN_GENERATORS}, {s.name: s for s in BUILTIN_SCHEMES})
    assert grid.at(PadPos(1, 1)).rest == Rgb(16, 32, 48)


def test_scheme_parameters_and_unknown_keys():   # d5, d18, A15's scheme
    schemes = {s.name: s for s in BUILTIN_SCHEMES} | {ROOT_HIGHLIGHT.name: ROOT_HIGHLIGHT}
    assert lab(TONNETZ_C + "  scheme: root-highlight\n", schemes=schemes).layout.section("lab").scheme == \
        "root-highlight"
    assert messages(lab(TONNETZ_C + "  scheme: rainbow\n")) == [
        'tonnetz-c.yaml line 5: no colour scheme "rainbow"; available: fifths']
    assert messages(lab(TONNETZ_C + "  rows: 4\n")) == [
        "tonnetz-c.yaml line 5: unknown key 'rows'; the lab section takes generator, scheme, colours, strips, performer and "
        "the tonnetz parameters: base, channel"]
    assert messages(lab(TONNETZ_C + "  channel: 17\n")) == [
        "tonnetz-c.yaml line 5, channel: 17 is outside 1–16; channels are 1–16"]
    assert messages(lab("lab:\n  base: 48\n")) == [
        "tonnetz-c.yaml line 1: the lab section names no generator; add 'generator: <name>'; "
        "available: isomorphic, tonnetz"]


def test_fourths_isomorphic_definition():   # A9 through the definition
    text = "name: Fourths\nlab:\n  generator: isomorphic\n  base: 36\n  column: 1\n  row: 5\n"
    definition = lab(text, "fourths.yaml").layout.section("lab")
    grid = definition.grid({g.name: g for g in BUILTIN_GENERATORS}, {s.name: s for s in BUILTIN_SCHEMES})
    assert (grid.note_at(1, 1), grid.note_at(1, 2), grid.note_at(2, 1), grid.note_at(8, 8)) == (36, 37, 41, 78)


def test_an_explicit_encoder_binding_clashes_with_the_section():   # s4 (T29's conflicting encoder binding)
    text = ("name: Tonnetz C\ndevices: {mpc: MPC}\npages:\n  1:\n    encoder: cc 30\nlab:\n  generator: tonnetz\n"
            "  base: 48\n")
    assert messages(lab(text)) == [
        "tonnetz-c.yaml line 5: the lab section shifts the window with the encoder; remove this encoder binding; "
        "Shift + encoder still browses layouts"]


def test_the_optional_strip_section():   # §2.7 q6
    text = TONNETZ_C + ("  strips:\n    1-8: {cc: 20, channel: 2, bar: blue, bipolar: true}\n"
                        "    'strip 9': {cc: 1}\n")
    assert messages(lab(text)) == [
        "tonnetz-c.yaml line 7, strip 9: no such strip; strips are 1–8, e.g. '3' or '1-8'"]
    text = TONNETZ_C + "  strips:\n    1-4: {cc: 20, lsb: 52, channel: 2, bar: blue, bipolar: true}\n"
    strips = dict(lab(text).layout.section("lab").strips)
    assert sorted(strips) == [1, 2, 3, 4]
    assert (strips[4].cc, strips[4].lsb, strips[4].channel, strips[4].bar, strips[4].bipolar) == (
        23, 55, 2, Rgb(0, 0, 255), True)
    assert lab(TONNETZ_C).layout.section("lab").strips == ()   # absent: strips are written back as read
    assert messages(lab(TONNETZ_C + "  strips:\n    3: {channel: 2}\n")) == [
        "tonnetz-c.yaml line 6, strip 3: the strip has no cc; write 'cc: <0–127>'"]


def test_without_the_lab_registered_the_section_is_an_unknown_key():   # contract 1 unchanged
    assert compile_text(TONNETZ_C, "tonnetz-c.yaml").issues[0].problem == "unknown key 'lab'"


def test_tempos_label_follows_the_layouts_own_window_steps():   # after the guitar live test (2026-10-27)
    from _apc64_lab.generators.guitar import GENERATOR as GUITAR

    class WithGuitar:
        def compile(self, section, file, existing):
            generators = {g.name: g for g in (*BUILTIN_GENERATORS, GUITAR)}
            return compile_lab_section(section, file, existing, generators)
    result = compile_text("name: Guitar\nlab:\n  generator: guitar\n", "guitar.yaml", sections={"lab": WithGuitar()})
    assert result.valid, messages(result)
    assert result.layout.page(1).binding(Layer.BASE, TEMPO).label == "Fret / Page"
    assert lab(TONNETZ_C).layout.page(1).binding(Layer.BASE, TEMPO).label == "interval"
