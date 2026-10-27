"""Contract 2 T21 (state side): a control bound to a module action says so, so the page shell can let the
replica's encoder turn it in Custom view (A37); contract 1's control JSON is unchanged."""
from fastapi.testclient import TestClient

from _apc64_host.presentation.conftest import BASE, HOME
from _apc64_host.presentation.test_api_modules import lab_rig


def test_the_encoder_of_a_generated_layout_names_its_module_action_and_a_host_layouts_does_not(tmp_path):
    panel = tmp_path / "panel"
    panel.mkdir()
    app, built, _ = lab_rig(tmp_path, panel)
    with TestClient(app, base_url=BASE, client=HOME) as client:
        jam = client.get("/api/state").json()["controls"]
        assert "module_action" not in jam["encoder"] and "module_action" not in jam["pad r1c1"]
        client.post("/api/layout", json={"name": "Tonnetz C"})
        controls = client.get("/api/state").json()["controls"]
    assert controls["encoder"]["module_action"] == "lab.window_shift"
    assert controls["tempo"]["module_action"] == "lab.interval_cycle"
    assert controls["encoder"]["label_base"] == "window shift"
