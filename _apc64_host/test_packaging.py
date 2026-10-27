import importlib
import shutil
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


def _project():
    return tomllib.loads(PYPROJECT.read_text())


def test_project_declares_runtime_and_dev_dependencies():
    project = _project()["project"]
    assert project["name"] == "apc64-host"
    assert project["requires-python"] == ">=3.14"
    assert set(project["dependencies"]) == {"fastapi", "uvicorn", "websockets", "ruamel.yaml", "alsa-midi"}
    assert set(project["optional-dependencies"]["dev"]) == {"pytest", "httpx"}


def test_the_apc64_console_script_points_at_the_cli():
    assert _project()["project"]["scripts"] == {"apc64": "_apc64_host.presentation.cli:main"}


def test_pytest_collects_from_the_package_and_deselects_live(pytestconfig):
    options = _project()["tool"]["pytest"]["ini_options"]
    assert options["testpaths"] == ["_apc64_host", "_apc64_lab"]   # contract 2 T1 adds the lab package
    assert options["markers"] == ["live: needs the real APC64 (APC64_LIVE=1)"]
    assert options["addopts"] == "-m 'not live'"
    assert pytestconfig.getoption("markexpr") == "not live"


def test_runtime_dependencies_import():
    for module in ("fastapi", "uvicorn", "websockets", "ruamel.yaml", "alsa_midi"):
        importlib.import_module(module)


def test_the_package_carries_a_version():
    package = importlib.import_module("_apc64_host")
    assert package.__version__ == "0.1.0"


def test_the_apc64_command_is_installed_next_to_the_interpreter():
    import sys
    assert (Path(sys.executable).parent / "apc64").exists() or shutil.which("apc64")


def test_gitignore_keeps_local_config_venv_and_build_debris_out():
    ignored = set((ROOT / ".gitignore").read_text().split())
    assert {"config.local", ".venv/", "*.egg-info/", "__pycache__/"} <= ignored
