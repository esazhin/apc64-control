"""The layout's 'lab:' section → LabDefinition plus the implied base-layer bindings (contract §7.1, s4).

    name: Tonnetz C
    lab:
      generator: tonnetz          # required: a registered generator
      base: C3                    # the generator's parameters (base, column, row, channel, …)
      scheme: fifths              # optional colour scheme, default 'fifths' (and its parameters, e.g. scale)
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
    BUILTIN_GENERATORS, BUILTIN_SCHEMES, DEFAULT_SCHEME, ColourScheme, GeneratorFault, Neck, PadLayoutGenerator,
    ParamKind, ScaleOverlay, channels_of, configure, generate, neck_of, out_of_range, overlay_of, pad_names_of,
    raw_notes, root_of, row_labels_of, scheme_params, window_of,
)
from .music import PitchClass
from .harmony.spelling import parse_pitch_class, pc_name
from .pads import PadGrid, Rgb
from .records import StripAssignment
from .window import WindowSpec

LAB_MODULE, SECTION = "lab", "lab"
WINDOW_SHIFT, INTERVAL_CYCLE = "window_shift", "interval_cycle"
TEMPO = FunctionButton(FunctionName.TEMPO)
OWN_KEYS = ("generator", "scheme", "colours", "strips")
STRIP_KEYS = ("cc", "lsb", "channel", "ch", "bar", "indicator", "bipolar", "outputs")


def implied_bindings(window: WindowSpec | None = None) -> dict:
    """The base-layer encoder and Tempo of a generated layout. Tempo's label names what it toggles: 'interval'
    (octave / fifth / third), or the generator's own step kinds ('Fret / Page' for the guitar)."""
    tempo = " / ".join(step.label for step in window.steps) if window is not None else "interval"
    return {Encoder(): Binding((), label="window shift", module_action=ModuleAction(LAB_MODULE, WINDOW_SHIFT)),
            TEMPO: Binding((), label=tempo, module_action=ModuleAction(LAB_MODULE, INTERVAL_CYCLE))}


@dataclass(frozen=True)
class LabDefinition:
    """A validated generated layout: generator and parameters, scheme and its parameters, colour overrides,
    strips, and where each field is written (for page tweaks spliced back into the file, d10)."""
    generator: str
    params: tuple[tuple[str, int | str], ...]
    scheme: str = DEFAULT_SCHEME
    colours: tuple[tuple[int, Rgb], ...] = ()
    strips: tuple[tuple[int, StripAssignment], ...] = ()
    file: str = ""
    line: int = 0
    field_lines: tuple[tuple[str, int], ...] = field(default=(), compare=False)
    scheme_params: tuple[tuple[str, int | str | None], ...] = ()
    layout_root: int | None = None   # the generator's root(params) when it has one (the guitar: its lowest string)

    @property
    def parameters(self) -> dict[str, int | str]:
        return dict(self.params)

    @property
    def root(self) -> int:
        """The layout's root pitch class: the generator's own, else its base note's (C without a base)."""
        if self.layout_root is not None:
            return self.layout_root
        return int(PitchClass.of(self.parameters.get("base", 0)))

    def colour_scheme(self, schemes: Mapping[str, ColourScheme]) -> ColourScheme:
        return configure(schemes[self.scheme], dict(self.scheme_params))

    def grid(self, generators: Mapping[str, PadLayoutGenerator], schemes: Mapping[str, ColourScheme],
             transposition: int = 0) -> PadGrid:
        return generate(generators[self.generator], self.parameters, self.colour_scheme(schemes), transposition,
                        dict(self.colours))

    def overlay(self, schemes: Mapping[str, ColourScheme]) -> ScaleOverlay | None:
        """The scale the scheme lights, when it is a scale overlay."""
        return overlay_of(self.colour_scheme(schemes), self.root) if self.scheme in schemes else None

    def row_labels(self, generators: Mapping[str, PadLayoutGenerator]) -> tuple[str, ...] | None:
        generator = generators.get(self.generator)
        return row_labels_of(generator, self.parameters) if generator is not None else None

    def pad_names(self, generators: Mapping[str, PadLayoutGenerator], transposition: int = 0) -> tuple | None:
        generator = generators.get(self.generator)
        return pad_names_of(generator, self.parameters, transposition) if generator is not None else None

    def window_spec(self, generators: Mapping[str, PadLayoutGenerator]) -> WindowSpec | None:
        """The generator's own window steps and range, or None (Octave / Fifth / Third)."""
        return window_of(generators.get(self.generator), self.parameters)

    def neck(self, generators: Mapping[str, PadLayoutGenerator]) -> Neck | None:
        """The fretboard the page draws for a guitar-like generator, or None."""
        return neck_of(generators.get(self.generator), self.parameters)

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
        values = self._params(body, generator, self.schemes.get(scheme)) if generator is not None else None
        params, given_scheme_params = values if values is not None else (None, None)
        colours = self._colours(body.get("colours"))
        strips = self._strips(body.get("strips"))
        if generator is not None and params is not None:
            self._check_range(generator, params, body)
        self._clashes()
        if any(issue.is_error for issue in self.issues):
            return SectionResult(None, {}, tuple(self.issues))
        own_root = root_of(generator, params) if callable(getattr(generator, "root", None)) else None
        definition = LabDefinition(generator.name, tuple(params.items()), scheme, tuple(colours.items()),
                                   tuple(strips.items()), self.file, line, tuple(self.lines.items()),
                                   tuple(given_scheme_params.items()), own_root)
        try:
            window = window_of(generator, params)
        except Exception:   # checked above (_check_range); a label is no reason to refuse the layout
            window = None
        return SectionResult(definition, implied_bindings(window), tuple(self.issues))   # warnings only

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

    def _params(self, body: SectionMap, generator: PadLayoutGenerator,
                scheme: ColourScheme | None) -> tuple[dict, dict] | None:
        """The generator's parameters (defaults filled in) and the scheme's as written. A name both declare is
        the generator's."""
        specs = {p.name: p for p in generator.params}
        own_scheme = {p.name: p for p in scheme_params(scheme) if p.name not in specs} if scheme else {}
        values = {p.name: p.default for p in generator.params}
        scheme_values: dict = {}
        ok = True
        for entry in body.entries:
            key = entry.key.lower()
            if key in OWN_KEYS:
                continue
            spec = specs.get(key) or own_scheme.get(key)
            owner = self._scheme_owning(key) if spec is None else None
            if owner is not None:   # left over from another scheme (a scheme switch): unused, not wrong
                self.issues.append(LayoutIssue(
                    Severity.WARNING, SourceRef(self.file, entry.line), key,
                    f"{key} is a parameter of the {owner} colour scheme, unused with {scheme.name if scheme else 'this scheme'}",
                    f"remove it, or write 'scheme: {owner}'"))
                continue
            if spec is None:
                self.error(entry.line, None, f"unknown key '{entry.key}'", self._unknown_fix(generator, own_scheme))
                ok = False
                continue
            given = _list(entry.value) if spec.kind == ParamKind.NOTE_LIST else _scalar(entry.value)
            try:
                (values if key in specs else scheme_values)[key] = spec.parse(given)
            except DomainInvariantError as error:
                self.error(entry.line, key, error.problem, error.fix, error.joiner)
                ok = False
        return (values, scheme_values) if ok else None

    def _scheme_owning(self, key: str) -> str | None:
        return next((name for name, s in sorted(self.schemes.items())
                     if any(p.name == key for p in scheme_params(s))), None)

    def _unknown_fix(self, generator: PadLayoutGenerator, own_scheme: Mapping) -> str:
        fix = (f"the lab section takes {', '.join(OWN_KEYS)} and the {generator.name} parameters: "
               + (", ".join(p.name for p in generator.params) or "none"))
        if own_scheme:
            fix += " and the scheme's: " + ", ".join(own_scheme)
        return fix

    def _check_range(self, generator: PadLayoutGenerator, params: dict, body: SectionMap):
        try:
            notes = raw_notes(generator, params)
            channels_of(generator, params)
            window_of(generator, params)
        except GeneratorFault as fault:
            self.error(body.get("generator").line, "generator", f'generator "{generator.name}" failed: {fault}',
                       "fix the generator or choose another")
            return
        problem = out_of_range(notes, params)
        if problem is not None:
            name = next((p.name for p in generator.params if p.kind in (ParamKind.NOTE, ParamKind.NOTE_LIST)
                         and body.get(p.name) is not None), "base")   # the note parameter written (base, tuning)
            written = body.get(name)
            self.error(written.line if written else self.section.line, name, problem.problem(params.get("base")),
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


def _list(node):
    """A list's scalars ([E1, A1, 50]), else the scalar."""
    return [_scalar(item) for item in node.items] if isinstance(node, SectionList) else _scalar(node)


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
