"""s9–s25 supplier/collaboration: every route of docs/api.md over the real services and the simulated APC64,
plus doubles for the view model and the hub (T32; A140, A141, and the API side of A7, A9, A22, A29, A70, A133,
A136, A139, A144, A145, A147)."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from _apc64_host.domain.layout import ContentHash, UnitPortRole
from _apc64_host.domain.midi import ControlChange, NoteOff, NoteOn
from _apc64_host.presentation import view_model
from _apc64_host.presentation.api import build_app
from _apc64_host.presentation.conftest import BASE, HOME, JAM, WS_BASE, compose_rig


def post(rig, path, body=None, **kwargs):
    return rig.client.post(path, json=body if body is not None else {}, **kwargs)


# --- A140 / A141 / A142: the CLI-shaped sequence ---------------------------------------------------------
def test_an_agent_lists_loads_switches_and_reads_the_same_state(rig):
    assert post(rig, "/api/unit/take", {"source": "agent"}).json()["status_text"] == "Held (taken by command-line tool)"
    ports = rig.client.get("/api/ports").json()
    assert {"name": "MPC Live III MIDI 1", "direction": "both", "present": True, "device": None} in ports
    layouts = rig.client.get("/api/layouts").json()
    assert [(x["id"], x["name"]) for x in layouts] == [("jam", "Jam"), ("tonnetz", "Tonnetz C")]
    loaded = post(rig, "/api/layout", {"name": "Tonnetz C"})              # by display name …
    assert loaded.status_code == 200 and loaded.json()["layout"] == "tonnetz"
    assert post(rig, "/api/layout", {"name": "tonnetz"}).status_code == 200   # … or by file name
    assert post(rig, "/api/page", {"n": 3}).json()["page"]["n"] == 3
    assert post(rig, "/api/bank", {"n": 2}).json()["bank"]["n"] == 2
    state = rig.client.get("/api/state").json()
    assert (state["layout_name"], state["page"]["n"], state["bank"]["n"]) == ("Tonnetz C", 3, 2)
    assert state["unit"]["status"] == "held"
    assert rig.sim.oled[0].rstrip() == state["oled"][0].rstrip()                 # the unit shows the same


def test_page_0_is_refused_with_the_allowed_values_and_nothing_changes(rig):
    post(rig, "/api/page", {"n": 2})
    for bad in (0, 9, "x", None, True):
        answer = post(rig, "/api/page", {"n": bad})
        assert answer.status_code == 400
        assert answer.json() == {"problem": "page must be 1–8", "allowed": [1, 2, 3, 4, 5, 6, 7, 8]}   # A141
    assert post(rig, "/api/bank", {"n": 7}).json() == {"problem": "bank must be 1–6", "allowed": [1, 2, 3, 4, 5, 6]}
    assert rig.client.get("/api/state").json()["page"]["n"] == 2
    unknown = post(rig, "/api/layout", {"name": "Ambient"})
    assert unknown.status_code == 409 and unknown.json() == {"problem": "no layout Ambient", "allowed": ["jam", "tonnetz"]}
    assert post(rig, "/api/shift", {"held": "yes"}).status_code == 400
    assert rig.client.post("/api/page", content=b"{not json").status_code == 400


def test_the_last_switch_wins_for_everyone(rig):
    # A142: the user taps page 2, an agent then selects page 3; the unit, every page and the agent read page 3
    post(rig, "/api/layout", {"name": "tonnetz"})
    with rig.ws("/ws") as page:
        assert page.receive_json()["type"] == "snapshot"
        post(rig, "/api/page", {"n": 2}, headers={"origin": BASE})
        post(rig, "/api/page", {"n": 3})
        seen = []
        while not seen or seen[-1] != 3:
            message = page.receive_json()
            if message["type"] == "diff" and "page" in message["data"]["changed"]:
                seen.append(message["data"]["changed"]["page"]["n"])
    assert seen == [2, 3]
    assert rig.client.get("/api/state").json()["page"]["n"] == 3 == rig.engine.nav.page


# --- the guard in front of the app (A143–A147) ------------------------------------------------------------
def test_guests_on_the_home_network_switch_pages_and_strangers_and_foreign_sites_are_refused(tmp_path):
    built = compose_rig(tmp_path)
    with TestClient(built.app, base_url=BASE, client=("192.168.1.40", 4000)) as guest:
        assert guest.get("/api/state").status_code == 200
        assert guest.post("/api/page", json={"n": 2}).json()["page"]["n"] == 2        # A147
        refused = guest.post("/api/layout", json={"name": "tonnetz"}, headers={"origin": "https://example.com"})
        assert refused.status_code == 403 and refused.json() == {"problem": "cross-site request refused"}   # A145
        assert guest.get("/api/state").json()["layout"] == "jam"
    with TestClient(built.app, base_url=BASE, client=("203.0.113.5", 4000)) as stranger:
        answer = stranger.post("/api/layout", json={"name": "tonnetz"})
        assert answer.status_code == 403 and answer.json() == {"problem": "not on the home network"}   # A144
    with TestClient(built.app, base_url="http://[fd00::1]:5058", client=("fd00::23", 4000)) as laptop:
        assert laptop.get("/api/state").status_code == 200                           # A146
    assert built.engine.layout.id == "jam"


# --- the unit: take, decline, release (s15) ---------------------------------------------------------------
def test_take_from_the_page_then_a_second_yes_then_release_twice(rig):
    first = post(rig, "/api/unit/take", {"source": "banner"}, headers={"origin": BASE})
    assert first.status_code == 200 and first.json()["status_text"] == "Held"          # A21 (phone on the LAN)
    assert first.json()["by"] == "lan_browser"
    again = post(rig, "/api/unit/take", {"source": "banner"})
    assert again.status_code == 409 and again.json()["problem"] == "already held"    # A7
    released = post(rig, "/api/unit/release")
    assert released.status_code == 200 and released.json()["text"] == "Not held"
    assert rig.sim.daw_mode is False
    twice = post(rig, "/api/unit/release")
    assert twice.status_code == 409 and twice.json()["problem"] == "APC64 is not held"    # A29


def test_busy_no_permission_and_not_connected_are_refusals_with_their_text(rig):
    rig.on_loop(rig.sim.hold, UnitPortRole.DAW, "Bitwig Studio")
    busy = post(rig, "/api/unit/take", {"source": "banner"})
    assert busy.status_code == 409 and busy.json()["problem"] == "Busy: held by Bitwig Studio"   # A9
    assert rig.sim.commands == [] or not rig.sim.daw_mode
    rig.on_loop(rig.sim.free, UnitPortRole.DAW)
    rig.sim.no_permission = True
    denied = post(rig, "/api/unit/take", {"source": "agent"})
    assert denied.status_code == 409 and denied.json()["problem"] == "No permission to open APC64"   # A12
    rig.sim.no_permission = False
    rig.on_loop(rig.sim.unplug)
    gone = post(rig, "/api/unit/take", {"source": "agent"})
    assert gone.status_code == 409 and gone.json()["problem"] == "APC64 not connected"
    assert post(rig, "/api/unit/take", {"source": "nobody"}).status_code == 400


def test_decline_answers_not_held(rig):
    answer = post(rig, "/api/unit/decline")
    assert answer.status_code == 200 and answer.json() == {"status": "declined", "text": "Not held"}
    assert rig.client.get("/api/unit").json()["text"] == "Not held"


# --- replica input (s16; A70, A61, A16) ------------------------------------------------------------------
def test_a_replica_press_sends_exactly_what_a_hardware_press_sends(rig):
    post(rig, "/api/control/pad r1c1/press")
    post(rig, "/api/control/pad%20r1c1/release")
    assert rig.ports.sent[-2:] == [("MPC Live III MIDI 1", NoteOn(10, 36, 127)),
                                   ("MPC Live III MIDI 1", NoteOff(10, 36, 0))]
    activity = rig.client.get("/api/activity?limit=2").json()
    assert activity[1]["text"].startswith("pad r1c1 → note 36 ch 10 → MPC Live III MIDI 1: sent")
    post(rig, "/api/control/strip 4/move", {"value": 16383})
    assert rig.ports.sent[-1] == ("MPC Live III MIDI 1", ControlChange(1, 23, 127))
    assert rig.client.get("/api/state").json()["unit"]["text"] == "Take control of APC64?"   # not held, still sent


def test_replica_input_refuses_what_cannot_be_done(rig):
    not_held = post(rig, "/api/control/view note/press")
    assert not_held.status_code == 409 and not_held.json()["problem"].startswith("the APC64 is not held")
    project = post(rig, "/api/control/view project/press")
    assert project.status_code == 400 and "Project view" in project.json()["problem"]
    assert post(rig, "/api/control/pad r9c1/press").json()["problem"].startswith("no such pad")
    assert post(rig, "/api/control/pad r1c1/move", {"value": 3}).status_code == 400
    assert post(rig, "/api/control/strip 1/move", {"value": 20000}).json()["problem"] == "value must be 0–16383"
    assert post(rig, "/api/control/encoder/move", {"value": 0}).status_code == 400
    assert post(rig, "/api/control/encoder/move", {"value": 1}).status_code == 200


# --- reads: card, overview, surface, activity, device log (s22–s24) ---------------------------------------
def test_the_card_has_both_layers_elsewhere_and_the_hash_to_tweak_against(rig):
    card = rig.client.get("/api/controls/pad r1c1").json()
    assert card["base"] == "Note 36 → mpc ch 10, momentary"
    assert card["port_status"] == ["mpc connected"]
    assert [e["text"] for e in card["elsewhere"]] == ["Page 2: Note 50"]
    assert card["base_hash"] == ContentHash.of(JAM)
    assert (card["layout"], card["page"], card["bank"], card["layer"]) == ("jam", 1, 1, "base")
    assert rig.client.get("/api/controls/pad r0c0").status_code == 400
    overview = rig.client.get("/api/overview").json()
    assert overview["pages"][1]["name"] == "Keys"
    surface = rig.client.get("/api/surface").json()
    assert len(surface["controls"]) > 100 and surface["approximate"] is True


def test_the_device_log_lists_what_the_unit_was_sent(rig):
    post(rig, "/api/unit/take", {"source": "agent"})
    log = rig.client.get("/api/device-log").json()
    assert log and not any(e["hazard"] for e in log)
    assert {e["command"] for e in log} >= {"identity_request"} or log[0]["hex"].startswith("F0")
    assert len(rig.client.get("/api/device-log?limit=3").json()) == 3
    assert rig.client.get("/api/activity?limit=0").status_code == 400


# --- validate, versions, restore (s17) -------------------------------------------------------------------
def test_validate_takes_text_never_a_path(rig):
    good = post(rig, "/api/validate", {"text": JAM, "file": "/tmp/draft.yaml"}).json()
    assert good["valid"] is True and good["summary"].startswith("valid: 2 pages, 1 bank")
    bad = post(rig, "/api/validate", {"text": "name: X\npages:\n  9:\n    pad r1c1: note 1\n", "file": "x.yaml"}).json()
    assert bad["valid"] is False and bad["errors"][0]["text"].startswith("x.yaml line 3")
    refused = post(rig, "/api/validate", {"path": "/etc/passwd"})
    assert refused.status_code == 400 and "not a path" in refused.json()["problem"]
    assert rig.engine.layout.id == "jam"                                             # A45: nothing applied


def test_versions_are_listed_and_restore_refuses_an_unknown_version(rig):
    versions = rig.client.get("/api/layouts/jam/versions").json()
    assert len(versions) == 1 and versions[0]["at"].endswith("Z")
    assert post(rig, "/api/layouts/jam/restore", {"id": "nope"}).status_code == 409
    assert post(rig, "/api/layouts/jam/restore", {}).status_code == 400
    restored = post(rig, "/api/layouts/jam/restore", {"id": versions[0]["id"]})
    assert restored.status_code == 200 and restored.json()["restored"] == versions[0]["id"]
    assert rig.client.get("/api/layouts/..%2Fetc/versions").status_code in (400, 404)


# --- tweak, learn, calibrate (s19–s21) -------------------------------------------------------------------
def test_a_tweak_saves_one_line_and_stale_or_invalid_ones_change_nothing(rig):
    base = rig.client.get("/api/controls/pad r1c3").json()["base_hash"]
    saved = post(rig, "/api/tweak", {"control": "pad r1c3", "field": "colour", "value": "blue", "base_hash": base})
    assert saved.status_code == 200 and saved.json()["ok"] is True
    text = rig.source.files["jam"]
    assert len(text.splitlines()) == len(JAM.splitlines()) + 1 and "pad r1c3" in text
    stale = post(rig, "/api/tweak", {"control": "pad r1c1", "field": "colour", "value": "green", "base_hash": base})
    assert stale.status_code == 409 and stale.json() == {"problem": "layout changed, reload"}       # A139
    fresh = rig.client.get("/api/controls/pad r1c1").json()["base_hash"]
    invalid = post(rig, "/api/tweak", {"control": "pad r1c1", "field": "assignment",
                                       "value": "note 36 on mpc ch 17", "base_hash": fresh})
    assert invalid.status_code == 400 and "channel must be 1–16" in invalid.json()["problem"]      # A136
    assert rig.source.files["jam"] == text
    assert post(rig, "/api/tweak", {"control": "scene 1", "field": "label", "value": "x",
                                    "base_hash": fresh}).status_code == 400
    assert post(rig, "/api/tweak", {"control": "pad r1c1", "field": "size", "base_hash": fresh}).status_code == 400


def test_learn_by_touch_and_midi_learn_from_the_mpc(rig):
    assert post(rig, "/api/learn", {"mode": "touch"}).json()["mode"] == "touch"
    assert post(rig, "/api/learn", {"mode": "midi", "port": "nord"}).json() == {
        "problem": "unknown port nord", "allowed": ["mpc"]}
    listening = post(rig, "/api/learn", {"mode": "midi", "port": "mpc", "control": "pad r2c1"}).json()
    assert listening["mode"] == "midi" and listening["selected"] == "pad r2c1"
    rig.on_loop(rig.ports.deliver, "MPC Live III MIDI 1", ControlChange(1, 74, 10))                 # A133
    assert "pad r2c1: cc 74 on mpc ch 1" in rig.source.files["jam"]
    assert post(rig, "/api/learn", {"mode": "sideways"}).status_code == 400
    assert post(rig, "/api/learn", {"mode": "off"}).json()["mode"] == "off"


def test_calibration_steps(rig):
    assert post(rig, "/api/calibrate", {"step": "start"}).json()["step"] == "waiting for bottom-left"
    assert post(rig, "/api/calibrate", {"step": "cancel"}).json()["step"] == "idle"
    assert post(rig, "/api/calibrate", {"step": "jump"}).status_code == 400


# --- WebSockets through the app (s12) --------------------------------------------------------------------
def test_the_page_socket_starts_with_a_snapshot_and_follows_api_changes(rig):
    with rig.ws("/ws") as page:
        first = page.receive_json()
        assert first["type"] == "snapshot" and first["data"]["layout"] == "jam"
        assert page.receive_json()["type"] == "activity_list"
        post(rig, "/api/page", {"n": 2})
        while True:
            message = page.receive_json()
            if message["type"] == "diff" and "page" in message["data"]["changed"]:
                break
        assert message["data"]["changed"]["page"]["n"] == 2                             # A130 through the API


def test_the_play_socket_streams_presses(rig):
    with rig.ws("/ws/play") as agent:
        post(rig, "/api/control/pad r1c1/press")
        event = agent.receive_json()
        assert event["type"] == "event" and event["data"]["control"] == "pad r1c1"
        assert event["data"]["source"] == "replica" and event["data"]["velocity"] == 127


# --- collaboration doubles: view model (s13) and hub (s12) -----------------------------------------------
def test_responses_are_the_view_models_dicts_and_sockets_go_to_the_hub(tmp_path):
    built = compose_rig(tmp_path)
    canned = SimpleNamespace(**{name: getattr(view_model, name) for name in dir(view_model) if not name.startswith("_")})
    canned.state_json = lambda snapshot: {"canned": "state"}
    canned.overview_json = lambda view: {"canned": "overview"}
    accepted = []

    class Hub:
        async def accept(self, ws, channel):
            accepted.append(str(channel))
            await ws.accept()
            await ws.send_json({"channel": str(channel)})
            await ws.close()

    built.services.hub = Hub()
    app = build_app(built.services, view_model=canned, local_names=("studio-pc",))
    with TestClient(app, base_url=BASE, client=HOME) as client:
        assert client.get("/api/state").json() == {"canned": "state"}
        assert client.get("/api/overview").json() == {"canned": "overview"}
        with client.websocket_connect(WS_BASE + "/ws") as ws:
            assert ws.receive_json() == {"channel": "state"}
        with client.websocket_connect(WS_BASE + "/ws/play") as ws:
            assert ws.receive_json() == {"channel": "play"}
    assert accepted == ["state", "play"]


# --- the replica's view buttons switch the unit (2026-10-27) ----------------------------------------------------
def test_a_replica_view_button_switches_the_unit_and_the_host_assumes_the_view(rig):
    post(rig, "/api/unit/take", {"source": "agent"})
    custom = post(rig, "/api/control/view custom/press")
    assert custom.status_code == 200 and custom.json()["unit"]["view"] == "custom"   # assumed at once: no echo
    assert rig.sim.current_view.value == "custom"                                     # the unit obeyed
    assert rig.sim.written[-1] == bytes.fromhex("F0 47 00 53 19 00 01 09 F7")
    assert post(rig, "/api/control/view custom/release").status_code == 200
    before = len(rig.sim.written)
    session = post(rig, "/api/control/view session/press")
    assert session.json()["unit"]["view"] == "session" and rig.sim.current_view.value == "session"
    assert len(rig.sim.written) - before > 64   # the request, then Session view's pads repainted
