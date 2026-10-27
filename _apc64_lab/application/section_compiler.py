"""The host SectionCompiler for the layout's 'lab:' section (contract s4 supplier side, T22).

It delegates to the pure lab_section.compile_lab_section with the registry's working generators and schemes,
so the result shape is the domain's: a LabDefinition plus the implied base-layer encoder/Tempo ModuleAction
bindings, or LayoutIssues. Two additions:
- §2.7 q2: with a lab-wide default NoteTarget configured, a valid section also implies the Custom-port routing
  rule to it (and its device). The host compiler keeps a layout's own 'routing: custom:' line instead: that is
  the per-layout override. With neither, Custom-view notes are only shown.
- every valid definition is reported to `on_compiled(layout id, definition)`, so the lab knows the generated
  layouts (the library listing and push by layout) without asking the host's library.
"""
from dataclasses import replace
from pathlib import PurePath
from typing import Callable, Mapping

from _apc64_host.domain.layout import DeviceName, LayoutId, SectionEntry, SectionResult, UnitPortRole

from ..domain.lab_section import LabDefinition, compile_lab_section
from ..domain.note_target import NoteTarget


def layout_id_of_file(file: str) -> LayoutId:
    return LayoutId(PurePath(str(file)).stem)


class LabSectionCompiler:
    def __init__(self, generators: Callable[[], Mapping], schemes: Callable[[], Mapping],
                 target: NoteTarget | None = None,
                 on_compiled: Callable[[LayoutId, LabDefinition], None] | None = None):
        self._generators, self._schemes = generators, schemes
        self.target = target
        self._on_compiled = on_compiled

    def compile(self, section: SectionEntry, file: str, existing) -> SectionResult:
        result = compile_lab_section(section, file, existing, self._generators(), self._schemes())
        if result.value is None or any(issue.is_error for issue in result.issues):
            return result
        if self._on_compiled is not None:
            try:
                self._on_compiled(layout_id_of_file(file), result.value)
            except Exception:   # the index is a convenience; compiling never fails because of it
                pass
        if self.target is None:
            return result
        return replace(result, routing={UnitPortRole.CUSTOM: self.target.rule()},
                       devices={DeviceName(self.target.device): self.target.declaration()})
