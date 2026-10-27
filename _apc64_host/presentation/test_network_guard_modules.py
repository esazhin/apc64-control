"""Contract 2 T19: the network guard, reused unchanged, in front of mounted module routes (inv9; s30; A61)."""
from dataclasses import replace

from fastapi import APIRouter
from fastapi.testclient import TestClient

from _apc64_host.presentation.api import build_app
from _apc64_host.presentation.conftest import BASE, compose_rig


def lab_app(tmp_path):
    calls = []
    router = APIRouter()

    @router.post("/api/lab/push")
    async def push(body: dict):
        calls.append(body)
        return {"result": "pushed", "backup": "slot7-2026-10-25T12-00", "message": "pushed to slot 7"}

    built = compose_rig(tmp_path)
    app = build_app(replace(built.services, routers=(router,)), local_names=("studio-pc",))
    return app, calls


def test_a61_a_push_from_outside_the_home_network_is_refused_and_nothing_is_read_or_written(tmp_path):
    app, calls = lab_app(tmp_path)
    with TestClient(app, base_url=BASE, client=("203.0.113.5", 4000)) as stranger:
        answer = stranger.post("/api/lab/push", json={"entry": "Tonnetz C", "slot": 7})
    assert answer.status_code == 403 and answer.json() == {"problem": "not on the home network"}
    assert calls == []


def test_a_home_network_client_passes_and_a_foreign_site_is_refused(tmp_path):
    app, calls = lab_app(tmp_path)
    with TestClient(app, base_url=BASE, client=("192.168.1.20", 4000)) as laptop:
        ok = laptop.post("/api/lab/push", json={"entry": "Tonnetz C", "slot": 7})
        foreign = laptop.post("/api/lab/push", json={"entry": "Tonnetz C", "slot": 8},
                              headers={"origin": "https://example.com"})
    assert ok.status_code == 200 and ok.json()["result"] == "pushed"
    assert foreign.status_code == 403 and foreign.json() == {"problem": "cross-site request refused"}
    assert calls == [{"entry": "Tonnetz C", "slot": 7}]
