"""The layout's 'lab:' section → LabDefinition plus the implied base-layer bindings (contract §7.1, s4).

    name: Tonnetz C
    lab:
      generator: tonnetz          # required: a registered generator
      base: C3                    # the generator's parameters (base, column, row, channel, …)
      scheme: fifths              # optional colour scheme, default 'fifths'
      colours:                    # optional rest-colour overrides by pitch class
        C: [255, 255, 255]
      strips:                     # optional strip section (§2.7 q6); without it strips stay as read
        1-8: {cc: 20, channel: 1, bar: red, bipolar: false}

A valid section binds the base-layer encoder to the window shift and Tempo to the interval cycle, so the
active layout is the single owner of those controls (Shift + encoder stays the host's browser). An explicit
encoder or tempo binding on a page clashes with that and is refused at its line.
"""
from dataclasses import dataclass, field
from typing import Mapping

from _apc64_host.domain.controls import Encoder, FunctionButton, FunctionName, Strip, parse_controls
from _apc64_host.domain.issues import DomainInvariantError, LayoutIssue, Severity, SourceRef
from _apc64_host.domain.layout import (
    Binding, ModuleAction, SectionEntry, SectionList, SectionMap, SectionResult, SectionScalar,
)

from .bulk_edit import NAMED_COLOURS
from .generators import (
    BUILTIN_GENERATORS, BUILTIN_SCHEMES, DEFAULT_SCHEME, ColourScheme, GeneratorFault, PadLayoutGenerator,
    generate, out_of_range, raw_notes,
)
from .harmony.spelling import parse_pitch_class, pc_name
from .pads import PadGrid, Rgb
from .records import StripAssignment

LAB_MODULE, SECTION = "lab", "lab"
WINDOW_SHIFT, INTERVAL_CYCLE = "window_shift", "interval_cycle"
TEMPO = FunctionButton(FunctionName.TEMPO)
OWN_KEYS = ("generator", "scheme", "colours", "strips")
STRIP_KEYS = ("cc", "lsb", "channel", "ch", "bar", "indicator", "bipolar", "outputs")


def implied_bindings() -> dict:
    return {Encoder(): Binding((), label="window shift", module_action=ModuleAction(LAB_MODULE, WINDOW_SHIFT)),
            TEMPO: Binding((), label="interval", module_action=ModuleAction(LAB_MODULE, INTERVAL_CYCLE))}


@dataclass(frozen=True)
class LabDefinition:
    """A validated generated layout: generator and parameters, scheme, colour overrides, strips, and where
    each field is written (for page tweaks spliced back into the file, d10)."""
    generator: str
    params: tuple[tuple[str, int], ...]
    scheme: str = DEFAULT_SCHEME
    colours: tuple[tuple[int, Rgb], ...] = ()
    strips: tuple[tuple[int, StripAssignment], ...] = ()
    file: str = ""
    line: int = 0
    field_lines: tuple[tuple[str, int], ...] = field(default=(), compare=False)

    @property
    def parameters(self) -> dict[str, int]:
        return dict(self.params)

    def grid(self, generators: Mapping[str, PadLayoutGenerator], schemes: Mapping[str, ColourScheme],
             transposition: int = 0) -> PadGrid:
        return generate(generators[self.generator], self.parameters, schemes[self.scheme], transposition,
                        dict(self.colours))

    def line_of(self, path: str) -> int | None:
        """The line of a field path such as 'lab.base' (None when the field is not written)."""
        return dict(self.field_lines).get(path)


def compile_lab_section(section: SectionEntry, file: str, existing: Mapping | None = None,
                        generators: Mapping[str, PadLayoutGenerator] | None = None,
                        schemes: Mapping[str, ColourScheme] | None = None) -> SectionResult:
    """The SectionCompiler body for 'lab:' (the application wraps it with the registry's generators)."""
    return _LabSection(section, file, existing or {},
                       generators if generators is not None else {g.name: g for g in BUILTIN_GENERATORS},
                       schemes if schemes is not None else {s.name: s for s in BUILTIN_SCHEMES}).run()


class _LabSection:
    def __init__(self, section, file, existing, generators, schemes):
        self.section, self.file, self.existing = section, file, existing
        self.generators, self.schemes = generators, schemes
        self.issues: list[LayoutIssue] = []
        self.lines: dict[str, int] = {}

    def error(self, line: int, control: str | None, problem: str, fix: str | None, joiner: str = "; "):
        self.issues.append(LayoutIssue(Severity.ERROR, SourceRef(self.file, line), control, problem, fix, joiner))

    def run(self) -> SectionResult:
        body, line = self.section.value, self.section.line
        if not isinstance(body, SectionMap):
            self.error(line, None, "the lab section is a mapping", "write 'lab:' then '  generator: tonnetz'")
            return SectionResult(None, {}, tuple(self.issues))
        for entry in body.entries:
            self.lines[f"lab.{entry.key.lower()}"] = entry.line
        generator = self._generator(body)
        scheme = self._scheme(body)
        params = self._params(body, generator) if generator is not None else None
        colours = self._colours(body.get("colours"))
        strips = self._strips(body.get("strips"))
        if generator is not None and params is not None:
            self._check_range(generator, params, body)
        self._clashes()
        if self.issues:
            return SectionResult(None, {}, tuple(self.issues))
        definition = LabDefinition(generator.name, tuple(params.items()), scheme, tuple(colours.items()),
                                   tuple(strips.items()), self.file, line, tuple(self.lines.items()))
        return SectionResult(definition, implied_bindings(), ())

    # --- generator, scheme, parameters ----------------------------------------------------------------
    def _available(self, names) -> str:
        return "available: " + ", ".join(sorted(names))

    def _generator(self, body: SectionMap) -> PadLayoutGenerator | None:
        entry = body.get("generator")
        if entry is None:
            self.error(self.section.line, None, "the lab section names no generator",
                       "add 'generator: <name>'; " + self._available(self.generators))
            return None
        name = _text(entry.value)
        if name not in self.generators:
            self.error(entry.line, "generator", f'no generator "{name}"', self._available(self.generators))   # A11
            return None
        return self.generators[name]

    def _scheme(self, body: SectionMap) -> str:
        entry = body.get("scheme")
        if entry is None:
            return DEFAULT_SCHEME
        name = _text(entry.value)
        if name not in self.schemes:
            self.error(entry.line, "scheme", f'no colour scheme "{name}"', self._available(self.schemes))
        return name

    def _params(self, body: SectionMap, generator: PadLayoutGenerator) -> dict | None:
        specs = {p.name: p for p in generator.params}
        values = {p.name: p.default for p in generator.params}
        ok = True
        for entry in body.entries:
            key = entry.key.lower()
            if key in OWN_KEYS:
                continue
            if key not in specs:
                self.error(entry.line, None, f"unknown key '{entry.key}'",
                           f"the lab section takes {', '.join(OWN_KEYS)} and the {generator.name} parameters: "
                           + (", ".join(specs) or "none"))
                ok = False
                continue
            try:
                values[key] = specs[key].parse(_scalar(entry.value))
            except DomainInvariantError as error:
                self.error(entry.line, key, error.problem, error.fix, error.joiner)
                ok = False
        return values if ok else None

    def _check_range(self, generator: PadLayoutGenerator, params: dict, body: SectionMap):
        try:
            notes = raw_notes(generator, params)
        except GeneratorFault as fault:
            self.error(body.get("generator").line, "generator", f'generator "{generator.name}" failed: {fault}',
                       "fix the generator or choose another")
            return
        problem = out_of_range(notes, params)
        if problem is not None:
            base = body.get("base")
            self.error(base.line if base else self.section.line, "base", problem.problem(params.get("base")),
                       problem.fix())   # A10

    # --- colours and strips ---------------------------------------------------------------------------
    def _colours(self, entry: SectionEntry | None) -> dict[int, Rgb]:
        if entry is None:
            return {}
        if not isinstance(entry.value, SectionMap):
            self.error(entry.line, "colours", "colours maps note names to colours", "write '  C: [255, 255, 255]'")
            return {}
        colours = {}
        for item in entry.value.entries:
            control = f"colour {item.key}"
            pc = parse_pitch_class(item.key)
            if pc is None:
                self.error(item.line, control, f"'{item.key}' is not a note name",
                           "write C, C♯ (or C#), D♭ (or Db) … B")
                continue
            try:
                colours[pc] = _colour(item.value)   # A12
            except DomainInvariantError as error:
                self.error(item.line, control, error.problem, error.fix, error.joiner)
            self.lines[f"lab.colours.{pc_name(pc)}"] = item.line
        return colours

    def _strips(self, entry: SectionEntry | None) -> dict[int, StripAssignment]:
        if entry is None:
            return {}
        if not isinstance(entry.value, SectionMap):
            self.error(entry.line, "strips", "strips maps strip numbers to settings",
                       "write '  1-8: {cc: 20, channel: 1}'")
            return {}
        strips: dict[int, StripAssignment] = {}
        for item in entry.value.entries:
            key = item.key.strip().lower()
            words = key if key.startswith("strip") else ("strips " if "-" in key else "strip ") + key
            try:
                numbers = [s.n for s in parse_controls(words)]
                if not all(isinstance(s, Strip) for s in parse_controls(words)):
                    raise DomainInvariantError("strip", f"'{item.key}' is not a strip", "strips are 1–8")
            except DomainInvariantError as error:
                self.error(item.line, words, error.problem, "strips are 1–8, e.g. '3' or '1-8'")
                continue
            settings = self._strip_settings(item)
            if settings is None:
                continue
            for i, number in enumerate(numbers):
                if number in strips:
                    self.error(item.line, f"strip {number}", f"strip {number} is set twice", "keep one")
                    continue
                try:
                    strips[number] = StripAssignment(
                        cc=settings["cc"] + i, channel=settings.get("channel", 1),
                        lsb=None if settings.get("lsb") is None else settings["lsb"] + i,
                        bar=settings.get("bar", Rgb(255, 0, 0)), indicator=settings.get("indicator", Rgb(255, 255, 255)),
                        bipolar=settings.get("bipolar", False), outputs=settings.get("outputs", 7))
                except DomainInvariantError as error:
                    self.error(item.line, f"strip {number}", error.problem, error.fix, error.joiner)
        return strips

    def _strip_settings(self, item: SectionEntry) -> dict | None:
        key = item.key.strip().lower()
        control = key if key.startswith("strip") else f"strip {key}"
        if not isinstance(item.value, SectionMap):
            self.error(item.line, control, "a strip takes cc, lsb, channel, bar, indicator, bipolar, outputs",
                       "write e.g. '{cc: 20, channel: 1, bar: red}'")
            return None
        settings: dict = {}
        for sub in item.value.entries:
            key = sub.key.lower()
            if key not in STRIP_KEYS:
                self.error(sub.line, control, f"unknown strip key '{sub.key}'",
                           "a strip takes cc, lsb, channel, bar, indicator, bipolar, outputs")
                return None
            value = _scalar(sub.value) if isinstance(sub.value, SectionScalar) else None
            try:
                if key in ("bar", "indicator"):
                    settings[key] = _colour(sub.value)
                elif key == "bipolar":
                    settings[key] = str(value).lower() in ("true", "yes", "on", "1")
                else:
                    if isinstance(value, bool) or not str(value).lstrip("-").isdigit():
                        raise DomainInvariantError(key, f"{key} '{value}' is not a number", "write a whole number")
                    settings["channel" if key == "ch" else key] = int(value)
            except DomainInvariantError as error:
                self.error(sub.line, control, error.problem, error.fix, error.joiner)
                return None
        if "cc" not in settings:
            self.error(item.line, control, "the strip has no cc", "write 'cc: <0–127>'")
            return None
        return settings

    # --- the controls the section owns ----------------------------------------------------------------
    def _clashes(self):
        for control, what, fix in ((Encoder(), "the lab section shifts the window with the encoder",
                                    "remove this encoder binding; Shift + encoder still browses layouts"),
                                   (TEMPO, "the lab section cycles the interval with Tempo",
                                    "remove this tempo binding")):
            for found in self.existing.get(control, ()):
                self.error(found.line, str(control), what, fix)


def _scalar(node):
    return node.value if isinstance(node, SectionScalar) else None


def _text(node) -> str:
    value = _scalar(node)
    return "" if value is None else str(value).strip()


def _colour(node) -> Rgb:
    """[r, g, b], '#RRGGBB' or a colour name."""
    if isinstance(node, SectionList):
        return Rgb.of([_scalar(item) for item in node.items])
    value = _scalar(node)
    if isinstance(value, str) and value.strip().lower() in NAMED_COLOURS:
        return NAMED_COLOURS[value.strip().lower()]
    if not isinstance(value, str):
        raise DomainInvariantError("colour", f"'{value}' is not a colour",
                                   "write [r, g, b] with 0–255 each, #RRGGBB or a name")
    return Rgb.of(value)
