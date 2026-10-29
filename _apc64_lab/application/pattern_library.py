"""PatternLibrary: the performer patterns in patterns/, read and validated with their file lines (contract 2 §2.10).

A pattern file is YAML (or JSON) whose data is the pure performer format (docs/performer-format.md). The source
(infrastructure) reads each into plain data with the line of every place in it; this service hands the data to
performer.parse_pattern and turns each issue's place in the data back into a line (`travis.yaml line 7, lane 2:
7 steps; length is 8; …`), as LayoutIssues, in the text the layout validator uses. Files are read when asked (a
list, a choice), so a pattern saved or fixed is seen at once.

Writing (Phase 2: the page's editor, the API and the CLI). save(id, text= or data=) validates first and writes only
a valid pattern: text as given (an agent's file), or data written as canonical YAML (pattern_text: the canonical
form with a short header comment, rows in the grid notation with a | at every bar). The page sends the hash of the
text it read as `base`: a file changed since is refused (stale), as the host refuses a stale layout tweak; `create`
refuses an existing id (New, Save as). delete refuses a pattern a layout's performer block names. The source keeps
every replaced or deleted text as a version, so restore(id, version) rolls a write back.
"""
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable

from _apc64_host.domain.issues import LayoutIssue, Severity, SourceRef, in_line_order
from performer import RELATIVE, Pattern, check_pattern, lane_order, to_data
from performer.pattern import CELL_TEXT, STRUM_TEXT

from ..domain.performer_block import find_pattern
from .ports import PatternSource


@dataclass(frozen=True)
class PatternResult:
    """A file compiled: the pattern (None when invalid) and every issue, errors first in line order."""
    file: str
    pattern: Pattern | None
    issues: tuple[LayoutIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return self.pattern is not None

    @property
    def errors(self) -> tuple[LayoutIssue, ...]:
        return tuple(i for i in self.issues if i.is_error)

    @property
    def warnings(self) -> tuple[LayoutIssue, ...]:
        return tuple(i for i in self.issues if not i.is_error)


def compile_parsed(parsed, file: str) -> PatternResult:
    """(data, {path: line}, syntax issues) from PatternSource.parse → the pattern with its issues at their lines."""
    data, lines, syntax = parsed
    if syntax or data is None:
        return PatternResult(file, None, tuple(in_line_order(syntax)))
    pattern, issues = check_pattern(data)
    found = [LayoutIssue(Severity.ERROR if i.is_error else Severity.WARNING, SourceRef(file, _line(lines, i.path)),
                         i.field, i.problem, i.fix) for i in issues]
    return PatternResult(file, pattern, tuple(in_line_order(found)))


def _line(lines: dict, path: tuple) -> int:
    path = tuple(path)
    while path and path not in lines:
        path = path[:-1]
    return lines.get(path, 1)


def pattern_json(pattern_id: str, pattern: Pattern, lanes: int | None = None) -> dict:
    """A pattern as the page and the API show it: its canonical data, and the grid as cells (the editor edits the
    same `data`). `lanes`: show lanes 1…lanes (a guitar's strings), manual ones marked; else the pattern's own
    numbered lanes; then R and A (the lanes that follow the chord), written or not."""
    bar = pattern.bar_steps
    numbered = range(1, lanes + 1) if lanes else sorted({lane for lane, _ in pattern.lanes if isinstance(lane, int)}
                                                        | set(pattern.manual))
    shown = [*numbered, *RELATIVE]
    return {"id": pattern_id, "name": pattern.name, "description": pattern.description, "meter": str(pattern.meter),
            "step": pattern.step, "length": pattern.length, "play": pattern.play,
            "bar": int(bar) if bar.denominator == 1 else None,
            "lanes": [{"lane": lane, "manual": lane in pattern.manual,
                       "cells": "".join(CELL_TEXT[c] for c in pattern.cells(lane)) if lane not in pattern.manual else ""}
                      for lane in shown],
            "strum": "".join(STRUM_TEXT[m] for m in pattern.strum) if pattern.strum is not None else None,
            "data": to_data(pattern), "warnings": [w.text() for w in pattern.warnings]}


PATTERN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
ID_FIX = "a pattern's file name is 1–40 lower-case letters, digits and -, e.g. my-pick"


def content_hash(text: str) -> str:
    """The hash a reader sends back as the base of a write (a file changed since is stale)."""
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]


def id_for(name: str) -> str:
    """A file name for a pattern's name: 'Travis pick 2' → 'travis-pick-2'."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")[:40].strip("-")
    return slug or "pattern"


class PatternRefused(Exception):
    """A write, delete or restore refused: the HTTP status, the problem and its fix, and the issues of an invalid
    pattern ({field, problem, fix, text, line} each, in order)."""

    def __init__(self, status: int, problem: str, fix: str | None = None, issues=(), code: str | None = None):
        self.status, self.problem, self.fix, self.issues, self.code = status, problem, fix, list(issues), code
        super().__init__(problem)

    def to_json(self) -> dict:
        first = self.issues[0] if self.issues else {}
        return {"problem": self.problem, "fix": self.fix, "issues": self.issues, "field": first.get("field"),
                "line": first.get("line"), "text": first.get("text") or (f"{self.problem}; {self.fix}" if self.fix
                                                                         else self.problem),
                **({"code": self.code} if self.code else {})}


def _scalar(value) -> str:
    """A YAML scalar: plain when it reads back as the same text, else double-quoted (JSON's escapes)."""
    text = str(value)
    plain = (text and text == text.strip() and not re.search(r":\s|\s#|[\n\t\"']|:$", text)
             and text[0] not in "-?:,[]{}#&*!|>'\"%@`" and not re.fullmatch(r"[-+]?[\d.]+([eE][-+]?\d+)?", text)
             and text.lower() not in ("true", "false", "yes", "no", "on", "off", "null", "~"))
    return text if plain else json.dumps(text, ensure_ascii=False)


def _number(value) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def pattern_text(pattern: Pattern, file: str = "pattern.yaml") -> str:
    """The pattern as a file: canonical YAML with a header comment (canonical JSON for a .json file)."""
    data = to_data(pattern)
    if str(file).lower().endswith(".json"):
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    head = f"# {pattern.name}" + (f": {pattern.description}" if pattern.description else "")
    lines = [head[:117] + ("…" if len(head) > 117 else ""),
             "# Written by the pattern editor; the format: docs/performer-format.md (canonical: every default shown).",
             f"format: {data['format']}", f"name: {_scalar(data['name'])}"]
    if "description" in data:
        lines.append(f"description: {_scalar(data['description'])}")
    lines += [f"meter: {data['meter']}", f"step: {data['step']}", f"length: {data['length']}", "lanes:"]
    lines += [f"  {lane}: {row}" for lane, row in sorted(data["lanes"].items(), key=lambda item: lane_order(
        item[0] if item[0] in RELATIVE else int(item[0])))]
    if "strum" in data:
        lines += [f"strum: {data['strum']}", f"spread: {_number(data['spread'])}"]
    gate = data["gate"]
    lines += [f"swing: {_number(data['swing'])}", f"play: {data['play']}",
              f"gate: {gate if isinstance(gate, str) else _number(gate)}",
              f"velocity: {{hit: {data['velocity']['hit']}, accent: {data['velocity']['accent']}}}",
              f"humanize: {{timing: {_number(data['humanize']['timing'])}, velocity: {data['humanize']['velocity']}}}",
              f"manual: [{', '.join(map(str, data['manual']))}]"]
    return "\n".join(lines) + "\n"


def data_issues(issues, file: str) -> list[dict]:
    """Issues of pattern data (no file lines): {field, path, problem, fix, text, line None, severity}."""
    return [{"field": i.field, "path": list(i.path), "problem": i.problem, "fix": i.fix, "text": i.text(file),
             "line": None, "severity": i.severity} for i in issues]


def file_issues(issues) -> list[dict]:
    return [{"field": i.control, "path": None, "problem": i.problem, "fix": i.fix, "text": i.message(),
             "line": i.source.line, "severity": str(i.severity)} for i in issues]


class PatternLibrary:
    def __init__(self, source: PatternSource, users: Callable[[str], list[str]] | None = None):
        self._source = source
        self._compiled: dict[str, tuple[str, PatternResult]] = {}    # id → (the text compiled, its result)
        self.users = users or (lambda pattern_id: [])                # the layouts whose performer names a pattern

    def compile_text(self, text: str, file: str) -> PatternResult:
        """Any pattern text (the API's validate, the CLI's offline fallback), compiled as a file of that name."""
        if not str(text).strip():
            return PatternResult(file, None, (LayoutIssue(Severity.ERROR, SourceRef(file, 1), None,
                                                          "the pattern is empty",
                                                          "start with 'name:' and 'lanes:' (docs/performer-format.md)"),))
        return compile_parsed(self._source.parse(text, file), file)

    def compiled(self) -> dict[str, PatternResult]:
        """Every pattern file by id (its file name without the extension), read now."""
        out = {}
        for pattern_id in self._source.ids():
            text = self._source.read(pattern_id)
            if text is None:
                continue
            known = self._compiled.get(pattern_id)
            if known is None or known[0] != text:                      # compiled again only when the file changed
                known = (text, self.compile_text(text, self._source.file_name(pattern_id)))
                self._compiled[pattern_id] = known
            out[pattern_id] = known[1]
        return out

    def names(self) -> dict[str, str]:
        """{id: name} of the valid patterns (a layout's performer block names one of them)."""
        return {pattern_id: result.pattern.name for pattern_id, result in self.compiled().items() if result.valid}

    def listing(self) -> list[dict]:
        rows = []
        for pattern_id, result in sorted(self.compiled().items()):
            if result.valid:
                p = result.pattern
                rows.append({"id": pattern_id, "name": p.name, "meter": str(p.meter), "step": p.step,
                             "length": p.length, "play": p.play, "valid": True, "file": result.file})
            else:
                rows.append({"id": pattern_id, "name": pattern_id, "valid": False, "file": result.file,
                             "error": result.errors[0].message() if result.errors else "invalid"})
        return rows

    def find(self, name: str) -> tuple[str, PatternResult] | None:
        """The pattern a name names (an id, a file name or a display name), valid or not."""
        compiled = self.compiled()
        named = {pattern_id: (r.pattern.name if r.valid else None) for pattern_id, r in compiled.items()}
        pattern_id = find_pattern(name, named)
        return (pattern_id, compiled[pattern_id]) if pattern_id is not None else None

    def get(self, name: str) -> tuple[str, Pattern] | None:
        found = self.find(name)
        if found is None or not found[1].valid:
            return None
        return found[0], found[1].pattern

    # --- writing (Phase 2) ----------------------------------------------------------------------------------
    def read(self, pattern_id: str) -> tuple[str, str] | None:
        """(the file's text, its hash), or None."""
        text = self._source.read(pattern_id)
        return (text, content_hash(text)) if text is not None else None

    def check_data(self, data, file: str = "pattern.yaml") -> tuple[Pattern, list[dict]]:
        """Pattern data validated: (the pattern, its warnings), or PatternRefused with every issue."""
        pattern, issues = check_pattern(data)
        if pattern is None:
            listed = data_issues(issues, file)
            errors = [i for i in listed if i["severity"] == "error"]
            raise PatternRefused(400, errors[0]["text"] if errors else "not a pattern", None, listed, "invalid")
        return pattern, data_issues(issues, file)

    def save(self, pattern_id: str, *, text: str | None = None, data=None, base: str | None = None,
             create: bool = False) -> dict:
        """Validate, then write the pattern as `pattern_id` (the module text). PatternRefused when refused."""
        pattern_id = self._id(pattern_id)
        current = self._source.read(pattern_id)
        exists = pattern_id in self._source.ids()
        file = self._source.file_name(pattern_id) if exists else f"{pattern_id}.yaml"
        if create and exists:
            raise PatternRefused(409, f"patterns/{file} exists", "choose another name, or save over it", code="exists")
        if base is not None and (current is None or content_hash(current) != str(base)):
            raise PatternRefused(409, f"patterns/{file} changed on disk since it was read",
                                 "reload it, then make the change again", code="stale")
        if (text is None) == (data is None):
            raise PatternRefused(400, "send the pattern as text or as data", None, code="invalid")
        if data is not None:
            pattern, _ = self.check_data(data, file)
            text = pattern_text(pattern, file)
        result = self.compile_text(text, file)
        if not result.valid:
            listed = file_issues(result.issues)
            raise PatternRefused(400, listed[0]["text"], None, listed, "invalid")
        if text != current:
            try:
                self._source.write(pattern_id, text)
            except OSError as error:
                raise PatternRefused(500, f"could not write patterns/{file} ({error.strerror or error})",
                                     "check the directory's permissions", code="storage") from None
        self._compiled.pop(pattern_id, None)
        verb = "unchanged" if text == current else "created" if current is None else "saved"
        return {"id": pattern_id, "file": file, "hash": content_hash(text), "created": current is None,
                "pattern": pattern_json(pattern_id, result.pattern),
                "warnings": [w["text"] for w in file_issues(result.warnings)],
                "message": f"{verb} patterns/{file}" + (f" ({result.pattern.name})" if verb != "unchanged" else "")}

    def delete(self, pattern_id: str, base: str | None = None) -> dict:
        found = self.find(pattern_id)
        if found is None:
            raise PatternRefused(404, f'no pattern "{pattern_id}"', "available: " + ", ".join(self._source.ids()),
                                 code="not_found")
        pattern_id, result = found
        users = self.users(pattern_id)
        if users:
            raise PatternRefused(409, f"{', '.join(users)} play{'s' if len(users) == 1 else ''} {result.file} "
                                 "(the layout's performer block)", "change the layout's performer block first",
                                 code="in_use")
        current = self._source.read(pattern_id)
        if base is not None and (current is None or content_hash(current) != str(base)):
            raise PatternRefused(409, f"patterns/{result.file} changed on disk since it was read",
                                 "reload it before deleting", code="stale")
        try:
            gone = self._source.delete(pattern_id)
        except OSError as error:
            raise PatternRefused(500, f"could not delete patterns/{result.file} ({error.strerror or error})",
                                 code="storage") from None
        self._compiled.pop(pattern_id, None)
        kept = self._source.versions(pattern_id)
        return {"id": pattern_id, "file": gone,
                "message": f"deleted patterns/{gone}" + (f"; kept as version {kept[0]['version']}" if kept else "")}

    def versions(self, pattern_id: str) -> list[dict]:
        return self._source.versions(self._id(pattern_id))

    def restore(self, pattern_id: str, version: str) -> dict:
        """A kept version written back (validated first; the text it replaces is kept in turn)."""
        pattern_id = self._id(pattern_id)
        text = self._source.version(pattern_id, version)
        if text is None:
            listed = [v["version"] for v in self._source.versions(pattern_id)]
            raise PatternRefused(404, f'no version "{version}" of {pattern_id}',
                                 ("versions: " + ", ".join(listed[:5])) if listed else "no versions are kept",
                                 code="not_found")
        answer = self.save(pattern_id, text=text)
        return {**answer, "message": f"restored patterns/{answer['file']} from version {version}"}

    def _id(self, pattern_id) -> str:
        text = str(pattern_id or "").strip()
        for suffix in (".yaml", ".yml", ".json"):
            text = text.removesuffix(suffix)
        if not PATTERN_ID.match(text):
            raise PatternRefused(400, f"'{pattern_id}' is not a pattern file name", ID_FIX, code="invalid")
        return text


def users_of(pattern_id: str, layouts, names: dict) -> list[str]:
    """The layouts (IndexedLayout: name and definition) whose performer block plays the pattern or holds it in a
    slot; `names`: {id: name} of the patterns."""
    from ..domain.performer_block import find_pattern
    found = []
    for layout in layouts:
        settings = getattr(layout.definition, "performer", None)
        if settings is None:
            continue
        wanted = [settings.pattern, *[slot for slot in getattr(settings, "slots", ()) if slot]]
        if any(find_pattern(name, names) == pattern_id for name in wanted):
            found.append(layout.name)
    return sorted(found)
