"""T37: the lab panel's static files (s25, s26, s27 supplier side; A21, A81).

- node --test passes in _apc64_lab/presentation/static (lab.test.js, harmony_views.test.js);
- lab.fixture.json, the recorded 'lab' + 'harmony' snapshot pair (plus the lists the panel reads) the JS tests
  render, is what the real services produce: 'Tonnetz C' active at Oct +0 with C3 E3 G3 held (the host's C2 E2 G2,
  48 52 55); and, under 'guitar', 'Guitar' (E standard) active at Fret 3-10 with the low E's fret 5 and the open
  high E played on their strings and a G from another input held (the neck view's data);
- every relative import resolves, the page asks the browser for no Web MIDI, and the note table is the core's.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from _apc64_host.domain.effects import PlayEvent, PlaySource, PlaySourceKind
from _apc64_host.domain.midi import NoteOn
from _apc64_lab.application.harmony_tracker import HarmonyTracker
from _apc64_lab.application.test_session_service import GUITAR, Rig
from _apc64_lab.application.global_settings import GlobalSettingsService
from _apc64_lab.application.project_memory import ProjectMemory
from _apc64_lab.application.conftest import FakeLibrary
from _apc64_lab.domain.harmony import NOTE_DISPLAY, Harmony
from _apc64_lab.presentation.publisher import payload_of

STATIC = Path(__file__).resolve().parent / "static"
FIXTURE = STATIC / "lab.fixture.json"
IMPORT = re.compile(r"""(?:import|export)\s[^'"]*?from\s+['"](\.[^'"]+)['"]|import\(\s*['"](\.[^'"]+)['"]""")


def fixture_data() -> dict:
    rig = Rig().running()
    rig.index.named("tonnetz-c", "Tonnetz C")
    projects = ProjectMemory(rig.writer, rig.backups, FakeLibrary(), rig.registry, rig.index, rig.service, rig.wall)
    harmony = Harmony()
    for note in (48, 52, 55):
        state = harmony.note_on(note)
    return {"lab": payload_of(rig.service.state()), "harmony": payload_of(state), "library": projects.library(),
            "backups": projects.backups(), "globals": GlobalSettingsService(rig.writer).read(),
            "guitar": guitar_data()}


def guitar_data() -> dict:
    rig = Rig().running()
    rig.load(GUITAR.replace("  tuning: drop-d\n", "  tuning: e-standard\n"), "guitar.yaml")
    rig.turn(+3)
    rig.service.drain()
    tracker = HarmonyTracker()
    custom = PlaySource(PlaySourceKind.CUSTOM)
    for note, channel in ((45, 6), (64, 1)):          # low E fret 5 (string 6), the open high E (string 1)
        tracker.apply(PlayEvent("note_on", note=note, velocity=90, port=custom, channel=channel))
    tracker.select_inputs(["Keys"])
    tracker.on_input("Keys", NoteOn(1, 55, 80))        # a G from a keyboard: no string
    return {"lab": payload_of(rig.service.state()), "harmony": payload_of(tracker.state())}


def render() -> str:
    return json.dumps(fixture_data(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def test_the_recorded_snapshot_pair_is_what_the_services_produce():
    assert FIXTURE.read_text() == render(), "regenerate: python -m _apc64_lab.presentation.test_static"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_panel_modules_pass_node_test():
    result = subprocess.run(["node", "--test"], cwd=STATIC, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
    assert re.search(r"# fail 0|ℹ fail 0", result.stdout)
    assert not re.search(r"# tests 0\b|ℹ tests 0\b", result.stdout)


def test_every_relative_import_of_the_panel_resolves():
    missing = []
    for module in STATIC.glob("*.js"):
        for match in IMPORT.finditer(module.read_text()):
            target = match.group(1) or match.group(2)
            if not (module.parent / target).is_file():
                missing.append(f"{module.name} → {target}")
    assert missing == []


def test_the_panel_never_asks_the_browser_for_midi_access():   # inv15: the views follow the host's play stream
    assert [p.name for p in STATIC.glob("*.js") if "requestMIDIAccess" in p.read_text()] == []


def test_the_panels_note_names_are_the_harmony_cores():   # §2.7 a25
    table = re.search(r"NOTE_NAMES = \[([^\]]*)\]", (STATIC / "harmony_views.js").read_text()).group(1)
    assert [name.strip().strip("'") for name in table.split(",")] == list(NOTE_DISPLAY)


def test_the_circles_keys_are_the_harmony_cores():   # spelled once, in the core
    from _apc64_lab.domain.harmony import circle_keys
    source = (STATIC / "harmony_views.js").read_text()
    rows = re.findall(r"\{ pc: (\d+), major: \[([^\]]*)\], minorPc: (\d+), minor: \[([^\]]*)\] \}", source)
    names = lambda text: tuple(n.strip().strip("'") for n in text.split(","))
    assert [(int(pc), names(major), int(minor_pc), names(minor)) for pc, major, minor_pc, minor in rows] == [
        (k.pc, k.major, k.minor_pc, k.minor) for k in circle_keys()]


def test_the_panel_is_served_by_the_module_mount():
    """The host mounts the panel's directory at /modules/lab/: its entry is lab.js."""
    assert (STATIC / "lab.js").is_file() and "export function mountPanel" in (STATIC / "lab.js").read_text()


def test_the_panel_styles_leave_showing_and_hiding_to_the_page_shell():
    """The shell shows a module panel only while it is chosen (.module-panel.current); a display rule on the panel
    element itself would show it beside the Overview too (found in a smoke run)."""
    css = (STATIC / "lab.css").read_text()
    rules = re.findall(r"(^|\})\s*([^{}]*\.lab-panel)\s*\{([^}]*)\}", css)
    assert rules and not any("display" in body for _, _, body in rules)



def test_the_panel_styles_never_reach_the_host_pages_own_elements():
    """lab.css loads into the whole page: a selector made only of the host's classes restyles the host's elements
    (an unscoped .oled fixed the replica's OLED at 12px, so it overflowed when the surface shrank: live session
    2026-10-26). Every selector must name at least one class the host's style.css does not use."""
    host_css = (STATIC.parents[2] / "_apc64_host" / "presentation" / "static" / "style.css").read_text()
    host = set(re.findall(r"\.([a-zA-Z][\w-]*)", re.sub(r"/\*.*?\*/", "", host_css, flags=re.S)))
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "lab.css").read_text(), flags=re.S)
    leaking = []
    for selectors in re.findall(r"([^{}]+)\{[^{}]*\}", css):
        for selector in selectors.split(","):
            selector = selector.strip()
            if selector.startswith("@") or not selector:
                continue
            classes = set(re.findall(r"\.([a-zA-Z][\w-]*)", selector))
            if not classes - host:
                leaking.append(selector)
    assert leaking == []


if __name__ == "__main__":
    FIXTURE.write_text(render())
    print(f"wrote {FIXTURE}")
