"""The static page: served by the app, modules resolve, and its node --test suite passes (T34–T36)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from _apc64_host.presentation.api import STATIC_DIR

IMPORT = re.compile(r"""(?:import|export)\s[^'"]*?from\s+['"](\.[^'"]+)['"]|import\(\s*['"](\.[^'"]+)['"]""")


def test_the_page_and_its_modules_are_served(rig):
    page = rig.client.get("/")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert '<script type="module" src="app.js">' in page.text
    for name in ("app.js", "api.js", "state.js", "style.css"):
        answer = rig.client.get(f"/{name}")
        assert answer.status_code == 200, name
    assert "javascript" in rig.client.get("/state.js").headers["content-type"]


def test_the_harmony_full_view_address_is_the_page_itself(rig):
    """/?view=harmony (a new tab, a bookmark, another device) is the same page: app.js reads the address, so the
    full view needs no route of its own."""
    page = rig.client.get("/?view=harmony")
    assert page.status_code == 200 and page.text == rig.client.get("/").text


def test_every_relative_import_of_the_page_resolves():
    missing = []
    for module in STATIC_DIR.glob("*.js"):
        for match in IMPORT.finditer(module.read_text()):
            target = match.group(1) or match.group(2)
            if not (module.parent / target).is_file():
                missing.append(f"{module.name} → {target}")
    assert missing == []
    referenced = re.findall(r'(?:src|href)="([^"]+)"', (STATIC_DIR / "index.html").read_text())
    assert all((STATIC_DIR / r).is_file() for r in referenced if not r.startswith(("http", "#")))


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_modules_pass_node_test():
    result = subprocess.run(["node", "--test"], cwd=STATIC_DIR, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
    assert re.search(r"# fail 0|ℹ fail 0", result.stdout)


def test_the_js_surface_fixture_is_what_the_api_serves(rig):
    """static/surface.fixture.json feeds the replica's node tests; it must stay equal to GET /api/surface."""
    import json
    fixture = json.loads((STATIC_DIR / "surface.fixture.json").read_text())
    assert fixture == rig.client.get("/api/surface").json()
