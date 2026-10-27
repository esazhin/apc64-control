"""YAML text → a syntax tree whose every node carries its source line (ruamel.yaml round-trip, parse only).

Syntax problems become LayoutIssues with the file, line, problem and fix. A line that names a control but
lacks the ':' after it is found before YAML sees it (contract A38) and parsing goes on as if the ':' were
there, so every other error in the file is still reported (d113).
"""
from dataclasses import dataclass

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.constructor import DuplicateKeyError
from ruamel.yaml.error import MarkedYAMLError

from ..domain.issues import LayoutIssue, Severity, SourceRef
from .grammar import loose_control_line


@dataclass(frozen=True)
class Scalar:
    value: object
    line: int


@dataclass(frozen=True)
class Entry:
    key: object
    line: int          # the key's line (1-based)
    column: int        # the key's column (0-based)
    value: "Node"


@dataclass(frozen=True)
class MapNode:
    entries: tuple[Entry, ...]
    line: int
    flow: bool = False

    def get(self, key: str) -> Entry | None:
        return next((e for e in self.entries if str(e.key).lower() == key), None)


@dataclass(frozen=True)
class SeqNode:
    items: tuple["Node", ...]
    line: int


Node = Scalar | MapNode | SeqNode


@dataclass(frozen=True)
class Parsed:
    file: str
    text: str
    root: Node | None
    issues: tuple[LayoutIssue, ...]

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.allow_duplicate_keys = False
    return yaml


def _tree(data, line: int) -> Node:
    if isinstance(data, CommentedMap):
        entries = []
        for key, value in data.items():
            key_line, key_col = data.lc.key(key)
            value_line = data.lc.value(key)[0] if not isinstance(value, (CommentedMap, CommentedSeq)) else (
                value.lc.line)
            entries.append(Entry(key, key_line + 1, key_col, _tree(value, value_line + 1)))
        return MapNode(tuple(entries), data.lc.line + 1, bool(data.fa.flow_style()))
    if isinstance(data, CommentedSeq):
        items = []
        for i, value in enumerate(data):
            item_line = data.lc.item(i)[0] + 1
            items.append(_tree(value, item_line))
        return SeqNode(tuple(items), data.lc.line + 1)
    return Scalar(data, line)


_HINTS = {
    "mapping values are not allowed": 'a value contains ": "; put it in quotes, e.g. label: "A: B"',
    "found character '\\t'": "indent with spaces, not tabs",
    "could not find expected ':'": "write each entry as '<control>: <binding>'",
    "expected <block end>": "line up the entries of one block at the same indentation",
    "found undefined alias": "remove the '*' or quote the value",
    "while scanning a quoted scalar": "close the quotes",
}


def _syntax_issue(file: str, error: MarkedYAMLError) -> LayoutIssue:
    if isinstance(error, DuplicateKeyError):
        first, second = error.context_mark.line + 1, error.problem_mark.line + 1
        key = str(error.problem).split('"')[1] if '"' in str(error.problem) else "a key"
        return LayoutIssue(Severity.ERROR, SourceRef(file, second), key,
                           f"lines {first} and {second} both say {key}", "keep one")
    mark = error.problem_mark or error.context_mark
    problem = str(error.problem or error.context or "not valid YAML").strip()
    fix = next((hint for text, hint in _HINTS.items() if text in problem or text in str(error.context or "")),
               "check the indentation and the ':' after each key")
    return LayoutIssue(Severity.ERROR, SourceRef(file, (mark.line + 1) if mark else 1), None,
                       f"YAML syntax: {problem}", fix)


def parse(text: str, file: str) -> Parsed:
    """Parse layout text. Never raises: problems come back as issues, with the tree when one could be built."""
    issues = []
    lines = text.splitlines(keepends=True)
    for number, line in enumerate(lines, start=1):
        loose = loose_control_line(line)
        if loose is not None:
            control, rest = loose
            issues.append(LayoutIssue(Severity.ERROR, SourceRef(file, number), control,
                                      "expected ':' after the control name", f'write "{control}: {rest}"'))
            lines[number - 1] = line.replace(control, control + ":", 1)
        if "\t" in line[:len(line) - len(line.lstrip())]:
            issues.append(LayoutIssue(Severity.ERROR, SourceRef(file, number), None,
                                      "this line is indented with a tab", "indent with spaces, not tabs"))
            lines[number - 1] = line.replace("\t", "    ")
    try:
        data = _yaml().load("".join(lines))
    except MarkedYAMLError as error:
        issue = _syntax_issue(file, error)
        if not any(i.source.line == issue.source.line for i in issues):
            issues.append(issue)
        return Parsed(file, text, None, tuple(issues))
    if data is None:
        issues.append(LayoutIssue(Severity.ERROR, SourceRef(file, 1), None, "the layout is empty",
                                  "start with 'name:', 'devices:' and 'pages:' (see docs/layout-guide.md)"))
        return Parsed(file, text, None, tuple(issues))
    return Parsed(file, text, _tree(data, 1), tuple(issues))
