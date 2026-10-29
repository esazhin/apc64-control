"""T1: the lab ships inside the apc64-host project (contract §7 layout: pyproject.toml, .gitignore)."""
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _project():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_the_lab_package_and_its_static_files_are_part_of_the_project():
    setuptools = _project()["tool"]["setuptools"]
    assert "_apc64_lab*" in setuptools["packages"]["find"]["include"]
    assert setuptools["package-data"]["_apc64_lab"] == ["presentation/static/*"]
    assert "_apc64_lab" in _project()["tool"]["pytest"]["ini_options"]["testpaths"]


def test_the_lab_imports_from_the_installed_package_outside_the_repository(tmp_path):
    """Run from a directory that is not the repository, so only the editable install can resolve it."""
    found = subprocess.run([sys.executable, "-c", "import _apc64_lab; print(_apc64_lab.__file__)"],
                           cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert found.returncode == 0, found.stderr
    assert Path(found.stdout.strip()).resolve() == (ROOT / "_apc64_lab" / "__init__.py").resolve()


def test_the_lab_carries_the_project_version():
    import _apc64_lab
    assert _apc64_lab.__version__ == _project()["project"]["version"]


def test_backups_are_ignored_by_git():
    assert "backups/" in (ROOT / ".gitignore").read_text().split()
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("no git checkout")
    checked = subprocess.run(["git", "check-ignore", "-q", "backups/slot7-2026-10-24T12-00.bin"], cwd=ROOT,
                             timeout=30)
    assert checked.returncode == 0


def test_the_performer_package_is_part_of_the_project_and_imports_outside_the_repository(tmp_path):   # §2.10
    setuptools = _project()["tool"]["setuptools"]
    assert "performer*" in setuptools["packages"]["find"]["include"]
    assert "performer" in _project()["tool"]["pytest"]["ini_options"]["testpaths"]
    found = subprocess.run([sys.executable, "-c", "import performer; print(performer.__file__)"],
                           cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert found.returncode == 0, found.stderr
    assert Path(found.stdout.strip()).resolve() == (ROOT / "performer" / "__init__.py").resolve()
