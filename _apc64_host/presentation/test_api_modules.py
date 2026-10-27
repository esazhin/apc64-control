"""Contract 2 T20: the host HTTP app, reused (inv9, inv6; s34 supplier, s40 and s41 collaboration).

Module routers and panels are mounted, the state lists module panels (only when there are any), and the replica
control and release routes reach the engine and session: POST /api/control/encoder/move {value: 1} gives the
engine EncoderTurn(+1), whose ModuleAction binding calls the module with ControlEvent(+1) (A37's host path);
tempo/press gives a Tempo press; /api/unit/release releases with RELEASE."""
from dataclasses import replace
from types import SimpleNamespace

from fastapi import APIRouter
from fastapi.testclient import TestClient

from _apc64_host.application.engine import EngineOk
from _apc64_host.application.modules import collect
from _apc64_host.application.session import ReleaseResult
from _apc64_host.application.state_view import StateView
from _apc64_host.application.test_engine_modules import TEMPO, Lab, tonnetz
from _apc64_host.domain.controls import EncoderPress
from _apc64_host.domain.effects import EncoderTurn, Press, Release
from _apc64_host.domain.layout import ControlEvent, LayoutId
from _apc64_host.domain.unit_status import ReleaseReason
from _apc64_host.presentation.api import Services, build_app
from _apc64_host.presentation.conftest import BASE, HOME, compose_rig
from _apc64_host.presentation.ws_hub import WebSocketHub


# --- the routes with doubles (s34.c1, s40.c1, s41.c1) ----------------------------------------------------------
class EngineDouble:
    def __init__(self):
        self.inputs = []

    def replica_input(self, event):
        self.inputs.append(event)
        return EngineOk(None)


class SessionDouble:
    def __init__(self):
        self.released = []

    async def release(self, reason=ReleaseReason.RELEASE):
        self.released.append(ReleaseReason(reason))
        return ReleaseResult.RELEASED

    def status(self):
        return SimpleNamespace(status="asking", text="Not held")


class StateDouble:
    def snapshot(self):
        return SimpleNamespace()


def doubles_app():
    engine, session = EngineDouble(), SessionDouble()
    services = Services(session=session, engine=engine, pipeline=None, library=None, tweaks=None, learn=None,
                        calibration=None, state=StateDouble(), activity=None, gate=None, ports=None, hub=None)
    vm = SimpleNamespace(state_json=lambda snapshot: {"ok": True}, problem=lambda p, **e: {"problem": p, **e})
    return build_app(services, view_model=vm, local_names=("studio-pc",)), engine, session


def test_s34_the_replica_encoder_tempo_and_release_routes_reach_the_engine_and_session():
    app, engine, session = doubles_app()
    with TestClient(app, base_url=BASE, client=HOME) as client:
        assert client.post("/api/control/encoder/move", json={"value": 1}).status_code == 200
        assert client.post("/api/control/encoder/move", json={"value": -3}).status_code == 200
        assert client.post("/api/control/tempo/press", json={}).status_code == 200
        assert client.post("/api/control/tempo/release", json={}).status_code == 200
        assert client.post("/api/control/encoder/press", json={}).status_code == 200
        released = client.post("/api/unit/release", json={})
    assert engine.inputs == [EncoderTurn(1), EncoderTurn(-3), Press(TEMPO, 127), Release(TEMPO), Press(EncoderPress())]
    # (the engine's replica_input marks them InputSource.REPLICA; test_engine_modules covers the dispatch)
    assert released.status_code == 200 and session.released == [ReleaseReason.RELEASE]


# --- the real app: module routes, panels and the replica path to a module action ----------------------------
def lab_rig(tmp_path, panel_dir):
    built = compose_rig(tmp_path)
    lab = Lab()
    router = APIRouter()

    @router.get("/api/lab")
    async def lab_state():
        return {"generators": ["tonnetz", "isomorphic"]}

    collection = collect([lab])
    built.engine._modules, built.engine._hooks = collection, collection.hooks       # as compose() passes it
    state = StateView(engine=built.engine, session=built.session, library=built.library,
                      calibration=built.calibration, learn=built.learn, panels=(("lab", str(panel_dir)),))
    hub = WebSocketHub(state, built.activity, built.services.hub._stream)
    services = replace(built.services, state=state, hub=hub, routers=(router,), panels=(("lab", str(panel_dir)),))
    built.library.register(LayoutId("tonnetz-c"), tonnetz())
    return build_app(services, local_names=("studio-pc",)), built, lab


def test_module_routes_and_panels_are_mounted_and_the_state_lists_the_panel(tmp_path):
    panel = tmp_path / "panel"
    panel.mkdir()
    (panel / "lab.js").write_text("export function mountPanel() {}\n")
    app, built, lab = lab_rig(tmp_path, panel)
    with TestClient(app, base_url=BASE, client=HOME) as client:
        assert client.get("/api/lab").json() == {"generators": ["tonnetz", "isomorphic"]}
        script = client.get("/modules/lab/lab.js")
        assert script.status_code == 200 and "mountPanel" in script.text
        assert client.get("/api/state").json()["modules"] == [
            {"name": "lab", "title": "Lab", "entry": "/modules/lab/lab.js"}]
        with client.websocket_connect("ws://192.168.1.10:5058/ws") as page:
            assert page.receive_json()["data"]["modules"][0]["name"] == "lab"


def test_a37_the_replica_encoder_reaches_the_module_action_like_the_units(tmp_path):
    panel = tmp_path / "panel"
    panel.mkdir()
    app, built, lab = lab_rig(tmp_path, panel)
    with TestClient(app, base_url=BASE, client=HOME) as client:
        assert client.post("/api/layout", json={"name": "Tonnetz C"}).status_code == 200
        client.post("/api/control/encoder/move", json={"value": 1})
        client.post("/api/control/tempo/press", json={})
        client.post("/api/control/tempo/release", json={})
    assert lab.events == [("window_shift", ControlEvent(1, False)), ("interval_cycle", ControlEvent(0, True))]


def test_without_modules_the_state_has_no_modules_key(tmp_path):
    built = compose_rig(tmp_path)
    with TestClient(built.app, base_url=BASE, client=HOME) as client:
        assert "modules" not in client.get("/api/state").json()
