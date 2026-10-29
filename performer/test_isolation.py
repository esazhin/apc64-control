"""The performer is shared with other projects: standard library only, nothing of the APC64, no clock or thread."""
import ast
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
STDLIB = set(sys.stdlib_module_names)
NOT_IN_A_PURE_CORE = {"threading", "time", "asyncio", "socket", "subprocess", "multiprocessing", "os"}


def _imports(path: Path):
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield "performer" if node.level else node.module


def _sources():
    return [p for p in PACKAGE.rglob("*.py") if not p.name.startswith("test_")]


def test_the_performer_imports_only_the_standard_library_and_itself():
    sources = _sources()
    assert {p.name for p in sources} >= {"__init__.py", "pattern.py", "engine.py", "clock.py"}
    outward = [f"{p.name} imports {m}" for p in sources for m in _imports(p)
               if not (m.split(".")[0] in STDLIB or m.split(".")[0] == "performer")]
    assert outward == []


def test_the_performer_never_imports_the_apc64_packages_tests_included():
    named = [f"{p.name} imports {m}" for p in PACKAGE.rglob("*.py") for m in _imports(p) if m.startswith("_apc64")]
    assert named == []


def test_the_core_keeps_no_clock_thread_or_port():
    found = [f"{p.name} imports {m}" for p in _sources() for m in _imports(p) if m.split(".")[0] in NOT_IN_A_PURE_CORE]
    assert found == []
