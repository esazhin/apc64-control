"""GeneratorRegistry: the built-in generators and schemes plus the plugins discovered at start (contract d11–d16,
inv14, s17 consumer, s33 supplier); and DefinitionIndex, the generated layouts the lab has compiled.

- A plugin that raises on import, exposes neither GENERATOR nor SCHEME, does not implement its protocol, fails
  when computing pads, does not return 64 pads or returns notes outside 0–127 at its default parameters is
  listed as broken with its error and never used (d13, A19). The others keep working.
- When two generators (or two schemes) share a name, the second is refused at start and the message names both
  files and the shared name (d14, A20).
- A lookup of an unknown name fails with the available names (d6, A11).
- Plugins are loaded once at start; one added while running appears after a restart (d15).
"""
import logging
import re
import threading
from dataclasses import dataclass
from typing import Iterable

from _apc64_host.domain.issues import DomainInvariantError

from ..domain.generators import (
    BUILTIN_GENERATORS, BUILTIN_SCHEMES, ColourScheme, GeneratorFault, PadLayoutGenerator, ParamSpec, channels_of,
    configure, defaults, marks_of, out_of_range, raw_notes, scheme_params, window_of,
)
from ..domain.lab_section import LabDefinition
from ..domain.pads import Rgb
from .ports import DiscoveryError, GeneratorSource

log = logging.getLogger(__name__)
BUILTIN_FILE = "_apc64_lab/domain/generators.py"
_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
GENERATOR, SCHEME = "generator", "scheme"


@dataclass(frozen=True)
class Listed:
    """One generator or scheme as the panel, CLI and API list it (A17)."""
    name: str
    kind: str
    file: str
    params: tuple[ParamSpec, ...] = ()
    error: str | None = None

    @property
    def broken(self) -> bool:
        return self.error is not None

    def to_json(self) -> dict:
        found = {"name": self.name, "file": self.file}
        if self.kind == GENERATOR or self.params:   # a scheme lists its parameters when it has any
            found["params"] = [p.describe() for p in self.params]
        if self.broken:
            found.update(broken=True, error=self.error)
        return found


def _generator_problem(candidate) -> str | None:
    """Why a generator object cannot be used, or None (d13)."""
    name, params = getattr(candidate, "name", None), getattr(candidate, "params", None)
    if not isinstance(candidate, PadLayoutGenerator) or not isinstance(name, str) \
            or not isinstance(params, tuple) or not all(isinstance(p, ParamSpec) for p in params):
        return "does not implement PadLayoutGenerator (name, params of ParamSpec, notes(params))"
    if not _NAME.match(name):
        return f'"{name}" is not a generator name; use lower-case letters, digits and "-"'
    values = defaults(params)
    try:
        notes = raw_notes(candidate, values)
        marks_of(candidate, values)
        channels_of(candidate, values)
        window_of(candidate, values)
    except GeneratorFault as fault:
        return str(fault)
    problem = out_of_range(notes, values)
    if problem is not None:
        return f"at its default parameters {problem.pad} gets note {problem.note}; notes are 0–127"
    return None


def _scheme_problem(candidate) -> str | None:
    name = getattr(candidate, "name", None)
    if not isinstance(candidate, ColourScheme) or not isinstance(name, str):
        return "does not implement ColourScheme (name, colour(note, root))"
    if not _NAME.match(name):
        return f'"{name}" is not a scheme name; use lower-case letters, digits and "-"'
    params = getattr(candidate, "params", ())
    if not isinstance(params, (tuple, list)) or not all(isinstance(p, ParamSpec) for p in params):
        return "its params are not a tuple of ParamSpec"
    if params and not callable(getattr(candidate, "configured", None)):
        return "has params but no configured(values)"
    try:
        rest, pressed = configure(candidate).colour(60, 0)
        Rgb.of(rest), Rgb.of(pressed)
    except Exception as error:   # a plugin may fail any way; it is listed, never used
        return str(error) or type(error).__name__
    return None


def _file_stem(file: str) -> str:
    return str(file).replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".py")


class GeneratorRegistry:
    def __init__(self, source: GeneratorSource | None = None,
                 builtins: Iterable[PadLayoutGenerator] = BUILTIN_GENERATORS,
                 builtin_schemes: Iterable[ColourScheme] = BUILTIN_SCHEMES):
        self._source = source
        self._builtins, self._builtin_schemes = tuple(builtins), tuple(builtin_schemes)
        self._generators: dict[str, PadLayoutGenerator] = {}
        self._schemes: dict[str, ColourScheme] = {}
        self._listed: list[Listed] = []
        self.refusals: tuple[str, ...] = ()
        self.loaded = False

    # --- start ------------------------------------------------------------------------------------------
    def load(self) -> "GeneratorRegistry":
        """Built-ins first, then each discovered plugin in file order (s17.c1: once at start)."""
        self._generators, self._schemes, self._listed, refusals = {}, {}, [], []
        files: dict[tuple[str, str], str] = {}
        found = [(BUILTIN_FILE, g) for g in self._builtins] + [(BUILTIN_FILE, s) for s in self._builtin_schemes]
        if self._source is not None:
            found += list(self._source.discover())
        for file, candidate in found:
            if isinstance(candidate, DiscoveryError):
                self._listed.append(Listed(_file_stem(file), GENERATOR, file, (), candidate.message))
                continue
            is_scheme = hasattr(candidate, "colour") and not hasattr(candidate, "notes")
            kind = SCHEME if is_scheme else GENERATOR
            problem = _generator_problem(candidate) if kind == GENERATOR else _scheme_problem(candidate)
            name = getattr(candidate, "name", None)
            name = name if isinstance(name, str) else _file_stem(file)
            if problem is None and (kind, name) in files:
                message = (f'two {kind}s are named "{name}": {files[(kind, name)]} and {file}; '
                           f"the second is refused")
                refusals.append(message)
                log.warning("lab: %s", message)
                continue
            params = ((tuple(getattr(candidate, "params", ())) if kind == GENERATOR else scheme_params(candidate))
                      if problem is None else ())
            self._listed.append(Listed(name, kind, file, params, problem))
            if problem is not None:
                log.warning("lab: %s %s (%s) is broken: %s", kind, name, file, problem)
                continue
            files[(kind, name)] = file
            (self._generators if kind == GENERATOR else self._schemes)[name] = candidate
        self.refusals = tuple(refusals)
        self.loaded = True
        return self

    # --- reading ----------------------------------------------------------------------------------------
    def generators(self) -> dict[str, PadLayoutGenerator]:
        """The working generators by name (broken and refused ones are never used)."""
        return dict(self._generators)

    def schemes(self) -> dict[str, ColourScheme]:
        return dict(self._schemes)

    def generator(self, name: str) -> PadLayoutGenerator:
        if name not in self._generators:
            raise DomainInvariantError("generator", f'no generator "{name}"',
                                       "available: " + ", ".join(sorted(self._generators)))   # A11
        return self._generators[name]

    def scheme(self, name: str) -> ColourScheme:
        if name not in self._schemes:
            raise DomainInvariantError("scheme", f'no colour scheme "{name}"',
                                       "available: " + ", ".join(sorted(self._schemes)))
        return self._schemes[name]

    def listed(self, kind: str | None = None) -> list[Listed]:
        return [entry for entry in self._listed if kind is None or entry.kind == kind]

    def listing(self) -> dict:
        """§3.5 GET /api/lab: generators [{name, params, broken?, error?}], schemes, and start-up refusals."""
        return {"generators": [e.to_json() for e in self.listed(GENERATOR)],
                "schemes": [e.to_json() for e in self.listed(SCHEME)],
                "refusals": list(self.refusals)}


@dataclass(frozen=True)
class IndexedLayout:
    layout_id: str
    name: str
    definition: LabDefinition


class DefinitionIndex:
    """The generated layouts the lab has seen: every valid 'lab:' section compiled (by layout id), named once
    the engine loads the layout or the host's catalog tells (the composition wires the catalog's names). A layout
    whose 'lab:' section did not compile (an unknown generator, a bad parameter) is kept as invalid with its first
    error, so the panel lists it with the reason rather than leaving it out (2026-10-27). Once the host's catalog
    has told which layouts are invalid (rejected()), only those are listed so: a refused tweak or a draft checked
    under the same file name compiles too, but leaves the layout in the library as it was."""

    def __init__(self):
        self._lock = threading.Lock()
        self._definitions: dict[str, LabDefinition] = {}
        self._names: dict[str, str] = {}
        self._invalid: dict[str, str] = {}
        self._rejected: set[str] | None = None   # the host library's invalid layouts (None: not told yet)

    def record(self, layout_id, definition: LabDefinition) -> None:
        with self._lock:
            self._definitions[str(layout_id)] = definition
            self._invalid.pop(str(layout_id), None)

    def failed(self, layout_id, reason: str) -> None:
        """The layout's 'lab:' section did not compile: listed as invalid with `reason` until it compiles."""
        with self._lock:
            self._invalid[str(layout_id)] = str(reason)   # the last good definition stays (a refused tweak)

    def rejected(self, layout_ids) -> None:
        """The layouts the host's library holds as invalid now."""
        with self._lock:
            self._rejected = {str(i) for i in layout_ids}

    def invalid(self) -> list[tuple[str, str, str]]:
        """(layout id, name, reason) of each layout whose 'lab:' section does not compile, by id."""
        with self._lock:
            return [(i, self._names.get(i, i), r) for i, r in sorted(self._invalid.items())
                    if self._rejected is None or i in self._rejected]

    def listing(self) -> list[dict]:
        """The panel's generated layouts: the valid ones, then the invalid ones with their reason."""
        invalid = self.invalid()
        broken = {i for i, _, _ in invalid}
        valid = [{"layout": i.layout_id, "name": i.name, "generator": i.definition.generator, "valid": True}
                 for i in self.all() if i.layout_id not in broken]
        return valid + [{"layout": i, "name": n, "valid": False, "error": r} for i, n, r in invalid]

    def named(self, layout_id, name: str | None) -> None:
        if name:
            with self._lock:
                self._names[str(layout_id)] = str(name)

    def forget(self, layout_id) -> None:
        with self._lock:
            self._definitions.pop(str(layout_id), None)
            self._names.pop(str(layout_id), None)
            self._invalid.pop(str(layout_id), None)

    def all(self) -> list[IndexedLayout]:
        with self._lock:
            return [IndexedLayout(i, self._names.get(i, i), d) for i, d in sorted(self._definitions.items())]

    def resolve(self, text: str) -> IndexedLayout | None:
        """By layout id or display name, ignoring case."""
        wanted = str(text).strip().casefold()
        return next((entry for entry in self.all()
                     if entry.layout_id.casefold() == wanted or entry.name.casefold() == wanted), None)
