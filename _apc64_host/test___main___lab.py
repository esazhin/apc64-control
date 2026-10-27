"""T40 (contract 2): the service composed with the layout lab registered (s32 consumer, s43; WIRES s2, s3, s4, s11,
s20, s21, s25, s27, s32, s36, s37, s39, s40, s41).

One scenario composed exactly as `python -m _apc64_host serve --simulate` does with MODULES (the simulated APC64,
in-memory MIDI ports, real layout files in a temp dir, the lab's real file stores under the simulated state dir),
then one named case per wired seam, each asserting only that the seam's consumer reached its supplier. And: the
composition without modules is contract 1's, unchanged. Hermetic: no ALSA, nothing sent to a real unit."""
import time

import pytest
from fastapi.testclient import TestClient

from _apc64_host import __main__ as root
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.layout import UnitPortRole
from _apc64_host.domain.midi import NoteOn
from _apc64_host.domain.outbound import CONTRACT1_POLICY
from _apc64_host.domain.unit_status import ReleaseReason
from _apc64_host.notation.compiler import compile_text
from _apc64_host.presentation.conftest import JAM
from _apc64_host.test___main__ import BASE, WS, Calls, config_for, spy, wait_until

TONNETZ_C = "name: Tonnetz C\nlab:\n  generator: tonnetz\n  base: 48\n"


def r1c1(sim):
    from _apc64_lab.domain.records import ProjectRecord
    return ProjectRecord(sim.slot(0)).pad(PadPos(1, 1)).note


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("composed-lab")
    (tmp / "layouts").mkdir()
    (tmp / "layouts" / "jam.yaml").write_text(JAM)
    (tmp / "layouts" / "tonnetz-c.yaml").write_text(TONNETZ_C)
    config = config_for(tmp, lab_target="MPC Live III MIDI 1 ch 2 aftertouch pass")
    adapters = root.simulated_adapters(config)
    comp = root.compose(config, adapters, root.MODULES, local_names=("studio-pc",))
    (lab,) = comp.parts
    sim, midi = adapters.simulator, adapters.midi
    calls = Calls()
    spy(calls, "lab module", lab.module, "on_held", "on_layout_loaded", "on_pad_mode", "on_release")
    spy(calls, "lab session", lab.session, "on_action")
    spy(calls, "lab compiler", lab.compiler, "compile")
    spy(calls, "gate", comp.gate, "send")
    spy(calls, "stream", comp.stream, "publish")
    spy(calls, "midi", midi, "send")
    spy(calls, "engine", comp.engine, "replica_input", "swap")
    spy(calls, "session", comp.session, "release")
    out = {"calls": calls, "comp": comp, "lab": lab, "sim": sim, "midi": midi, "tmp": tmp}
    with TestClient(comp.app, base_url=BASE, client=("127.0.0.1", 4000)) as client:
        on_loop = client.portal.call
        out["take"] = client.post("/api/unit/take", json={"source": "agent"}).json()
        on_loop(sim.view, UnitView.CUSTOM)
        out["activate"] = client.post("/api/lab/activate", json={"layout": "Tonnetz C"}).json()
        out["playing"] = wait_until(lambda: r1c1(sim) == 48 and lab.session.running)
        out["oled"] = wait_until(lambda: sim.oled.get(0, "").startswith("Tonnetz C"))
        out["turn"] = client.post("/api/control/encoder/move", json={"value": 1}).status_code
        out["shifted"] = wait_until(lambda: r1c1(sim) == 60)          # Oct +1 (A27, through the replica, A37)
        on_loop(sim.play, UnitPortRole.CUSTOM, NoteOn(1, 60, 38))
        out["routed"] = wait_until(lambda: ("MPC Live III MIDI 1", NoteOn(2, 60, 38)) in midi.sent)
        out["held"] = wait_until(lambda: [n["note"] for n in (lab.publisher.current().get("harmony") or {})
                                          .get("held", [])] == [60])
        with client.websocket_connect(WS + "/ws") as page:
            seen = {}
            end = time.monotonic() + 4
            while time.monotonic() < end and not {"lab", "harmony"} <= set(seen):
                message = page.receive_json()
                if message.get("type") == "topic" and message.get("topic") == "lab":
                    seen[message["data"]["kind"]] = message["data"]
            out["topics"] = seen
        out["state"] = client.get("/api/state").json()
        out["lab_state"] = client.get("/api/lab").json()
        out["panel"] = client.get("/modules/lab/lab.js")
        out["css"] = client.get("/modules/lab/lab.css")
        swaps = len(calls.args("engine", "swap"))
        out["tweak"] = client.post("/api/lab/tweak", json={"field": "base", "value": "D2"}).json()
        out["reloaded"] = wait_until(lambda: len(calls.args("engine", "swap")) > swaps
                                     and r1c1(sim) == 50 + 12)                 # base D2 (50) at Oct +1 (A16, d9)
        out["file"] = (tmp / "layouts" / "tonnetz-c.yaml").read_text()
        out["release"] = client.post("/api/unit/release", json={}).json()
        out["restored"] = r1c1(sim) != 62 and not lab.session.running
    out["backups"] = sorted(p.name for p in (tmp / "state" / "simulated" / "lab-backups").glob("*.bin"))
    out["writer_closed"] = lab.session.slot0._stopped
    return out


SEAMS = {
    # s2: the engine reaches the lab's hooks and actions
    "s2": lambda r: r["calls"].saw("lab module", "on_held", "application.modules")
    and r["calls"].saw("lab module", "on_layout_loaded", "application.modules")
    and r["calls"].saw("lab module", "on_pad_mode", "application.modules")
    and r["calls"].saw("lab session", "on_action", "application.module") and r["shifted"],
    # s3: the session reaches on_release
    "s3": lambda r: r["calls"].saw("lab module", "on_release", "application.modules") and r["restored"],
    # s4: the host compiler reaches the lab's section compiler
    "s4": lambda r: r["calls"].saw("lab compiler", "compile", "notation.compiler"),
    # s11: the engine reaches the gate (the resting OLED text of the generated layout)
    "s11": lambda r: r["calls"].saw("gate", "send", "application.engine") and r["oled"],
    # s20: the engine reaches the play stream
    "s20": lambda r: r["calls"].saw("stream", "publish", "application.engine") and r["held"],
    # s21: the engine reaches MIDI out (the lab's default note target, §2.7 q2)
    "s21": lambda r: r["calls"].saw("midi", "send", "application.engine") and r["routed"],
    # s25: the hub reaches the lab panel's topic
    "s25": lambda r: {"lab", "harmony"} <= set(r["topics"]) and r["topics"]["lab"]["active"]["name"] == "Tonnetz C",
    # s27: the panel's routes and files are mounted, and the state lists the panel
    "s27": lambda r: r["lab_state"]["active"]["name"] == "Tonnetz C" and r["panel"].status_code == 200
    and "mountPanel" in r["panel"].text and r["css"].status_code == 200
    and r["state"]["modules"] == [{"name": "lab", "title": "Lab", "entry": "/modules/lab/lab.js"}],
    # s32: __main__ reaches build_lab (the part MODULES composed is the lab)
    "s32": lambda r: type(r["lab"]).__name__ == "Lab" and r["comp"].gate.policy != CONTRACT1_POLICY
    and r["lab"].module.name == "lab",
    # s36: the pipeline reaches the compiler with the lab's section
    "s36": lambda r: r["comp"].pipeline._compile.keywords["sections"]["lab"] is r["lab"].compiler
    and r["comp"].services.library.compiled("tonnetz-c").section("lab") is not None,
    # s37: the pipeline reaches the engine (the tweaked file reloads the live layout)
    "s37": lambda r: r["calls"].saw("engine", "swap", "application.layout_pipeline") and r["reloaded"],
    # s39: the tweak reaches the pipeline (one spliced line, a new version)
    "s39": lambda r: r["tweak"]["result"] == "saved" and "base: D2" in r["file"] and r["reloaded"],
    # s40: the host API reaches the engine (the replica's encoder)
    "s40": lambda r: r["calls"].saw("engine", "replica_input", "presentation.api") and r["turn"] == 200,
    # s41: the host API reaches the session's release
    "s41": lambda r: r["calls"].saw("session", "release", "presentation.api") and r["release"]["status"] != "held",
}


@pytest.mark.parametrize("seam", sorted(SEAMS, key=lambda s: int(s[1:])))
def test_each_wired_seam_is_reached_through_the_composed_graph(run, seam):
    assert SEAMS[seam](run), seam


def test_the_lab_played_and_backed_up_like_the_contract_says(run):   # A22, A27, A42, §2.7 a5/q9
    assert run["take"]["status"] == "held" and run["activate"]["message"] == "activated Tonnetz C"
    assert run["playing"] and run["shifted"]
    assert any(name.startswith("slot0-") for name in run["backups"])          # the session backup
    assert sum(name.startswith("slot") and not name.startswith("slot0-") for name in run["backups"]) == 24
    assert run["writer_closed"]                                               # stop() after the release


def test_without_modules_the_composition_is_contract_1s(tmp_path):
    (tmp_path / "layouts").mkdir()
    config = config_for(tmp_path)
    comp = root.compose(config, root.simulated_adapters(config))
    assert comp.gate.policy == CONTRACT1_POLICY and comp.parts == ()
    assert comp.pipeline._compile is compile_text and comp.services.routers == () and comp.services.panels == ()
    assert comp.services.tweaks.on_saved is None and comp.engine._modules.names == ()
    with TestClient(comp.app, base_url=BASE, client=("127.0.0.1", 4000)) as client:
        assert "modules" not in client.get("/api/state").json()
        assert client.get("/api/lab").status_code == 404


def test_main_registers_the_lab(tmp_path):   # s43
    served = []
    (tmp_path / "layouts").mkdir()
    code = root.main(["serve", "--simulate"], {}, load_config=lambda env: config_for(tmp_path, http_port=5099),
                     serve=lambda app, **options: served.append(app), register_exit=lambda hook: None)
    app = served[0]
    assert code == 0 and app.state.services.panels[0][0] == "lab"
    answer = TestClient(app, base_url=BASE, client=("127.0.0.1", 4000)).get("/api/lab")   # no lifespan: no unit
    assert answer.status_code == 200 and [g["name"] for g in answer.json()["generators"]] == ["tonnetz", "isomorphic", "guitar", "modes"]


def test_a_bad_lab_target_is_a_start_up_error_naming_its_key(tmp_path):
    (tmp_path / "layouts").mkdir()
    with pytest.raises(SystemExit) as stop:
        root.main(["serve", "--simulate"], {}, load_config=lambda env: config_for(tmp_path, lab_target="the MPC"),
                  serve=lambda *a, **k: None, register_exit=lambda hook: None)
    assert "APC64_LAB_TARGET" in str(stop.value) and "'the MPC' is not a note target" in str(stop.value)


def test_the_lab_config_keys_are_read(tmp_path):
    from _apc64_host.config import Config
    config = Config.load({"APC64_LAB_TARGET": "MPC Live III MIDI 1  ch 2", "APC64_LAB_BACKUPS_DIR": "/srv/b"},
                         tmp_path / "config.local")
    assert config.lab_target == "MPC Live III MIDI 1 ch 2"
    assert str(config.lab_backups_dir) == "/srv/b" and config.lab_library_dir == tmp_path / "library"


def test_the_lab_asks_for_custom_view_and_the_host_assumes_it(tmp_path):   # 2026-10-27: obeyed, never echoed
    (tmp_path / "layouts").mkdir()
    (tmp_path / "layouts" / "jam.yaml").write_text(JAM)
    (tmp_path / "layouts" / "tonnetz-c.yaml").write_text(TONNETZ_C)
    config = config_for(tmp_path)
    adapters = root.simulated_adapters(config)
    comp = root.compose(config, adapters, root.MODULES, local_names=("studio-pc",))
    (lab,) = comp.parts
    sim = adapters.simulator
    with TestClient(comp.app, base_url=BASE, client=("127.0.0.1", 4000)) as client:
        client.post("/api/unit/take", json={"source": "agent"})
        assert sim.current_view is UnitView.SESSION and not sim.report_view_requests
        client.post("/api/lab/activate", json={"layout": "Tonnetz C"})
        assert wait_until(lambda: lab.session.running and lab.session.state().active["unit_view"] == "custom")
        assert sim.current_view is UnitView.CUSTOM                     # the unit obeyed the request
        assert client.get("/api/state").json()["unit"]["view"] == "custom"
        assert lab.session.message is None                             # no 'Press Custom'
        # the replica's Session button: the unit switches, the session pauses (d22) as for the unit's own button
        client.post("/api/control/view session/press")
        assert sim.current_view is UnitView.SESSION and lab.session.message == "Custom view off"
        client.post("/api/control/view custom/press")
        assert wait_until(lambda: lab.session.message is None and sim.current_view is UnitView.CUSTOM)
        client.post("/api/unit/release", json={})
