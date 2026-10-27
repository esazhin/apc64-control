"""s2 supplier; s10, s29, s31 collaboration: the apc64 command (T33; A45, A46, and A22/A30/A140 over the API)."""
import io
import json
import socket

from fastapi.testclient import TestClient

from _apc64_host.presentation import cli
from _apc64_host.presentation.conftest import BASE, HOME, compose_rig

GOOD = """\
name: Draft
devices:
  mpc: MPC Live III MIDI 1
pages:
  1 Drums:
    pads r1c1-r2c8: notes from 36 on mpc ch 10
banks:
  1 Mix:
    strips 1-8: cc 20-27 on mpc ch 1
"""


class FakeTransport:
    """Records each request; answers from a script keyed by (method, path), default 200 {}."""

    def __init__(self, answers=None, down=False):
        self.requests, self.answers, self.down = [], dict(answers or {}), down

    def request(self, method, path, body=None):
        self.requests.append((method, path, body))
        if self.down:
            raise cli.ServiceDown("connection refused")
        return self.answers.get((method, path), (200, {}))


def run(argv, transport=None, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, transport=transport or FakeTransport(), out=out, err=err, environ={}, **kwargs)
    return code, out.getvalue(), err.getvalue()


STATE = {"unit": {"status": "held", "text": "Held (taken by command-line tool)", "held": True, "view": "session",
                  "warnings": [], "notices": []},
         "layout": "tonnetz", "layout_name": "Tonnetz C", "file_deleted": False,
         "page": {"n": 3, "display": "Chords"}, "bank": {"n": 2, "display": "Sends"}, "shift": False,
         "oled": ["Tonnetz C", "P3 Chords | B2"], "routing": {"notes": None, "custom": None,
                                                              "status": "expressive pads not routed in this layout"},
         "learn": {"mode": "off", "selected": None}, "warnings": [], "errors": []}


def test_each_subcommand_calls_its_route_and_prints_the_result():
    transport = FakeTransport({
        ("POST", "/api/unit/take"): (200, {"status_text": "Held (taken by command-line tool)"}),
        ("POST", "/api/unit/release"): (200, {"text": "Not held"}),
        ("GET", "/api/ports"): (200, [{"name": "MPC Live III MIDI 1", "direction": "both", "present": True},
                                      {"name": "Bitwig Studio In", "direction": "declared", "present": False,
                                       "device": "bitwig"}]),
        ("GET", "/api/layouts"): (200, [{"file": "tonnetz.yaml", "name": "Tonnetz C", "valid": True, "pages": 3,
                                         "banks": 2, "errors": 0}]),
        ("POST", "/api/layout"): (200, STATE), ("POST", "/api/page"): (200, STATE), ("POST", "/api/bank"): (200, STATE),
        ("GET", "/api/state"): (200, STATE),
        ("GET", "/api/layouts/jam/versions"): (200, [{"id": "20261023T104200.123Z-abcdef123456",
                                                      "at": "2026-10-23T10:42:00.123Z"}]),
        ("POST", "/api/layouts/jam/restore"): (200, {"restored": "20261023T104200.123Z-abcdef123456",
                                                     "at": "2026-10-23T10:42:00.123Z"}),
    })
    assert run(["take"], transport)[:2] == (0, "Held (taken by command-line tool)\n")          # A22
    assert run(["release"], transport)[:2] == (0, "Not held\n")                                 # A30
    code, out, _ = run(["ports"], transport)
    assert out == "MPC Live III MIDI 1  (both)\nBitwig Studio In  (missing: declared by device bitwig)\n"
    assert run(["layouts"], transport)[1] == "tonnetz.yaml  Tonnetz C  3 pages, 2 banks\n"
    assert run(["load", "Tonnetz C"], transport)[1] == "Tonnetz C: page 3 Chords, bank 2 Sends\n"
    run(["page", "3"], transport)
    run(["bank", "2"], transport)
    code, out, _ = run(["state"], transport)
    assert code == 0 and "unit: Held (taken by command-line tool), view session" in out and "Tonnetz C: page 3" in out
    assert run(["versions", "jam"], transport)[1].startswith("20261023T104200.123Z-abcdef123456  2026-10-23")
    run(["restore", "jam", "20261023T104200.123Z-abcdef123456"], transport)
    sent = [(m, p, b) for m, p, b in transport.requests]
    assert ("POST", "/api/unit/take", {"source": "agent"}) in sent
    assert ("POST", "/api/layout", {"name": "Tonnetz C"}) in sent
    assert ("POST", "/api/page", {"n": 3}) in sent and ("POST", "/api/bank", {"n": 2}) in sent
    assert ("POST", "/api/layouts/jam/restore", {"id": "20261023T104200.123Z-abcdef123456"}) in sent


def test_the_rest_of_the_page_s_abilities_are_commands_too():
    transport = FakeTransport({("GET", "/api/controls/pad%20r1c1"): (200, {"base_hash": "h", "layer": "base",
                                                                            "display": "Pad r1c1", "role": "bindable",
                                                                            "lines": ["Base: Note 36 → mpc ch 10"]})})
    assert run(["card", "pad r1c1"], transport)[1] == "Pad r1c1\nBase: Note 36 → mpc ch 10\n"
    run(["tap", "pad r1c1"], transport)
    run(["move", "strip 4", "16383"], transport)
    run(["turn", "-2"], transport)
    run(["shift", "on"], transport)
    run(["tweak", "pad r1c1", "colour", "red"], transport)
    run(["learn", "midi", "mpc", "--control", "pad r2c1"], transport)
    run(["calibrate", "start"], transport)
    run(["decline"], transport)
    paths = [(m, p) for m, p, _ in transport.requests]
    assert ("POST", "/api/control/pad%20r1c1/press") in paths and ("POST", "/api/control/pad%20r1c1/release") in paths
    assert ("POST", "/api/control/strip%204/move", {"value": 16383}) in transport.requests
    assert ("POST", "/api/control/encoder/move", {"value": -2}) in transport.requests
    assert ("POST", "/api/shift", {"held": True}) in transport.requests
    assert ("POST", "/api/tweak", {"control": "pad r1c1", "field": "colour", "value": "red", "base_hash": "h",
                                   "layer": "base"}) in transport.requests
    assert ("POST", "/api/learn", {"mode": "midi", "port": "mpc", "control": "pad r2c1"}) in transport.requests
    assert ("POST", "/api/calibrate", {"step": "start"}) in transport.requests
    assert ("POST", "/api/unit/decline") in paths


def test_a_refusal_prints_the_problem_and_allowed_values_and_exits_1():
    transport = FakeTransport({("POST", "/api/page"): (400, {"problem": "page must be 1–8",
                                                             "allowed": [1, 2, 3, 4, 5, 6, 7, 8]}),
                               ("POST", "/api/unit/release"): (409, {"problem": "APC64 is not held"})})
    code, out, err = run(["page", "0"], transport)
    assert (code, out) == (1, "") and err == "page must be 1–8\nallowed: 1, 2, 3, 4, 5, 6, 7, 8\n"   # A141
    assert run(["release"], transport)[::2] == (1, "APC64 is not held\n")                              # A29
    code, out, _ = run(["--json", "page", "0"], transport)
    assert code == 1 and json.loads(out)["problem"] == "page must be 1–8"


def test_validate_posts_the_text_and_file_name_and_prints_issues(tmp_path):
    draft = tmp_path / "draft.yaml"
    draft.write_text(GOOD)
    report = {"valid": False, "summary": "invalid: 1 error", "warnings": [],
              "errors": [{"text": "draft.yaml line 6, pad r9c1: no such pad, pads are r1c1–r8c8"}]}
    transport = FakeTransport({("POST", "/api/validate"): (200, report)})
    code, out, _ = run(["validate", str(draft)], transport)
    assert transport.requests == [("POST", "/api/validate", {"text": GOOD, "file": "draft.yaml"})]   # s10.c1
    assert code == 1 and out == "invalid: 1 error\ndraft.yaml line 6, pad r9c1: no such pad, pads are r1c1–r8c8\n"
    assert run(["validate", str(tmp_path / "none.yaml")], transport)[0] == 1


def test_without_the_service_validate_runs_offline_and_everything_else_exits_2(tmp_path):
    # A45/A46: the service is stopped; an agent validates a draft, then asks to load it
    draft = tmp_path / "draft.yaml"
    draft.write_text(GOOD)
    down = FakeTransport(down=True)
    code, out, err = run(["validate", str(draft)], down)
    assert code == 0 and out == "valid: 1 page, 1 bank, 16 pads, 8 strips bound (ports not checked)\n"
    draft.write_text(GOOD.replace("pads r1c1-r2c8", "pads r1c1-r9c8"))
    assert run(["validate", str(draft)], down)[0] == 1
    code, out, err = run(["load", "jam"], down)
    assert (code, out, err) == (2, "", "service not running on port 5058\n")
    canned = []
    code, out, _ = run(["validate", str(draft)], down,
                       compile=lambda text, file: canned.append(file) or {
                           "valid": False, "summary": "invalid: 1 error", "warnings": [],
                           "errors": [{"text": "draft.yaml line 2: canned"}]})
    assert canned == ["draft.yaml"] and out == "invalid: 1 error (ports not checked)\ndraft.yaml line 2: canned\n"


def test_the_real_transport_reports_a_closed_port_as_service_not_running():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["--url", f"http://127.0.0.1:{port}", "state"], out=out, err=err, environ={})
    assert code == 2 and err.getvalue() == f"service not running on port {port}\n"


def test_watch_prints_each_event_and_stops_on_the_closed_notice():
    stream = [{"type": "event", "data": {"at": None, "kind": "press", "source": "unit", "control": "pad r1c1",
                                         "velocity": 127, "sent": ["note 36 ch 10 → mpc"]}},
              {"type": "event", "data": {"at": None, "kind": "note_on", "source": "unit", "note": 53,
                                         "velocity": 56, "sent": []}},
              {"type": "closed", "reason": "too slow"}]
    urls = []
    code, out, err = run(["watch"], socket_factory=lambda url: urls.append(url) or iter(stream))
    assert urls == ["ws://127.0.0.1:5058/ws/play"]
    assert out.splitlines() == ["--:--:-- unit pad r1c1 press vel 127 → note 36 ch 10 → mpc",
                                "--:--:-- unit note 53 note_on vel 56"]
    assert code == 1 and err == "stream closed: too slow\n"
    code, out, _ = run(["watch", "--json"], socket_factory=lambda url: iter(stream[:1]))
    assert code == 0 and json.loads(out)["control"] == "pad r1c1"


def test_the_cli_and_the_page_see_the_same_state_through_the_real_api(tmp_path):
    """a21: no second state path. The CLI drives the real app; the page's socket sees the switch."""
    built = compose_rig(tmp_path)
    with TestClient(built.app, base_url=BASE, client=("127.0.0.1", 4000)) as client:

        class Through:
            def request(self, method, path, body=None):
                answer = client.request(method, path, json=body)
                return answer.status_code, answer.json()

        with client.websocket_connect("ws://127.0.0.1:5058/ws") as page:
            assert page.receive_json()["type"] == "snapshot"
            assert run(["take"], Through())[1] == "Held (taken by command-line tool)\n"
            assert run(["load", "Tonnetz C"], Through())[0] == 0
            assert run(["page", "3"], Through())[1] == "Tonnetz C: page 3 Chords, bank 1 Mix\n"
            seen = None
            while seen != 3:
                message = page.receive_json()
                if message["type"] == "diff" and (message["data"]["changed"].get("page") or {}).get("n"):
                    seen = message["data"]["changed"]["page"]["n"]
            assert run(["release"], Through())[1] == "Not held\n"
        assert built.sim.daw_mode is False
