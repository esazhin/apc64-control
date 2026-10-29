"""PatternSource over a directory of pattern files (patterns/ in the repository, contract 2 §2.10).

A pattern's id is its file name without the extension: travis.yaml is 'travis'. YAML (.yaml, .yml) and JSON
(.json) are read; with two files of one id the YAML one wins. Files are listed and read when asked, so a new or
fixed file counts at once; nothing is cached.

Writing (Phase 2, the page's editor and the API): write(id, text) replaces or creates <id>.yaml (or the id's
existing file) as the host writes layouts: a temporary file, fsync, one rename, so a reader never sees half a file.
The text it replaces, and the text of a file deleted, is kept first as a version under the versions directory
(<state>/pattern-versions/<id>/<UTC stamp>-<hash>.yaml, outside the repository, every one kept), so any write can
be rolled back (versions, version). The application validates every text before it is written.

parse(text, file) reads a pattern's text into plain JSON-compatible data with the line of every place in it, using
the host's YAML parser (every node keeps its line; its syntax issues come back as they are), or json for a .json
file; the application validates the data with the pure performer package.
"""
import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from _apc64_host.domain.issues import LayoutIssue, Severity, SourceRef, in_line_order
from _apc64_host.notation.parser import MapNode, Scalar, SeqNode, parse

SUFFIXES = (".yaml", ".yml", ".json")
VERSION = re.compile(r"^(\d{8}T\d{6}\.\d{3}Z)-([0-9a-f]{12})\.(yaml|json)$")


def text_hash(text: str) -> str:
    """The short content hash the page sends back as the base of a write (stale when the file changed since)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


class PatternFiles:
    def __init__(self, directory, versions=None, now=lambda: datetime.now(UTC)):
        self.directory = Path(directory)
        self.versions_dir = Path(versions) if versions is not None else None
        self._now = now

    def _files(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        try:
            paths = sorted(self.directory.iterdir())
        except OSError:
            return {}
        for suffix in SUFFIXES:
            for path in paths:
                if path.suffix.lower() == suffix and path.is_file() and not path.name.startswith("."):
                    found.setdefault(path.stem, path)
        return found

    def ids(self) -> list[str]:
        return sorted(self._files())

    def read(self, pattern_id: str) -> str | None:
        path = self._files().get(str(pattern_id))
        if path is None:
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def file_name(self, pattern_id: str) -> str:
        path = self._files().get(str(pattern_id))
        return path.name if path is not None else f"{pattern_id}.yaml"

    def parse(self, text: str, file: str):
        return parse_text(text, file)

    # --- writing ------------------------------------------------------------------------------------------
    def write(self, pattern_id: str, text: str) -> str:
        """The pattern's file now holds `text` (created as <id>.yaml when new); the text replaced is kept as a
        version first. Answers the file's name. OSError when it cannot be written."""
        path = self._files().get(str(pattern_id)) or self.directory / f"{pattern_id}.yaml"
        old = self._text(path)
        if old is not None and old != text:
            self._keep(str(pattern_id), old, path.suffix)
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        with open(temporary, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return path.name

    def delete(self, pattern_id: str) -> str | None:
        """The pattern's file removed, its text kept as a version first; its name, or None when there was none."""
        path = self._files().get(str(pattern_id))
        if path is None:
            return None
        old = self._text(path)
        if old is not None:
            self._keep(str(pattern_id), old, path.suffix)
        path.unlink()
        return path.name

    def versions(self, pattern_id: str) -> list[dict]:
        """The kept versions of a pattern, newest first: {version, at, hash}."""
        directory = self._version_dir(pattern_id)
        try:
            names = os.listdir(directory) if directory is not None else []
        except OSError:
            return []
        found = [m for m in (VERSION.match(n) for n in names) if m]
        return [{"version": f"{m.group(1)}-{m.group(2)}", "at": m.group(1), "hash": m.group(2)}
                for m in sorted(found, key=lambda m: m.group(1), reverse=True)]

    def version(self, pattern_id: str, version: str) -> str | None:
        """A kept version's text (its name as versions() lists it, or a unique start of it), or None."""
        directory = self._version_dir(pattern_id)
        if directory is None:
            return None
        matches = [v for v in self.versions(pattern_id) if v["version"].startswith(str(version).strip())]
        if len(matches) != 1 or not str(version).strip():
            return None
        for suffix in ("yaml", "json"):
            text = self._text(directory / f"{matches[0]['version']}.{suffix}")
            if text is not None:
                return text
        return None

    def _version_dir(self, pattern_id: str) -> Path | None:
        if self.versions_dir is None or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", str(pattern_id)):
            return None
        return self.versions_dir / str(pattern_id)

    def _keep(self, pattern_id: str, text: str, suffix: str) -> None:
        directory = self._version_dir(pattern_id)
        if directory is None:
            return
        directory.mkdir(parents=True, exist_ok=True)
        moment = self._now().astimezone(UTC)
        latest = self.versions(pattern_id)
        stamp = _stamp(moment)
        if latest and latest[0]["at"] >= stamp:
            stamp = _stamp(datetime.strptime(latest[0]["at"], "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=UTC)
                           + timedelta(milliseconds=1))
        target = directory / f"{stamp}-{text_hash(text)}.{'json' if suffix == '.json' else 'yaml'}"
        temporary = target.with_name(f".{target.name}.tmp")
        with open(temporary, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)

    @staticmethod
    def _text(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None


def _stamp(moment: datetime) -> str:
    return f"{moment:%Y%m%dT%H%M%S}.{moment.microsecond // 1000:03d}Z"


def parse_text(text: str, file: str):
    """(data or None, {path: line}, syntax issues)."""
    if str(file).lower().endswith(".json"):
        try:
            return json.loads(text), {}, ()
        except ValueError as error:
            return None, {}, (LayoutIssue(Severity.ERROR, SourceRef(file, getattr(error, "lineno", 1)), None,
                                          f"JSON syntax: {getattr(error, 'msg', error)}", "check the commas and the quotes"),)
    parsed = parse(text, file)
    if parsed.root is None or any(i.is_error for i in parsed.issues):
        return None, {}, tuple(in_line_order(parsed.issues))
    lines: dict[tuple, int] = {}
    return _data(parsed.root, (), lines), lines, ()


def _data(node, path: tuple, lines: dict):
    """The parser's tree as plain JSON-compatible data, each path's line kept."""
    lines[path] = node.line
    if isinstance(node, MapNode):
        out = {}
        for entry in node.entries:
            key = _plain(entry.key)
            child = path + (str(key),)
            out[key] = _data(entry.value, child, lines)
            lines[child] = entry.line
        return out
    if isinstance(node, SeqNode):
        return [_data(item, path + (str(k),), lines) for k, item in enumerate(node.items)]
    return _plain(node.value) if isinstance(node, Scalar) else None


def _plain(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    return str(value)
