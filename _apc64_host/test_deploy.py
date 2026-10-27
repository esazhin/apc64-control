"""T38: operator docs and deployment — every route and CLI command documented, the user unit and the launcher."""
import json
import re
from pathlib import Path

from _apc64_host.presentation.cli import parser

REPO = Path(__file__).resolve().parents[1]
API_DOC = (REPO / "docs" / "api.md").read_text()
README = (REPO / "README.md").read_text()


def _routes():
    from fastapi.routing import APIRoute, APIWebSocketRoute
    from _apc64_host.presentation.conftest import compose_rig
    import tempfile
    app = compose_rig(Path(tempfile.mkdtemp())).app
    for route in app.routes:
        if isinstance(route, (APIRoute, APIWebSocketRoute)) and route.path != "/":
            yield route.path


def test_every_route_is_documented_with_an_example():
    missing = []
    for path in _routes():
        documented = re.sub(r"\{[^}]+\}", "{id}", path)
        if documented not in API_DOC and path not in API_DOC:
            missing.append(path)
    assert missing == []
    examples = re.findall(r"```json\n(.*?)```", API_DOC, re.S)
    assert len(examples) >= 12 and API_DOC.count("curl ") >= 5
    for example in examples:            # every JSON example is real JSON
        json.loads(example)


def test_every_cli_command_is_documented():
    commands = parser()._subparsers._group_actions[0].choices
    assert [c for c in commands if f"apc64 {c}" not in API_DOC] == []
    for text in ("service not running on port 5058", "ports not checked", "Exit codes"):
        assert text in API_DOC


def test_the_user_unit_runs_the_module_from_the_repo_venv_and_releases_on_stop():
    unit = (REPO / "deploy" / "apc64-host.service").read_text()
    assert re.search(r'^ExecStart="<repo>/\.venv/bin/python" -m _apc64_host$', unit, re.M)
    assert re.search(r"^WorkingDirectory=<repo>$", unit, re.M)
    assert re.search(r"^Restart=on-failure$", unit, re.M)
    stop = int(re.search(r"^TimeoutStopSec=(\d+)$", unit, re.M)[1])
    assert stop >= 10                     # release writes may each wait up to 2 s on a stuck device
    assert re.search(r"^WantedBy=default\.target$", unit, re.M)


def test_the_launcher_opens_the_page():
    desktop = (REPO / "deploy" / "apc64-host.desktop").read_text()
    assert re.search(r"^Exec=xdg-open http://localhost:5058/$", desktop, re.M)
    assert "Type=Application" in desktop


def test_the_readme_covers_install_take_release_busy_bitwig_and_the_gates():
    for text in ("Take control of APC64?", "Release", "Busy: held by", "Bitwig", "systemctl --user enable --now apc64-host",
                 "--simulate", "node --test", "APC64_LIVE=1", "docs/api.md", "docs/layout-guide.md"):
        assert text in README, text
