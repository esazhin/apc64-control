"""The composition root (T37): one scenario through the real object graph — the simulated APC64, in-memory MIDI ports,
real layout files (inotify in a temp dir), real version and state stores — then one named case per wired seam,
each showing that the seam's consumer reached its supplier (or produced the outcome only that path gives).
Also: s7/s76 lifespan start and release('stop') once, s77 modules, s78 config errors, s79 uvicorn arguments."""
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _apc64_host import __main__ as root
from _apc64_host.config import Config, ConfigError
from _apc64_host.domain.controls import PadPos, TrackButton
from _apc64_host.domain.layout import Layout, LayoutId, UnitPortRole
from _apc64_host.domain.midi import ControlChange, NoteOn
from _apc64_host.domain.network import AllowedNetworks
from _apc64_host.domain.outbound import CONTRACT1_POLICY, SysexCommand
from _apc64_host.domain.unit_status import ReleaseReason
from _apc64_host.presentation import view_model
from _apc64_host.presentation.conftest import JAM

REPO = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:5058"
WS = "ws://127.0.0.1:5058"


class Calls:
    def __init__(self):
        self.items = []

    def saw(self, owner, method, caller=None):
        return any(o == owner and m == method and (caller is None or c.endswith(caller)) for o, m, c, _ in self.items)

    def args(self, owner, method):
        return [a for o, m, _, a in self.items if o == owner and m == method]


def spy(calls, owner, obj, *methods):
    for method in methods:
        original = getattr(obj, method)

        def wrapper(*args, _original=original, _method=method, **kwargs):
            caller = sys._getframe(1).f_globals.get("__name__", "")
            calls.items.append((owner, _method, caller, args))
            return _original(*args, **kwargs)
        setattr(obj, method, wrapper)


def wait_until(predicate, timeout=4.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def config_for(tmp: Path, **overrides) -> Config:
    values = dict(http_port=5058, layouts_dir=tmp / "layouts", state_dir=tmp / "state",
                  allowed_networks=AllowedNetworks.default(), auto_accept=False, port_stem="APC64")
    values.update(overrides)
    return Config(**values)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """Compose exactly as `python -m _apc64_host serve --simulate` does and drive one scenario through it."""
    tmp = tmp_path_factory.mktemp("composed")
    (tmp / "layouts").mkdir()
    (tmp / "layouts" / "jam.yaml").write_text(JAM)
    config = config_for(tmp)
    adapters = root.simulated_adapters(config)
    comp = root.compose(config, adapters, local_names=("studio-pc",))
    s, a = comp.services, adapters
    sim, midi = a.simulator, a.midi
    calls = Calls()
    spy(calls, "session", comp.session, "start", "take", "release", "status")
    spy(calls, "engine", comp.engine, "select_page", "on_held", "snapshot", "swap")
    spy(calls, "pipeline", comp.pipeline, "validate_text")
    spy(calls, "library", s.library, "summaries", "register", "compiled", "all_issues")
    spy(calls, "tweaks", s.tweaks, "apply")
    spy(calls, "learn", s.learn, "set_mode", "intercept", "status")
    spy(calls, "calibration", s.calibration, "start", "observe", "label")
    spy(calls, "state", s.state, "card", "subscribe")
    spy(calls, "activity", s.activity, "records", "subscribe", "append")
    spy(calls, "gate", comp.gate, "device_log", "attach", "send")
    spy(calls, "stream", comp.stream, "subscribe", "publish")
    spy(calls, "hub", comp.hub, "accept")
    spy(calls, "midi", midi, "list", "send", "listen")
    spy(calls, "locator", a.locator, "find")
    spy(calls, "holders", a.holders, "holder_of")
    spy(calls, "unit_port", a.unit_port, "open")
    spy(calls, "prompt", a.prompt, "ask")
    spy(calls, "store", a.store, "marker_set", "nav_put", "calibration_put")
    spy(calls, "files", a.files, "read", "write")
    spy(calls, "versions", a.versions, "save")
    spy(calls, "clock", a.clock, "call_later", "monotonic")
    out = {"calls": calls, "comp": comp, "sim": sim, "midi": midi, "tmp": tmp}
    with TestClient(comp.app, base_url=BASE, client=("127.0.0.1", 4000)) as client:
        on_loop = client.portal.call
        out["asking"] = comp.session.status().status
        out["state"] = client.get("/api/state").json()
        out["layouts"] = client.get("/api/layouts").json()
        client.get("/api/ports")
        client.post("/api/validate", json={"text": JAM, "file": "draft.yaml"})
        out["card"] = client.get("/api/controls/pad r1c1").json()
        client.get("/api/activity")
        client.get("/api/overview")
        with client.websocket_connect(WS + "/ws") as page, client.websocket_connect(WS + "/ws/play") as agent:
            out["first"] = page.receive_json()
            out["take"] = client.post("/api/unit/take", json={"source": "agent"}).json()
            out["status_after_take"] = comp.session.status().status
            out["firmware"] = comp.session.firmware
            on_loop(sim.press, PadPos(1, 1))
            on_loop(sim.release, PadPos(1, 1))
            out["play"] = agent.receive_json()
        client.post("/api/page", json={"n": 2})
        client.post("/api/page", json={"n": 1})
        client.post("/api/control/pad r1c1/press")
        client.post("/api/control/pad r1c1/release")
        client.post("/api/calibrate", json={"step": "start"})
        on_loop(sim.play, UnitPortRole.NOTES, NoteOn(1, 36, 90))
        on_loop(sim.play, UnitPortRole.NOTES, NoteOn(1, 99, 90))
        client.post("/api/learn", json={"mode": "touch"})
        on_loop(sim.press, TrackButton(1))
        client.post("/api/learn", json={"mode": "midi", "port": "mpc", "control": "pad r2c1"})
        swaps = len(calls.args("engine", "swap"))
        on_loop(midi.deliver, "MPC Live III MIDI 1", ControlChange(1, 74, 10))
        # the learned line is written, the file watch sees it, the pipeline settles, compiles and swaps it in
        out["swapped"] = wait_until(lambda: len(calls.args("engine", "swap")) > swaps
                                    and comp.services.state.card("pad r2c1").card.base is not None)
        out["learned_card"] = comp.services.state.card("pad r2c1").card.base
        client.post("/api/learn", json={"mode": "off"})
        base_hash = client.get("/api/controls/pad r1c3").json()["base_hash"]
        out["tweak"] = client.post("/api/tweak", json={"control": "pad r1c3", "field": "colour", "value": "blue",
                                                        "base_hash": base_hash}).json()
        on_loop(comp.engine.send_to_unit, [bytes([0xF0, 0x47, 0x00, 0x53, 0x14, 0x00, 0x00, 0xF7])], "test")
        out["device_log"] = client.get("/api/device-log").json()
        stranger = TestClient(comp.app, base_url=BASE, client=("203.0.113.5", 4000))   # no second lifespan
        out["stranger"] = stranger.get("/api/state").status_code
        out["daw_mode_held"] = sim.daw_mode
        out["leds_held"] = dict(sim.leds)
        out["oled_held"] = dict(sim.oled)
    out["daw_mode_after"] = sim.daw_mode
    out["dark_after"] = sim.dark()
    out["file"] = (tmp / "layouts" / "jam.yaml").read_text()
    return out


SEAMS = {
    "s11": lambda r: r["stranger"] == 403 and r["state"]["layout"] == "jam",
    "s12": lambda r: [str(a[1]) for a in r["calls"].args("hub", "accept")] == ["state", "play"],
    "s13": lambda r: list(r["state"]) == list(view_model.state_json(r["comp"].services.state.snapshot())),
    "s14": lambda r: r["first"]["type"] == "snapshot" and r["first"]["data"]["layout"] == "jam",
    "s15": lambda r: r["calls"].saw("session", "take", "presentation.api") and r["take"]["status"] == "held",
    "s16": lambda r: r["calls"].saw("engine", "select_page", "presentation.api"),
    "s17": lambda r: r["calls"].saw("pipeline", "validate_text", "presentation.api"),
    "s18": lambda r: r["calls"].saw("library", "summaries", "presentation.api") and r["layouts"][0]["id"] == "jam",
    "s19": lambda r: r["calls"].saw("tweaks", "apply", "presentation.api") and r["tweak"] == {
        "ok": True, "hash": r["tweak"]["hash"]},
    "s20": lambda r: r["calls"].saw("learn", "set_mode", "presentation.api"),
    "s21": lambda r: r["calls"].saw("calibration", "start", "presentation.api"),
    "s22": lambda r: r["calls"].saw("state", "card", "presentation.api"),
    "s23": lambda r: r["calls"].saw("activity", "records", "presentation.api"),
    "s24": lambda r: r["calls"].saw("gate", "device_log", "presentation.api"),
    "s25": lambda r: r["calls"].saw("midi", "list", "presentation.api"),
    "s26": lambda r: r["calls"].saw("state", "subscribe", "presentation.ws_hub"),
    "s27": lambda r: r["calls"].saw("activity", "subscribe", "presentation.ws_hub"),
    "s28": lambda r: r["calls"].saw("stream", "subscribe", "presentation.ws_hub") and r["play"]["type"] == "event",
    "s32": lambda r: r["calls"].saw("locator", "find", "application.session"),
    "s33": lambda r: r["calls"].saw("holders", "holder_of", "application.session"),
    "s34": lambda r: [a[0] for a in r["calls"].args("unit_port", "open")][:1] == [UnitPortRole.DAW],
    "s35": lambda r: r["calls"].saw("prompt", "ask"),
    "s36": lambda r: r["calls"].saw("store", "marker_set", "application.session"),
    "s37": lambda r: r["calls"].saw("gate", "attach", "application.session"),
    "s38": lambda r: r["calls"].saw("engine", "on_held", "application.session"),
    "s39": lambda r: r["daw_mode_held"] is True and r["firmware"] == "1.2.1.6",
    "s40": lambda r: (r["asking"], r["status_after_take"]) == ("asking", "held"),
    "s41": lambda r: r["calls"].saw("clock", "call_later", "application.session"),
    "s42": lambda r: ("MPC Live III MIDI 1", NoteOn(10, 36, 127)) in r["midi"].sent,
    "s43": lambda r: sum(1 for v in r["leds_held"].values() if v) > 16 and r["oled_held"].get(0, "") != "",
    "s44": lambda r: r["calls"].saw("gate", "send", "application.engine"),
    "s45": lambda r: r["calls"].saw("midi", "send", "application.engine"),
    "s46": lambda r: r["play"]["data"]["source"] == "unit" and r["play"]["data"]["control"] == "pad r1c1",
    "s47": lambda r: r["calls"].saw("activity", "append", "application.engine"),
    "s48": lambda r: r["calls"].saw("stream", "publish", "application.engine"),
    "s49": lambda r: r["calls"].saw("library", "compiled", "application.engine"),
    "s50": lambda r: r["calls"].saw("learn", "intercept", "application.engine"),
    "s51": lambda r: r["calls"].saw("calibration", "observe", "application.engine"),
    "s52": lambda r: r["calls"].saw("clock", "call_later", "application.engine"),
    "s53": lambda r: r["calls"].saw("store", "nav_put", "application.engine"),
    "s54": lambda r: any(e["outcome"] == "sent" for e in r["device_log"]) and r["daw_mode_held"],
    "s55": lambda r: {e["command"] for e in r["device_log"]} >= {"identity_request", "daw_mode", "oled_text"},
    "s56": lambda r: r["comp"].gate.policy == CONTRACT1_POLICY and r["device_log"][-1]["hazard"]
    and r["device_log"][-1]["text"] == "refused: project write (0x14)" and not r["sim"].hazards,
    "s57": lambda r: r["calls"].saw("files", "read", "application.layout_pipeline"),
    "s58": lambda r: r["comp"].pipeline.compiles >= 2,
    "s59": lambda r: r["calls"].saw("versions", "save", "application.layout_pipeline"),
    "s60": lambda r: r["calls"].saw("library", "register", "application.layout_pipeline"),
    "s61": lambda r: r["swapped"] and r["learned_card"] == "CC74 → mpc ch 1, momentary",
    "s62": lambda r: r["calls"].saw("clock", "call_later", "application.layout_pipeline"),
    "s63": lambda r: "pad r2c1: cc 74 on mpc ch 1" in r["file"] and "pad r1c3:" in r["file"],
    "s64": lambda r: r["calls"].saw("files", "write", "application.tweaks"),
    "s65": lambda r: r["calls"].saw("midi", "listen", "application.learn"),
    "s66": lambda r: r["calls"].saw("tweaks", "apply", "application.learn"),
    "s67": lambda r: r["calls"].saw("store", "calibration_put", "application.calibration"),
    "s68": lambda r: r["card"]["lines"][0] == "Base: Note 36 → mpc ch 10, momentary",
    "s69": lambda r: r["calls"].saw("engine", "snapshot", "application.state_view"),
    "s70": lambda r: r["calls"].saw("session", "status", "application.state_view"),
    "s71": lambda r: r["calls"].saw("library", "all_issues", "application.state_view"),
    "s72": lambda r: r["calls"].saw("calibration", "label", "application.state_view"),
    "s73": lambda r: r["calls"].saw("clock", "monotonic", "application.play_stream"),
    "s74": lambda r: isinstance(r["comp"].services.library.compiled(LayoutId("jam")), Layout),
    "s75": lambda r: r["play"]["data"]["velocity"] == 127,
    "s76": lambda r: len(r["calls"].args("session", "start")) == 1
    and [tuple(a) for a in r["calls"].args("session", "release")] == [(ReleaseReason.STOP,)],
    "s77": lambda r: r["comp"].gate.policy == CONTRACT1_POLICY,
    "s89": lambda r: r["calls"].saw("midi", "list", "application.layout_pipeline"),
    "s90": lambda r: r["calls"].saw("learn", "status", "application.state_view"),
}


@pytest.mark.parametrize("seam", sorted(SEAMS, key=lambda s: int(s[1:])))
def test_each_wired_seam_is_reached_through_the_composed_graph(run, seam):
    assert SEAMS[seam](run), seam


def test_shutdown_released_the_unit_out_of_daw_mode_and_dark(run):
    # s7 / inv14 / A26: the lifespan shutdown cleared the surface, sent DAW off and freed the port
    assert run["daw_mode_held"] is True
    assert run["daw_mode_after"] is False and run["dark_after"] is True
    assert run["comp"].release_at_exit() is not None      # the atexit safety net runs harmlessly after it


def test_a_config_error_exits_naming_the_key_and_serves_nothing():
    # s78
    served = []

    def bad(environ):
        raise ConfigError("APC64_HTTP_PORT", "must be a port number 1-65535, got 'x'")
    with pytest.raises(SystemExit) as stop:
        root.main(["serve"], {}, load_config=bad, serve=lambda *a, **k: served.append(1))
    assert "APC64_HTTP_PORT" in str(stop.value) and served == []


def test_main_serves_dual_stack_with_lifespan_on_and_registers_the_exit_release(tmp_path):
    # s79: uvicorn.run(app, host='::', port=config.port, lifespan='on')
    served, hooks = [], []
    (tmp_path / "layouts").mkdir()
    code = root.main(["serve", "--simulate"], {}, load_config=lambda env: config_for(tmp_path, http_port=5099),
                     serve=lambda app, **options: served.append((app, options)), register_exit=hooks.append)
    assert code == 0
    app, options = served[0]
    assert options["host"] == "::" and options["port"] == 5099 and options["lifespan"] == "on"
    assert hooks and callable(hooks[0])


def test_the_real_adapters_are_built_without_opening_anything(tmp_path):
    from _apc64_host.infrastructure.alsa_rawmidi import AlsaRawMidi
    from _apc64_host.infrastructure.alsa_seq import AlsaSequencer
    from _apc64_host.infrastructure.notifier import DesktopNotifier
    from _apc64_host.infrastructure.unit_locator import AmidiUnitLocator
    adapters = root.real_adapters(config_for(tmp_path))
    assert isinstance(adapters.unit_port, AlsaRawMidi) and isinstance(adapters.midi, AlsaSequencer)
    assert adapters.holders is adapters.midi and isinstance(adapters.locator, AmidiUnitLocator)
    assert isinstance(adapters.prompt, DesktopNotifier)
    assert adapters.midi._client is None and adapters.unit_port._lib is None     # nothing opened yet
    assert len(adapters.starts) == 3 and len(adapters.stops) == 3


def test_a_command_word_runs_the_cli(capsys):
    code = root.main(["layouts"], {"APC64_URL": "http://127.0.0.1:9"})
    assert code == 2 and "service not running on port 9" in capsys.readouterr().err


def test_sigterm_stops_the_simulated_service_cleanly(tmp_path):
    """a7: a service stop (SIGTERM) runs the lifespan shutdown, which releases the unit, and exits 0."""
    (tmp_path / "layouts").mkdir()
    (tmp_path / "layouts" / "jam.yaml").write_text(JAM)
    env = {"APC64_LAYOUTS_DIR": str(tmp_path / "layouts"), "APC64_STATE_DIR": str(tmp_path / "state"),
           "APC64_AUTO_ACCEPT": "1", "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    process = subprocess.Popen([sys.executable, "-m", "_apc64_host", "serve", "--simulate", "--host", "127.0.0.1",
                                "--port", "0"], cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True)
    lines = []
    try:
        end = time.monotonic() + 20
        while time.monotonic() < end:
            line = process.stdout.readline()
            if not line:
                break
            lines.append(line)
            if "Application startup complete" in line:
                break
        assert any("Application startup complete" in line for line in lines), "".join(lines)
        process.send_signal(signal.SIGTERM)
        output, _ = process.communicate(timeout=20)
    finally:
        if process.poll() is None:
            process.kill()
    text = "".join(lines) + output
    assert process.returncode == 0, text
    assert "APC64 host stopped (Not held)" in text      # it held the simulated unit (auto-accept) and released it
