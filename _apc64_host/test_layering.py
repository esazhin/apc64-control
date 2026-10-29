"""Dependency direction (contract §7): imports point inward only, and the page never asks for Web MIDI."""
import ast
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
NAME = PACKAGE.name
STDLIB = set(sys.stdlib_module_names)

# layer -> (own packages it may import, third-party top-level modules it may import)
ALLOWED = {
    "domain": ({"domain"}, set()),
    "protocol": ({"domain", "protocol"}, set()),
    "notation": ({"domain", "notation"}, {"ruamel"}),
}
FORBIDDEN_FOR = {
    "application": {"infrastructure", "presentation", "__main__"},
    "infrastructure": {"presentation", "__main__"},
}


def _imports(path: Path):
    """Absolute module names imported by one source file (relative imports resolved)."""
    module_parts = [NAME, *path.relative_to(PACKAGE).with_suffix("").parts]
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


def _sources(layer: str):
    return [p for p in (PACKAGE / layer).rglob("*.py") if not p.name.startswith("test_")] \
        if (PACKAGE / layer).is_dir() else []


def _own_layer(module: str) -> str | None:
    parts = module.split(".")
    return parts[1] if parts[0] == NAME and len(parts) > 1 else ("" if parts[0] == NAME else None)


def test_pure_layers_import_only_the_standard_library_and_inner_layers():
    outward = []
    for layer, (own, third_party) in ALLOWED.items():
        for path in _sources(layer):
            for module in _imports(path):
                top = module.split(".")[0]
                inner = _own_layer(module)
                if inner is not None:
                    if inner not in own:
                        outward.append(f"{path.relative_to(PACKAGE)} imports {module}")
                elif top not in STDLIB and top not in third_party:
                    outward.append(f"{path.relative_to(PACKAGE)} imports {module}")
    assert outward == []


def test_application_and_infrastructure_never_import_outward():
    outward = []
    for layer, forbidden in FORBIDDEN_FOR.items():
        for path in _sources(layer):
            for module in _imports(path):
                if _own_layer(module) in forbidden:
                    outward.append(f"{path.relative_to(PACKAGE)} imports {module}")
    assert outward == []


GATE = PACKAGE / "application" / "outbound_gate.py"
_STREAMS = {"sys.stdout", "sys.stderr", "stdout", "stderr"}


def _unit_writes(path: Path):
    """Calls that look like UnitConnection.write(frame): an attribute call `.write` with exactly one
    argument whose receiver is not a standard stream. (LayoutSource.write takes two arguments.)"""
    tree = ast.parse(path.read_text(), str(path))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "write"
                and len(node.args) + len(node.keywords) == 1
                and ast.unparse(node.func.value) not in _STREAMS):
            yield node.lineno


def test_only_the_outbound_gate_writes_to_the_unit():
    """Contract §7 enforcement (a6): nothing but application/outbound_gate.py calls UnitConnection.write.
    Scans non-test code outside infrastructure/ (the adapters and the simulator implement write)."""
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        rel = path.relative_to(PACKAGE)
        if path.name.startswith("test_") or path.name == "conftest.py" or rel.parts[0] == "infrastructure":
            continue
        if path == GATE:
            continue
        offenders += [f"{rel}:{line}" for line in _unit_writes(path)]
    assert offenders == []
    assert list(_unit_writes(GATE)), "the gate itself must be the one writer"


def test_no_static_module_asks_the_browser_for_midi_access():
    static = PACKAGE / "presentation" / "static"
    offenders = [p.name for p in static.rglob("*.js") if "requestMIDIAccess" in p.read_text()] \
        if static.is_dir() else []
    assert offenders == []


# --- contract 2: the lab beside the host (contract 2 §7 dependency direction, inv2, a10) --------------------
LAB = PACKAGE.parent / "_apc64_lab"
HOST_MAIN = PACKAGE / "__main__.py"
LAB_COMPOSITION = LAB / "composition.py"
UNIT_MEMORY_ADAPTER = LAB / "infrastructure" / "unit_memory.py"
GUARDED_WRITER = LAB / "application" / "guarded_writer.py"


def _module_imports(path: Path, package: Path):
    """Absolute module names one source file of `package` imports (relative imports resolved)."""
    parts = [package.name, *path.relative_to(package).with_suffix("").parts]
    if path.name == "__init__.py":
        parts = parts[:-1] + ["__init__"]
    tree = ast.parse(path.read_text(), str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                yield ".".join(parts[:-node.level] + ([node.module] if node.module else []))
            else:
                yield node.module


def _code(root: Path, sub: str = ""):
    """Non-test sources under root/sub (tests and conftest doubles excluded)."""
    base = root / sub if sub else root
    return [p for p in base.rglob("*.py") if not p.name.startswith("test_") and p.name != "conftest.py"] \
        if base.is_dir() else []


def test_the_lab_application_imports_only_its_domain_host_domain_values_and_host_ports():
    """Contract 2 §7: `_apc64_lab/application` imports the lab domain and `_apc64_host/application/ports.py`
    Protocols only, never infrastructure or presentation (its own or the host's). §2.10: and the pure performer
    package (standard library only, as its own test enforces), like the standard library."""
    allowed = ("_apc64_lab.domain", "_apc64_lab.application", "_apc64_host.domain", "_apc64_host.application.ports",
               "performer")
    offenders = []
    for path in _code(LAB, "application"):
        for module in _module_imports(path, LAB):
            if module.split(".")[0] in STDLIB or any(module == a or module.startswith(a + ".") for a in allowed):
                continue
            offenders.append(f"{path.relative_to(LAB)} imports {module}")
    assert offenders == []


def test_lab_adapters_never_import_presentation_or_the_composition_roots():
    forbidden = ("_apc64_lab.presentation", "_apc64_lab.composition", "_apc64_host.presentation",
                 "_apc64_host.__main__")
    offenders = []
    for layer in ("domain", "application", "infrastructure", "generators"):
        for path in _code(LAB, layer):
            offenders += [f"{path.relative_to(LAB)} imports {m}" for m in _module_imports(path, LAB)
                          if m and any(m == f or m.startswith(f + ".") for f in forbidden)]
    assert offenders == []


def _calls_named(path: Path, name: str):
    tree = ast.parse(path.read_text(), str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if called == name:
                yield node.lineno


def test_only_the_composition_roots_construct_the_write_capability():
    """inv2, a10: one WriteCapability, made where the service is composed and handed to the lab's guarded writer."""
    offenders = []
    for root in (PACKAGE, LAB):
        for path in _code(root):
            if path in (HOST_MAIN, LAB_COMPOSITION):
                continue
            offenders += [f"{path.relative_to(root.parent)}:{line}" for line in _calls_named(path, "WriteCapability")]
    assert offenders == []


def _issuer_calls(path: Path):
    tree = ast.parse(path.read_text(), str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and any(k.arg == "issuer" for k in node.keywords):
            yield node.lineno


def test_only_the_labs_unit_memory_adapter_sends_with_an_issuer():
    """The token reaches the gate in one place: the adapter GuardedWriter calls with it, per call."""
    offenders = []
    for root in (PACKAGE, LAB):
        for path in _code(root):
            if path == UNIT_MEMORY_ADAPTER:
                continue
            offenders += [f"{path.relative_to(root.parent)}:{line}" for line in _issuer_calls(path)]
    assert offenders == []


def _stores_capability(path: Path):
    """Assignments to an attribute (self.x = …, obj.x = …) whose value names a capability."""
    tree = ast.parse(path.read_text(), str(path))
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] \
            if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
        value = getattr(node, "value", None)
        if value is None or not any(isinstance(t, (ast.Attribute, ast.Tuple)) for t in targets):
            continue
        if "capab" in ast.unparse(value).lower():
            yield node.lineno


def test_only_the_guarded_writer_holds_the_capability():
    """Contract 2 §7.1: GuardedWriter is the sole holder of the WriteCapability. No other lab object keeps it
    (the adapter takes it per call; LabModule asks the writer for its scoped writes)."""
    offenders = []
    for path in _code(LAB):
        if path in (GUARDED_WRITER, LAB_COMPOSITION):
            continue
        offenders += [f"{path.relative_to(LAB)}:{line}" for line in _stores_capability(path)]
    assert offenders == []
    assert not GUARDED_WRITER.exists() or list(_stores_capability(GUARDED_WRITER)), \
        "the guarded writer itself keeps the capability"


def test_no_lab_module_opens_a_write_through_plain_additions():
    """inv2 hardening (a build decision on a10/inv2): contract 1's plain outbound_additions() can open any command,
    so a lab module must name 0x14/0x18 only in outbound_scoped(), with the one capability."""
    offenders = []
    for path in _code(LAB):
        tree = ast.parse(path.read_text(), str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "outbound_additions":
                text = ast.unparse(node)
                if "PROJECT_WRITE" in text or "GLOBAL_WRITE" in text:
                    offenders.append(f"{path.relative_to(LAB)}:{node.lineno}")
    assert offenders == []
