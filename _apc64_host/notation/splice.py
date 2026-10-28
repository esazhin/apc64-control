"""plan_splice: save a single-control tweak as one entry line of the agent's own file (contract inv21, a9).

The document is never re-dumped. The tweak becomes one single-control entry in the notation's own phrase
form ('pad r1c3: note 38 on mpc ch 1 colour red') that overrides any range covering the control:

- the control already has its own entry → that entry is replaced (its trailing comment kept);
- it has none → one line is inserted after the last entry of that page/bank layer (a 'shift:' block is
  added when the layer has none yet);
- the tweak makes the control equal to what its range gives → its own entry is removed (d173), so a
  tweak and its undo leave the file byte-identical (A137).

Every other line stays byte-identical. The new text is compiled before it is returned; a result that would
be invalid, or that changed any other control's meaning, is refused with SpliceRefused(issues).
"""
from dataclasses import replace

from ..domain.controls import ControlId, Strip
from ..domain.issues import LayoutIssue, Severity, SourceRef
from ..domain.layout import (
    Action, Binding, Fixed, Layer, Layout, MessageKind, StripBinding, ToggleState, TweakField, TweakRequest,
)
from ..domain.leds import StripBarStyle
from ..domain.palette import WHITE
from .compiler import CompileResult, compile_text
from .compiler import compile_text as _compile_text
from .grammar import BindingSpec, FeedbackSpec, MessageSpec, PhraseError, parse_phrase, render_phrase, yaml_scalar


class SpliceRefused(Exception):
    """The tweak cannot be saved; issues say why, in the same form as validation."""

    def __init__(self, issues):
        self.issues = tuple(issues)
        super().__init__("; ".join(i.message() for i in self.issues))


# --- domain binding → the phrase it is written as ------------------------------------------------------
def _message_spec(action: Action, toggle: bool) -> MessageSpec:
    spec = MessageSpec(action.kind, None if action.number is None else str(action.number),
                       device=str(action.device), channel=int(action.channel))
    if action.kind is MessageKind.CC and isinstance(action.value, Fixed) and action.value.value != 127 and not toggle:
        spec.value = int(action.value.value)
    if action.kind is MessageKind.CC14 and action.lsb != action.number + 32:
        spec.lsb = int(action.lsb)
    return spec


def _feedback_spec(rule, first: Action) -> FeedbackSpec:
    colours = [(v, str(c)) for v, c in rule.colours]
    echo = (rule.device == first.device and rule.kind is first.kind and rule.number == first.number
            and rule.channel == first.channel)
    if echo:
        return FeedbackSpec(colours=colours)
    return FeedbackSpec(rule.kind, str(rule.number), str(rule.device),
                        None if rule.channel is None else int(rule.channel), colours)


def spec_of(binding: Binding | StripBinding) -> BindingSpec:
    """The BindingSpec that compiles back to this binding (used to write a tweak in the file's notation)."""
    if isinstance(binding, StripBinding):
        return BindingSpec(
            [_message_spec(binding.position, False)],
            colour=None if binding.colour == WHITE else str(binding.colour),
            label=binding.label,
            feedback=_feedback_spec(binding.feedback, binding.position) if binding.feedback else None,
            off_colour=str(binding.feedback.off_colour) if binding.feedback and binding.feedback.off_colour else None,
            touch=_message_spec(binding.touch, False) if binding.touch else None,
            style="bipolar" if binding.style is StripBarStyle.BIPOLAR else None)
    first = binding.actions[0]
    spec = BindingSpec([_message_spec(a, binding.toggle) for a in binding.actions],
                       toggle=True if binding.toggle else None,
                       colour=str(binding.colour) if binding.colour else None, label=binding.label)
    if binding.toggle and isinstance(first.value, ToggleState) and (first.value.values.on, first.value.values.off) \
            != (127, 0):
        spec.toggle_values = (int(first.value.values.on), int(first.value.values.off))
    if not binding.toggle and first.kind is MessageKind.NOTE and isinstance(first.value, Fixed):
        spec.velocity = int(first.value.value)
    if binding.feedback is not None:
        spec.feedback = _feedback_spec(binding.feedback, first)
        if binding.feedback.off_colour is not None:
            spec.off_colour = str(binding.feedback.off_colour)
    return spec


def _tweaked(old: BindingSpec | None, request: TweakRequest) -> BindingSpec:
    """The control's new spec: the old one with one field changed."""
    value = None if request.value is None or str(request.value).strip() == "" else str(request.value).strip()
    if request.field is TweakField.ASSIGNMENT:
        if value is None:
            return BindingSpec(none=True)
        new = parse_phrase(value)
        if old is not None and not new.none:   # options the new phrase does not state are kept
            for name in ("toggle", "toggle_values", "colour", "label", "velocity", "feedback", "off_colour", "touch",
                         "style"):
                if getattr(new, name) is None and getattr(old, name) is not None:
                    setattr(new, name, getattr(old, name))
        return new
    if old is None or old.none:
        raise PhraseError("the control has no binding to change", "give it an assignment first")
    if request.field is TweakField.LABEL:
        return replace(old, label=value)
    if request.field is TweakField.COLOUR:
        return replace(old, colour=None if value is None else value.replace(" ", ""))
    return replace(old, toggle=True if value == "toggle" else None, toggle_values=None)


# --- the splice ----------------------------------------------------------------------------------------
def _scope(request: TweakRequest) -> tuple[str, int]:
    return ("page", int(request.page)) if request.page is not None else ("bank", int(request.bank))


def _binding_at(layout: Layout, request: TweakRequest):
    scope, number = _scope(request)
    holder = layout.page(number) if scope == "page" else layout.bank(number)
    return holder, (holder.binding(request.layer, request.control) if holder else None)


def _comment_of(line: str) -> str:
    """The trailing ' # comment' of a line, found outside quotes ('' when there is none)."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and i > 0 and line[i - 1] in " \t":
            return "  " + line[i:].rstrip("\n")
    return ""


def _refused(file: str, line: int, control: ControlId, problem: str, fix: str) -> SpliceRefused:
    return SpliceRefused([LayoutIssue(Severity.ERROR, SourceRef(file, line), str(control), problem, fix)])


def _all_bindings(layout: Layout) -> dict:
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


def plan_splice(text: str, request: TweakRequest, file: str = "layout.yaml", sections=None) -> str:
    """The layout text with only the tweaked control's own entry inserted, replaced or removed. `sections`: the
    registered module section compilers (contract 2), so a file with a module section compiles as it does live."""
    def compile_text(text, file, ports=None):
        return _compile_text(text, file, ports, sections)
    before = compile_text(text, file)
    if not before.valid:
        raise SpliceRefused(before.issues)
    scope, number = _scope(request)
    holder, current = _binding_at(before.layout, request)
    key = (scope, number, request.layer, request.control)
    name = before.file
    if holder is None:
        raise _refused(name, 1, request.control, f"{scope} {number} is not in the layout",
                       f"add '{number}:' under {scope}s in the file first")
    if (scope == "bank") != isinstance(request.control, Strip):
        raise _refused(name, 1, request.control, f"{request.control} is not bound in {scope}s",
                       "tweak strips on a bank and pads/buttons on a page")
    try:
        new_spec = _tweaked(spec_of(current) if current is not None else None, request)
    except PhraseError as error:
        raise _refused(name, 1, request.control, error.problem, error.fix) from None
    lines = text.splitlines(keepends=True)
    own = before.sources.singles.get(key)
    from_range = before.sources.from_ranges.get(key)
    if new_spec.none and from_range is None:
        candidate = _remove(lines, own) if own else text   # nothing else binds it: drop the entry
    else:
        entry = f"{request.control}: {yaml_scalar(render_phrase(new_spec))}"
        candidate = _replace(lines, own, entry) if own else _insert(lines, before, request, entry, name)
    after = compile_text(candidate, file)
    if not after.valid:
        raise SpliceRefused(after.issues)
    _, new_binding = _binding_at(after.layout, request)
    if own is not None and new_binding == from_range and not new_spec.none:
        candidate = _remove(lines, own)   # back to what the range says: the override goes (d173)
        after = compile_text(candidate, file)
    elif own is None and new_binding == current:
        return text                       # nothing changes
    _check_only_target_changed(before, after, key, name, request.control)
    return candidate


def _check_only_target_changed(before: CompileResult, after: CompileResult, key, file: str, control):
    old, new = _all_bindings(before.layout), _all_bindings(after.layout)
    changed = {k for k in old.keys() | new.keys() if old.get(k) != new.get(k)} - {key}
    if changed:
        raise _refused(file, 1, control, "the tweak would change other controls too",
                       "edit the file directly for this change")


def _replace(lines: list[str], own, entry: str) -> str:
    first = lines[own.line - 1]
    indent = first[:len(first) - len(first.lstrip())]
    ending = "\n" if lines[own.end_line - 1].endswith("\n") else ""
    keep = _comment_of(first) if own.end_line == own.line else ""
    head = f"{indent}{own.key}:" + entry.split(":", 1)[1]
    return "".join(lines[:own.line - 1] + [head + keep + ending] + lines[own.end_line:])


def _remove(lines: list[str], own) -> str:
    return "".join(lines[:own.line - 1] + lines[own.end_line:])


def _insert(lines: list[str], before: CompileResult, request: TweakRequest, entry: str, file: str) -> str:
    scope, number = _scope(request)
    block = before.sources.blocks.get((scope, number, request.layer))
    base = before.sources.blocks[(scope, number, Layer.BASE)]
    if base.flow or (block is not None and block.flow):
        raise _refused(file, base.line, request.control, f"{scope} {number} is written on one line",
                       "write it as a block (one entry per line) to tweak it from the page")
    body_column = base.entry_column if base.entry_column is not None else base.column + 2
    if block is not None and block.entries:
        new = [" " * block.entry_column + entry + "\n"]
        at = block.end_line
    elif block is not None and request.layer is Layer.BASE:
        new = [" " * body_column + entry + "\n"]
        at = block.line
    elif block is not None:   # an empty 'shift:' block
        new = [" " * (block.column + 2) + entry + "\n"]
        at = block.line
    else:                     # no 'shift:' yet: add one at the end of the page body
        new = [" " * body_column + "shift:\n", " " * (body_column + 2) + entry + "\n"]
        at = base.end_line
    if at > 0 and at <= len(lines) and not lines[at - 1].endswith("\n"):
        lines = lines[:at - 1] + [lines[at - 1] + "\n"] + lines[at:]
    return "".join(lines[:at] + new + lines[at:])


# --- module-owned sections (contract 2, s38) ----------------------------------------------------------------
class SectionSpliceError(ValueError):
    """A section field that cannot be spliced, with the line to point at and how to fix it."""

    def __init__(self, line: int, field: str, problem: str, fix: str):
        self.line, self.field, self.problem, self.fix = line, field, problem, fix
        super().__init__(problem)


def _value_text(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_value_text(v) for v in value) + "]"
    return yaml_scalar(str(value))


def _content(line: str) -> str:
    """The line without its comment and line end; '' for a blank or comment-only line."""
    body = line.rstrip("\n")
    comment = _comment_of(body)              # '  # …': two spaces, then the line from its '#'
    if comment:
        body = body[:len(body) - (len(comment) - 2)]
    stripped = body.strip()
    return "" if not stripped or stripped.startswith("#") else body.rstrip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _key_of(content: str) -> str | None:
    head = content.strip()
    if ":" not in head or head.startswith(("-", "{", "[")):
        return None
    return head.split(":", 1)[0].strip().strip("'\"")


def splice_section_field(text: str, path: str, value, comment: str | None = None) -> str:
    """The text with one field of a block-style section set: 'lab.base' → the 'base:' line under 'lab:' gets
    the new value (its comment kept, or replaced by `comment` when one is given: a comment that describes the
    value would otherwise go stale), or a new line is added at the end of the section. Only that one line
    changes; anything else is refused with a SectionSpliceError."""
    parts = [p for p in str(path).split(".") if p]
    if len(parts) < 2:
        raise SectionSpliceError(1, str(path), f"'{path}' names no field of a section", "write e.g. 'lab.base'")
    lines = text.splitlines(keepends=True)
    start, end, parent_indent, parent_line = 0, len(lines), -1, 0
    for depth, part in enumerate(parts):
        found = None
        child_indent = None
        for i in range(start, end):
            content = _content(lines[i])
            if not content:
                continue
            indent = _indent(lines[i])
            if indent <= parent_indent:
                break
            if child_indent is None:
                child_indent = indent
            if indent == child_indent and (_key_of(content) or "").lower() == part.lower():
                found = i
                break
        last = depth == len(parts) - 1
        if found is None:
            if not last:
                raise SectionSpliceError(parent_line + 1, ".".join(parts[:depth + 1]),
                                         f"the layout has no '{'.'.join(parts[:depth + 1])}:'",
                                         f"add '{part}:' to the file first")
            indent = child_indent if child_indent is not None else parent_indent + 2
            at = end
            while at > start and not _content(lines[at - 1]):
                at -= 1                               # after the section's last entry, before blank lines
            if at > 0 and not lines[at - 1].endswith("\n"):
                lines[at - 1] += "\n"
            note = f"  # {comment}" if comment else ""
            lines.insert(at, " " * indent + f"{part}: {_value_text(value)}{note}\n")
            return "".join(lines)
        content = _content(lines[found])
        rest = content.split(":", 1)[1].strip()
        if not last:
            if rest:
                raise SectionSpliceError(found + 1, ".".join(parts[:depth + 1]),
                                         f"'{parts[depth]}' is written inline",
                                         "write the section as an indented block to tweak it from the page")
            start, parent_indent, parent_line = found + 1, _indent(lines[found]), found
            end = len(lines)
            for j in range(start, len(lines)):
                if _content(lines[j]) and _indent(lines[j]) <= parent_indent:
                    end = j
                    break
            continue
        nested = found + 1 < len(lines) and _content(lines[found + 1]) and _indent(lines[found + 1]) > _indent(lines[found])
        if not rest and nested:
            raise SectionSpliceError(found + 1, str(path), f"'{path}' holds a block, not one value",
                                     "tweak one of its fields instead")
        line = lines[found]
        note = _comment_of(line) if comment is None else (f"  # {comment}" if comment else "")
        if rest == _value_text(value) and note == _comment_of(line):
            return text                               # already so: the file stays byte for byte
        ending = "\n" if line.endswith("\n") else ""
        key = content.strip().split(":", 1)[0]
        lines[found] = " " * _indent(line) + f"{key}: {_value_text(value)}{note}{ending}"
        return "".join(lines)
    raise SectionSpliceError(1, str(path), f"'{path}' was not found", "check the field path")
