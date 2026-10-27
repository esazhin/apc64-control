"""TweakService: a single-control change from the page saved back into the agent's file (contract inv21, d169–d173).

The request carries the hash of the file the page last read; a different hash on disk is STALE ('layout
changed, reload', d79) and nothing is written. Otherwise the tweak is spliced in as one entry line
(notation.splice, never a re-dump), the whole new text is compiled with the current port catalog, and only
a valid result is written (atomically, by the LayoutSource). The write then goes live through the normal
layout pipeline like any other file write (a22).

Contract 2 (T16, s38/s39): save_section_field(layout, 'lab.base', 'D3') changes one field of a module-owned
section by one line (notation.splice), checks that the file still compiles with the registered section
compilers and that no binding changed, writes it, and hands the layout to the pipeline (on_saved) as a new
version, which hot-reloads it when it is live. Both kinds of tweak compile with the registered sections.
"""
from dataclasses import dataclass

from ..domain.issues import DomainInvariantError, LayoutIssue, Severity, SourceRef
from ..domain.layout import ContentHash, LayoutId, TweakRequest
from ..notation.compiler import compile_text
from ..notation.splice import SectionSpliceError, SpliceRefused, plan_splice, splice_section_field
from .ports import LayoutSource, PortCatalog

STALE = "layout changed, reload"


@dataclass(frozen=True)
class Saved:
    hash: ContentHash


@dataclass(frozen=True)
class Stale:
    message: str = STALE


@dataclass(frozen=True)
class Invalid:
    issues: tuple[LayoutIssue, ...]


TweakAnswer = Saved | Stale | Invalid


class TweakService:
    def __init__(self, source: LayoutSource, catalog: PortCatalog | None = None,
                 splice=plan_splice, compile=compile_text, sections=None, on_saved=None):
        self._source = source
        self._catalog = catalog
        self._splice = splice
        self._compile = compile
        self._sections = dict(sections) if sections else None
        self.on_saved = on_saved          # the pipeline's changed(layout id): a saved file is a new version (s39)

    def _compiled(self, text: str, file: str):
        ports = [p.name for p in self._catalog.list()] if self._catalog is not None else None
        if self._sections:
            return self._compile(text, file, ports, sections=self._sections)
        return self._compile(text, file, ports)

    def current_hash(self, layout: LayoutId) -> ContentHash | None:
        read = self._source.read(LayoutId(layout))
        return read[1] if read else None

    def apply(self, request: TweakRequest) -> TweakAnswer:
        read = self._source.read(request.layout)
        if read is None or read[1] != request.base_hash:
            return Stale()
        text, _ = read
        file = f"{request.layout}.yaml"
        try:
            new_text = self._splice(text, request, file, sections=self._sections) if self._sections \
                else self._splice(text, request, file)
        except SpliceRefused as refused:
            return Invalid(refused.issues)
        except DomainInvariantError as error:
            return Invalid((LayoutIssue(Severity.ERROR, SourceRef(file, 1), str(request.control), error.problem,
                                        error.fix, error.joiner),))
        if new_text == text:
            return Saved(read[1])
        result = self._compiled(new_text, file)
        if not result.valid:
            return Invalid(tuple(result.issues))
        self._source.write(request.layout, new_text)
        return Saved(ContentHash.of(new_text))

    # --- module sections (contract 2, s38) -------------------------------------------------------------------
    def save_section_field(self, layout_id, path: str, value, base_hash: ContentHash | None = None) -> TweakAnswer:
        """One field of a module section, e.g. ('tonnetz-c', 'lab.base', 'D3'): Saved, Stale or Invalid."""
        layout_id = LayoutId(layout_id)
        file = f"{layout_id}.yaml"
        read = self._source.read(layout_id)
        if read is None or (base_hash is not None and read[1] != base_hash):
            return Stale()
        text, current = read
        top = str(path).split(".", 1)[0]
        if self._sections is not None and top not in self._sections:
            return Invalid((LayoutIssue(Severity.ERROR, SourceRef(file, 1), str(path),
                                        f"'{top}' is not a module section",
                                        f"use one of: {', '.join(sorted(self._sections))}"),))
        try:
            new_text = splice_section_field(text, path, value)
        except SectionSpliceError as error:
            return Invalid((LayoutIssue(Severity.ERROR, SourceRef(file, error.line), error.field, error.problem,
                                        error.fix),))
        if new_text == text:
            return Saved(current)
        before, after = self._compiled(text, file), self._compiled(new_text, file)
        if not after.valid:
            return Invalid(tuple(after.issues))
        if before.valid and _bindings(before.layout) != _bindings(after.layout):
            return Invalid((LayoutIssue(Severity.ERROR, SourceRef(file, 1), str(path),
                                        "the change would rebind controls too",
                                        "edit the file directly for this change"),))
        self._source.write(layout_id, new_text)
        if self.on_saved is not None:
            self.on_saved(layout_id)
        return Saved(ContentHash.of(new_text))


def _bindings(layout) -> dict:
    found = {}
    for page in layout.pages.values():
        for layer, bindings in page.layers.items():
            for control, binding in bindings.items():
                found[("page", int(page.number), layer, control)] = binding
    for bank in layout.banks.values():
        for layer, bindings in bank.layers.items():
            for control, binding in bindings.items():
                found[("bank", int(bank.number), layer, control)] = binding
    return found
