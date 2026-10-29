"""Lab dependency direction (contract §7): the lab domain is pure; the host core never imports the lab.

_apc64_lab/domain imports only the standard library, _apc64_host.domain value types, the pure performer package
(§2.10: standard library only itself, shared with other projects) and itself.
The harmony core (_apc64_lab/domain/harmony) imports only the standard library and itself (§2.7 q7).
"""
import ast
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent
HOST = LAB.parent / "_apc64_host"
STDLIB = set(sys.stdlib_module_names)


def _imports(path: Path, package: Path):
    module_parts = [package.name, *path.relative_to(package).with_suffix("").parts]
    if path.name == "__init__.py":
        module_parts = module_parts[:-1] + ["__init__"]
    tree = ast.parse(path.read_text(), str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module_parts[:-node.level]
                yield ".".join(base + ([node.module] if node.module else []))
            else:
                yield node.module


def _sources(root: Path):
    return [p for p in root.rglob("*.py") if not p.name.startswith("test_") and p.name != "conftest.py"]


def test_the_lab_domain_imports_only_the_stdlib_host_domain_values_and_itself():
    outward = []
    for path in _sources(LAB / "domain"):
        for module in _imports(path, LAB):
            top = module.split(".")[0]
            allowed = (top in STDLIB or module.startswith("_apc64_host.domain")
                       or module.startswith("_apc64_lab.domain") or top == "performer")
            if not allowed:
                outward.append(f"{path.relative_to(LAB)} imports {module}")
    assert outward == []


def test_the_harmony_core_is_pure_and_device_independent():
    """§2.7 q7 (binding): standard library only — no _apc64_host, no other lab module, no ALSA or FastAPI."""
    harmony = LAB / "domain" / "harmony"
    sources = _sources(harmony)
    assert sources, "the harmony core exists"
    outward = []
    for path in sources:
        for module in _imports(path, LAB):
            if not (module.split(".")[0] in STDLIB or module.startswith("_apc64_lab.domain.harmony")):
                outward.append(f"{path.relative_to(LAB)} imports {module}")
    assert outward == []


def test_generator_plugins_import_only_the_stdlib_and_the_domain():
    """A plugin is domain code (contract §7 layout: _apc64_lab/generators — layer: domain)."""
    outward = []
    for path in _sources(LAB / "generators"):
        for module in _imports(path, LAB):
            allowed = (module.split(".")[0] in STDLIB or module.startswith("_apc64_lab.domain")
                       or module.startswith("_apc64_host.domain") or module.startswith("_apc64_lab.generators"))
            if not allowed:
                outward.append(f"{path.relative_to(LAB)} imports {module}")
    assert outward == []


def test_the_host_core_never_imports_the_lab():
    """Only _apc64_host/__main__.py may name the lab (contract §7.1); no host file does yet."""
    offenders = []
    for path in _sources(HOST):
        if path.name == "__main__.py" and path.parent == HOST:
            continue
        offenders += [f"{path.relative_to(HOST)} imports {m}" for m in _imports(path, HOST)
                      if m and m.split(".")[0] == "_apc64_lab"]
    assert offenders == []


def _docstrings(tree) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def test_nothing_in_the_lab_imports_or_runs_the_tools_scripts():
    """Contract §2.5: tools/apc64_project.py, daw_probe.py and settings_watch.py open their own MIDI
    connection around the gate; their codec knowledge is ported into the domain instead. Tests included:
    no import of tools, and no string naming a tools/ path or script outside docstrings."""
    offenders = []
    for path in LAB.rglob("*.py"):
        if path.name == "test_layering.py":
            continue
        tree = ast.parse(path.read_text(), str(path))
        docs = _docstrings(tree)
        if any(m and m.split(".")[0] == "tools" for m in _imports(path, LAB)):
            offenders.append(f"{path.relative_to(LAB)} imports tools")
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs and any(
                    word in node.value for word in ("tools/", "apc64_project", "daw_probe", "settings_watch")):
                offenders.append(f"{path.relative_to(LAB)}:{node.lineno} names {node.value!r}")
    assert offenders == []
