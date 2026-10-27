"""T39: the lab composition root (s32 supplier, s33; WIRES s5, s6, s7, s8, s9, s13, s15, s17, s18, s19, s23, s24,
s31, s33, s38).

One scenario through the real object graph build_lab composes, on a held simulated APC64 (the real gate with the
lab's scoped policy, the real DeviceSession and its SysEx tap) with the real file stores in a temporary directory:
Tonnetz C is played in slot 0, a note is played, the router pushes, captures, reads the globals and tweaks. Then one
named case per wired seam, each asserting only that its consumer reached its supplier. Hermetic: no ALSA."""
import asyncio
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from _apc64_host.application.play_stream import PlayStream
from _apc64_host.application.ports import HostPorts
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.effects import PlayEvent, PlaySource, PlaySourceKind, UnitView
from _apc64_host.domain.outbound import SysexCommand, WriteCapability
from _apc64_host.infrastructure.memory_ports import MemoryPorts
from _apc64_host.notation.compiler import compile_text
from _apc64_host.presentation.ws_hub import WebSocketHub
from _apc64_lab import composition
from _apc64_lab.application.conftest import EngineDouble, TweaksDouble
from _apc64_lab.application.guarded_writer import GuardedWriter
from _apc64_lab.application.module import LabModule
from _apc64_lab.application.test_module import _holders
from _apc64_lab.domain.records import ProjectRecord
from _apc64_lab.generators import root_highlight
from _apc64_lab.infrastructure import unit_memory as unit_memory_module
from _apc64_lab.infrastructure.conftest import HeldUnit
from _apc64_lab.presentation.publisher import HubPublisher

TONNETZ_C = "name: Tonnetz C\nlab:\n  generator: tonnetz\n  base: 48\n"
PUSHED_7 = "pushed to slot 7; takes effect when project 7 is next loaded"


class Calls(list):
    def saw(self, owner, method, caller=None):
        return any(o == owner and m == method and (caller is None or c.endswith(caller)) for o, m, c in self)


def spy(calls, owner, obj, *methods, setter=setattr):
    for method in methods:
        original = getattr(obj, method)

        def wrapper(*args, _original=original, _method=method, **kwargs):
            calls.append((owner, _method, sys._getframe(1).f_globals.get("__name__", "")))
            return _original(*args, **kwargs)
        setter(obj, method, wrapper)


class Nothing:
    def subscribe(self, *a, **k):
        return lambda: None


async def scenario(tmp_path, monkeypatch):
    calls = Calls()
    capability = WriteCapability("lab guarded writer")
    unit = HeldUnit(capability=capability)
    paths = composition.LabPaths.under(tmp_path / "backups", tmp_path / "library", tmp_path / "state")
    lab = composition.build_lab(paths, capability, threaded=False, read_timeout=0.05)
    engine, tweaks = EngineDouble(), TweaksDouble()
    stream = PlayStream(unit.rig.clock)
    hub = WebSocketHub(Nothing(), Nothing(), Nothing())
    tap = unit.session.sysex_tap
    for name, obj, methods in (("memory", lab.memory, ("read_project", "write_project", "read_globals")),
                               ("gate", unit.gate, ("send",)), ("tap", tap, ("subscribe", "held")),
                               ("backups", lab.backups, ("save", "save_set")), ("library", lab.library, ("put",)),
                               ("stream", stream, ("subscribe",)), ("publisher", lab.publisher, ("publish",)),
                               ("hub", hub, ("publish",)), ("projects", lab.projects, ("push", "capture")),
                               ("globals", lab.globals, ("read",)), ("session", lab.session, ("tweak",)),
                               ("tweaks", tweaks, ("save_section_field",))):
        spy(calls, name, obj, *methods)
    for frame in ("project_read_frame", "parse_project_dump", "project_write_frame"):
        spy(calls, "codec", unit_memory_module, frame, setter=monkeypatch.setattr)   # undone after the run
    collection = unit.use([lab.module])
    collection.hooks.bind(HostPorts(display=engine, notes=engine, loader=engine, tweaks=tweaks, sysex=tap,
                                    gate=unit.gate, stream=stream, topics=hub, clock=unit.rig.clock,
                                    inputs=MemoryPorts()))
    await unit.take()
    unit.sim.view(UnitView.CUSTOM)
    layout = compile_text(TONNETZ_C, "tonnetz-c.yaml", sections=lab.module.layout_sections()).layout
    lab.module.on_layout_loaded(layout, layout.section("lab"))
    lab.session.drain()
    out = {"calls": calls, "lab": lab, "unit": unit, "hub": hub, "tmp": tmp_path, "capability": capability,
           "r1c1": ProjectRecord(unit.sim.slot(0)).pad(PadPos(1, 1)).note}
    stream.publish(PlayEvent("note_on", note=48, velocity=90, port=PlaySource(PlaySourceKind.CUSTOM)))
    lab.tracker.pump()
    app = FastAPI()
    app.include_router(lab.router)
    with TestClient(app) as client:
        out["push"] = client.post("/api/lab/push", json={"entry": "Tonnetz C", "slot": 7}).json()
        out["capture"] = client.post("/api/lab/library/capture", json={"slot": 12, "name": "Live set B"}).json()
        out["globals"] = client.get("/api/lab/globals").json()
        out["tweak"] = client.post("/api/lab/tweak", json={"field": "base", "value": "D2"})
        out["state"] = client.get("/api/lab").json()
    lab.stop()
    return out


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    monkeypatch = pytest.MonkeyPatch()
    try:
        return asyncio.run(scenario(tmp_path_factory.mktemp("lab"), monkeypatch))
    finally:
        monkeypatch.undo()


SEAMS = {
    # s5: the services reach the domain (LabSession's record is what slot 0 holds)
    "s5": lambda r: r["r1c1"] == 48 and r["lab"].session.session.active,
    # s6: the guarded writer reaches the unit-memory adapter
    "s6": lambda r: r["calls"].saw("memory", "read_project", "guarded_writer")
    and r["calls"].saw("memory", "write_project", "guarded_writer"),
    # s7: the adapter reaches the memory SysEx codec
    "s7": lambda r: r["calls"].saw("codec", "project_read_frame", "unit_memory")
    and r["calls"].saw("codec", "parse_project_dump", "unit_memory"),
    # s8: the adapter reaches the host's outbound gate
    "s8": lambda r: r["calls"].saw("gate", "send", "infrastructure.unit_memory"),
    # s9: the adapter reaches the session's SysEx tap
    "s9": lambda r: r["calls"].saw("tap", "subscribe", "infrastructure.unit_memory")
    and r["calls"].saw("tap", "held", "infrastructure.unit_memory"),
    # s13: the services reach the backup files (written under backups/)
    "s13": lambda r: r["calls"].saw("backups", "save", "guarded_writer")
    and any((r["tmp"] / "backups").glob("slot7-*.bin")) and any((r["tmp"] / "backups").glob("slot0-*.bin")),
    # s15: project memory reaches the library files
    "s15": lambda r: r["calls"].saw("library", "put", "project_memory") and any((r["tmp"] / "library").glob("*.json")),
    # s17: the registry reaches plugin discovery
    "s17": lambda r: any(s["name"] == "root-highlight" and s["file"] == "_apc64_lab/generators/root_highlight.py"
                         for s in r["state"]["schemes"]),
    # s18: discovery reaches the plugin package (the very object its file exposes)
    "s18": lambda r: r["lab"].registry.schemes()["root-highlight"] is root_highlight.SCHEME,
    # s19: the harmony tracker reaches the play stream
    "s19": lambda r: r["calls"].saw("stream", "subscribe", "harmony_tracker")
    and [n["note"] for n in r["lab"].publisher.current()["harmony"]["held"]] == [48],
    # s23: the session and the tracker reach the publisher
    "s23": lambda r: r["calls"].saw("publisher", "publish", "session_service")
    and r["calls"].saw("publisher", "publish", "harmony_tracker"),
    # s24: the publisher reaches the hub's 'lab' topic
    "s24": lambda r: r["calls"].saw("hub", "publish", "presentation.publisher")
    and r["hub"].current("lab", "harmony")["held"][0]["note"] == 48 and r["hub"].current("lab", "lab") is not None,
    # s31: the router reaches the use cases
    "s31": lambda r: r["calls"].saw("projects", "push", "presentation.api") and r["push"]["message"] == PUSHED_7
    and r["calls"].saw("projects", "capture", "presentation.api") and r["calls"].saw("globals", "read", "presentation.api")
    and r["calls"].saw("session", "tweak", "presentation.api"),
    # s33: the composition gave each service its ports; only GuardedWriter holds the capability
    "s33": lambda r: r["lab"].writer.memory is r["lab"].memory and r["lab"].session._writer is r["lab"].writer
    and r["lab"].projects._writer is r["lab"].writer and r["lab"].globals._writer is r["lab"].writer
    and r["lab"].module.tracker is r["lab"].tracker and r["lab"].registry.loaded,
    # s38: the session reaches the host's section tweaks
    "s38": lambda r: r["calls"].saw("tweaks", "save_section_field", "application.ports")
    and r["lab"].link.ports.tweaks is not None and r["tweak"].status_code == 200,
}


@pytest.mark.parametrize("seam", sorted(SEAMS, key=lambda s: int(s[1:])))
def test_each_wired_seam_is_reached_through_the_composed_graph(run, seam):
    assert SEAMS[seam](run), seam


def test_only_the_guarded_writer_holds_the_capability_in_the_lab(run):   # §7.1, inv2
    lab_holders = [h for h in _holders(run["lab"].module, run["capability"])
                   if type(h).__module__.startswith("_apc64_lab")]
    assert lab_holders and {type(h) for h in lab_holders} == {GuardedWriter}


def test_build_lab_returns_a_module_with_the_specified_shape(tmp_path):   # s32 supplier
    capability = WriteCapability("lab guarded writer")
    lab = composition.build_lab(composition.LabPaths.under(tmp_path / "b", tmp_path / "l", tmp_path / "s"), capability,
                                threaded=False)
    try:
        assert isinstance(lab.module, LabModule) and lab.module.name == "lab"
        assert lab.module.outbound_additions() == {SysexCommand.PROJECT_READ, SysexCommand.GLOBAL_READ}
        assert lab.module.outbound_scoped() == {SysexCommand.PROJECT_WRITE: capability,
                                                 SysexCommand.GLOBAL_WRITE: capability}
        assert set(lab.module.actions()) == {"window_shift", "interval_cycle"}
        assert set(lab.module.layout_sections()) == {"lab"}
        assert lab.module.panel() == str(composition.STATIC_DIR) and (composition.STATIC_DIR / "lab.js").is_file()
        assert lab.module.cli_commands() == (lab.cli,) and lab.module.router() is lab.router
        assert isinstance(lab.publisher, HubPublisher)
    finally:
        lab.stop()


def test_start_up_refusals_are_logged(tmp_path, caplog):   # A20
    class Twice:
        def discover(self):
            from _apc64_lab.domain.generators import TonnetzCheckerboard
            return [("_apc64_lab/generators/tonnetz2.py", TonnetzCheckerboard())]
    caplog.set_level("WARNING")
    lab = composition.build_lab(composition.LabPaths.under(tmp_path / "b", tmp_path / "l", tmp_path / "s"),
                                WriteCapability("x"), source=Twice(), threaded=False)
    lab.stop()
    assert any('two generators are named "tonnetz": _apc64_lab/domain/generators.py and '
               '_apc64_lab/generators/tonnetz2.py' in r.getMessage() for r in caplog.records)


def test_the_host_librarys_names_reach_the_index(tmp_path):
    lab = composition.build_lab(composition.LabPaths.under(tmp_path / "b", tmp_path / "l", tmp_path / "s"),
                                WriteCapability("x"), threaded=False)
    try:
        compile_text(TONNETZ_C, "tonnetz-c.yaml", sections=lab.module.layout_sections())
        compile_text("name: Gone\nlab:\n  generator: tonnetz\n", "gone.yaml", sections=lab.module.layout_sections())
        lab.name_layouts([("tonnetz-c", "Tonnetz C"), ("jam", "Jam")])
        assert [(i.layout_id, i.name) for i in lab.index.all()] == [("tonnetz-c", "Tonnetz C")]
        assert lab.index.resolve("tonnetz c").layout_id == "tonnetz-c"
    finally:
        lab.stop()


def test_a_layout_with_an_unknown_generator_is_listed_as_invalid_with_its_reason(tmp_path):   # 2026-10-27
    from types import SimpleNamespace
    lab = composition.build_lab(composition.LabPaths.under(tmp_path / "b", tmp_path / "l", tmp_path / "s"),
                                WriteCapability("x"), threaded=False)
    try:
        compile_text(TONNETZ_C, "tonnetz-c.yaml", sections=lab.module.layout_sections())
        compile_text("name: Banjo\nlab:\n  generator: banjo\n", "banjo.yaml", sections=lab.module.layout_sections())
        lab.name_layouts([SimpleNamespace(id="tonnetz-c", name="Tonnetz C", valid=True),
                          SimpleNamespace(id="banjo", name="banjo", valid=False)])
        layouts = lab.session.state().to_json()["layouts"]
        assert [(e["layout"], e["valid"]) for e in layouts] == [("tonnetz-c", True), ("banjo", False)]
        assert 'no generator "banjo"' in layouts[1]["error"] and "available: " in layouts[1]["error"]
        assert lab.publisher.current()["lab"]["layouts"] == layouts          # published at once
        # a draft checked through the API never changes the list
        lab.services.validate("name: Tonnetz C\nlab:\n  generator: nope\n", "tonnetz-c.yaml")
        assert [e["valid"] for e in lab.session.state().to_json()["layouts"]] == [True, False]
        # a layout the library holds as valid is not listed invalid, whatever was compiled last
        compile_text("name: Tonnetz C\nlab:\n  generator: nope\n", "tonnetz-c.yaml", sections=lab.module.layout_sections())
        lab.name_layouts([SimpleNamespace(id="tonnetz-c", name="Tonnetz C", valid=True)])
        assert [(e["layout"], e["valid"]) for e in lab.session.state().to_json()["layouts"]] == [("tonnetz-c", True)]
    finally:
        lab.stop()
