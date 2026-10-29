"""T35: the /api/lab router (s27 and s29 supplier, s31 consumer; inv9, inv10).

With service doubles: each route makes its typed call and maps each answer kind to its status and JSON. With the
real services over the application fakes: the messages the contract gives reach the client verbatim."""
import base64
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from _apc64_host.application.tweaks import Invalid, Saved, Stale
from _apc64_host.domain.issues import LayoutIssue, Severity, SourceRef
from _apc64_host.domain.layout import ContentHash
from _apc64_host.notation.compiler import compile_text
from _apc64_lab.application.global_settings import GlobalSettingsService
from _apc64_lab.application.ports import LabState
from _apc64_lab.application.test_project_memory import PUSHED_7, Rig
from _apc64_lab.domain.harmony import Harmony
from _apc64_lab.domain.memory import BackupId, OutcomeCode, OutcomeKind, WriteOutcome
from _apc64_lab.domain.test_apc64_preset import file_of, items_of
from _apc64_lab.presentation.api import LabServices, lab_router

BUSY_5 = "busy: push to slot 5 in progress"


class Recorder:
    """A service double: records (method, args) and answers what the test set for that method."""

    def __init__(self, **answers):
        self.calls, self.answers = [], answers

    def __getattr__(self, name):
        if name.startswith("_") or name in ("calls", "answers"):
            raise AttributeError(name)

        def call(*args):
            self.calls.append((name, args))
            value = self.answers.get(name, WriteOutcome(OutcomeKind.UNCHANGED, f"{name} done"))
            return value(*args) if callable(value) else value
        return call


def client_for(**services) -> tuple[TestClient, LabServices]:
    s = LabServices(session=services.get("session", Recorder()), projects=services.get("projects", Recorder()),
                    globals=services.get("globals", Recorder()), tracker=services.get("tracker", Recorder()),
                    validate=services.get("validate"))
    app = FastAPI()
    app.include_router(lab_router(s))
    return TestClient(app), s


# --- the T35 rows -------------------------------------------------------------------------------------------
def test_a_push_maps_to_200_with_result_backup_and_message():   # A1, A60
    backup = BackupId("slot7-2026-10-24T20-15")
    projects = Recorder(push=WriteOutcome(OutcomeKind.PUSHED, PUSHED_7, backup))
    client, _ = client_for(projects=projects)
    answer = client.post("/api/lab/push", json={"entry": "Tonnetz C", "slot": 7})
    assert answer.status_code == 200
    assert answer.json() == {"result": "pushed", "backup": "slot7-2026-10-24T20-15", "message": PUSHED_7}
    assert projects.calls == [("push", ("Tonnetz C", 7, None))]


def test_a_busy_push_is_409_with_the_message_verbatim():   # A7
    projects = Recorder(push=WriteOutcome(OutcomeKind.REFUSED, BUSY_5, code=OutcomeCode.BUSY))
    client, _ = client_for(projects=projects)
    answer = client.post("/api/lab/push", json={"entry": "Tonnetz C", "slot": 7, "offset": 7})
    assert answer.status_code == 409 and answer.json()["problem"] == BUSY_5
    assert projects.calls == [("push", ("Tonnetz C", 7, 7))]


def test_validate_with_an_issue_is_400_with_problem_fix_file_line_and_field():   # A10, inv10
    validate = lambda text, file: compile_text(text, file, sections={"lab": _lab_compiler()})
    client, _ = client_for(validate=validate)
    text = "name: Tonnetz C\nlab:\n  base: 110\n  generator: tonnetz\n"
    answer = client.post("/api/lab/validate", json={"text": text, "file": "tonnetz-c.yaml"})
    assert answer.status_code == 400
    body = answer.json()
    assert (body["problem"], body["fix"], body["file"], body["line"], body["field"]) == (
        "110 puts pad r8c8 at note 138", "the highest base is 99", "tonnetz-c.yaml", 3, "base")
    assert body["issues"][0]["text"] == "tonnetz-c.yaml line 3, base: 110 puts pad r8c8 at note 138; the highest base is 99"
    assert body["valid"] is False


def test_validate_a_good_definition():
    client, _ = client_for(validate=lambda text, file: compile_text(text, file, sections={"lab": _lab_compiler()}))
    answer = client.post("/api/lab/validate", json={"text": "name: T\nlab:\n  generator: tonnetz\n", "file": "t.yaml"})
    assert answer.status_code == 200 and answer.json()["valid"] is True and answer.json()["issues"] == []


def test_validate_names_the_unknown_generator():   # A11
    client, _ = client_for(validate=lambda text, file: compile_text(text, file, sections={"lab": _lab_compiler()}))
    answer = client.post("/api/lab/validate", json={"text": "name: T\nlab:\n  generator: tonetz\n",
                                                     "file": "tonnetz-c.yaml"})
    assert answer.status_code == 400
    assert answer.json()["issues"][0]["text"] == \
        'tonnetz-c.yaml line 3: no generator "tonetz"; available: isomorphic, tonnetz'


def _lab_compiler():
    from _apc64_lab.application.registry import GeneratorRegistry
    from _apc64_lab.application.section_compiler import LabSectionCompiler
    registry = GeneratorRegistry().load()
    return LabSectionCompiler(registry.generators, registry.schemes)


# --- every outcome code maps to its status ---------------------------------------------------------------
@pytest.mark.parametrize("code, status", [
    (OutcomeCode.INVALID, 400), (OutcomeCode.BUSY, 409), (OutcomeCode.NOT_HELD, 409), (OutcomeCode.SESSION, 409),
    (OutcomeCode.TAKEN, 409), (OutcomeCode.FIRMWARE, 409), (OutcomeCode.NOT_FOUND, 404),
    (OutcomeCode.CORRUPT, 422), (OutcomeCode.STORAGE, 500), (OutcomeCode.UNIT, 502)])
def test_refusals_map_by_code(code, status):
    outcome = WriteOutcome(OutcomeKind.REFUSED, "no", code=code, field="slot", fix="do this")
    client, _ = client_for(projects=Recorder(restore=outcome))
    answer = client.post("/api/lab/restore", json={"backup": "slot7-2026-10-24T12-00", "slot": 7})
    assert answer.status_code == status
    assert answer.json() | {} == {"problem": "no", "fix": "do this", "field": "slot", "result": "refused",
                                  "backup": None, "code": str(code)}


def test_a_failed_write_is_502_and_names_its_backup():   # A54
    backup = BackupId("slot7-2026-10-24T20-30")
    outcome = WriteOutcome(OutcomeKind.FAILED, "slot 7 may be partial; restore slot7-2026-10-24T20-30", backup,
                           OutcomeCode.UNIT)
    client, _ = client_for(projects=Recorder(push=outcome))
    answer = client.post("/api/lab/push", json={"entry": "Tonnetz C", "slot": 7})
    assert answer.status_code == 502 and answer.json()["backup"] == str(backup)
    assert answer.json()["problem"] == "slot 7 may be partial; restore slot7-2026-10-24T20-30"


# --- each route makes its typed call (s31.c1) -------------------------------------------------------------
def test_each_route_reaches_its_use_case():
    harmony = Harmony()
    harmony.note_on(48)
    session = Recorder(state=LabState(message="hello"))
    projects = Recorder(backups={"backups": [], "sets": []}, library=[{"name": "Tonnetz C"}],
                        slot={"slot": 3, "pads": [], "strips": [], "raw": "00"})
    globals_ = Recorder(read={"fields": [{"field": "led_level", "text": "75%"}], "raw": "00"})
    tracker = Recorder(state=harmony.state(), inputs={"apc64": ["APC64 Custom", "APC64 Notes"], "inputs": []},
                       select_inputs=lambda ports: {"inputs": ports, "message": "ok"},
                       clear_trail={"trail": [], "message": "trail cleared"})
    client, _ = client_for(session=session, projects=projects, globals=globals_, tracker=tracker)
    data = base64.b64encode(b"preset").decode()
    requests = [
        ("get", "/api/lab", None), ("post", "/api/lab/activate", {"layout": "Tonnetz C"}),
        ("post", "/api/lab/leave", {}), ("post", "/api/lab/recovery/dismiss", {}),
        ("get", "/api/lab/harmony", None), ("get", "/api/lab/harmony/inputs", None),
        ("post", "/api/lab/harmony/inputs", {"inputs": ["Keystation 49"]}),
        ("post", "/api/lab/harmony/trail/clear", {}),
        ("get", "/api/lab/slots/3", None), ("post", "/api/lab/preview", {"entry": "Live set B"}),
        ("post", "/api/lab/backup", {"all": True}), ("post", "/api/lab/backup", {"slot": 7}),
        ("post", "/api/lab/backup", {"slot": "globals"}), ("get", "/api/lab/backups", None),
        ("post", "/api/lab/restore", {"backup": "slot7-2026-10-24T12-00", "slot": 7}),
        ("post", "/api/lab/import", {"name": "Boss RC-600", "data_base64": data, "file": "Boss RC-600.APC64"}),
        ("get", "/api/lab/library", None), ("post", "/api/lab/library/capture", {"slot": 12, "name": "Live set B"}),
        ("post", "/api/lab/bulk-edit", {"target": "5", "edits": ["all pads channel 3"]}),
        ("get", "/api/lab/globals", None),
        ("post", "/api/lab/globals", {"changes": {"led_level": 100, "cv2_channel": 4}}),
        ("post", "/api/lab/globals", {"changes": {"device_mode": "standalone"}, "confirm": True}),
    ]
    for method, path, body in requests:
        answer = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert answer.status_code == 200, (path, answer.json())
    assert session.calls == [("state", ()), ("activate", ("Tonnetz C",)), ("leave", ()), ("dismiss_recovery", ())]
    assert projects.calls == [
        ("slot", ("3",)), ("preview", ("Live set B",)), ("backup_all", ()), ("backup", (7,)), ("backup", ("globals",)),
        ("backups", ()), ("restore", ("slot7-2026-10-24T12-00", 7)),
        ("import_preset", ("Boss RC-600", b"preset", "Boss RC-600.APC64")), ("library", ()),
        ("capture", (12, "Live set B")), ("bulk_edit", ("5", ["all pads channel 3"]))]
    assert globals_.calls == [("read", ()), ("change", ({"led_level": 100, "cv2_channel": 4}, False)),
                              ("change", ({"device_mode": "standalone"}, True))]
    assert [c[0] for c in tracker.calls] == ["state", "inputs", "select_inputs", "clear_trail"]
    assert client.get("/api/lab/harmony").json()["kind"] == "harmony"


@pytest.mark.parametrize("path, body, problem", [
    ("/api/lab/push", {"slot": 7}, "send 'entry'"),
    ("/api/lab/push", {"entry": "Tonnetz C"}, "send the 'slot' (1–24)"),
    ("/api/lab/push", {"entry": "Tonnetz C", "slot": 7, "offset": "up"}, "'offset' is a whole number of semitones"),
    ("/api/lab/backup", {}, "send {all: true}, or the 'slot' (0–24 or 'globals')"),
    ("/api/lab/import", {"name": "x", "data_base64": "%%%"}, "'data_base64' is not base64"),
    ("/api/lab/globals", {"changes": {"led_level": 100}, "confirm": "yes"}, "'confirm' is true or false"),
    ("/api/lab/globals", {}, "send 'changes' as {field: value}, e.g. {\"led_level\": 100}"),
    ("/api/lab/harmony/inputs", {"inputs": "Keystation"},
     "send 'inputs' as a list of MIDI input port names ([] follows the APC64 only)"),
    ("/api/lab/validate", {"path": "layouts/x.yaml"},
     "send the layout text, not a path: the service never reads paths you name"),
])
def test_a_malformed_request_is_400_and_nothing_is_called(path, body, problem):
    projects, globals_, tracker = Recorder(), Recorder(), Recorder()
    client, _ = client_for(projects=projects, globals=globals_, tracker=tracker)
    answer = client.post(path, json=body)
    assert answer.status_code == 400 and answer.json()["problem"] == problem
    assert projects.calls == globals_.calls == tracker.calls == []


def test_a_body_that_is_not_a_json_object_is_400():
    client, _ = client_for()
    answer = client.post("/api/lab/push", content=b"[1, 2]", headers={"Content-Type": "application/json"})
    assert answer.status_code == 400 and answer.json()["problem"] == "the request body must be a JSON object"


# --- tweaks (A16) -------------------------------------------------------------------------------------------
def test_a_tweak_reaches_the_session_and_maps_each_answer():
    session = Recorder(tweak=Saved(ContentHash.of("x")))
    client, _ = client_for(session=session)
    answer = client.post("/api/lab/tweak", json={"field": "base", "value": "D2"})
    assert answer.status_code == 200 and answer.json()["message"] == "saved lab.base = D2; the layout reloads"
    assert session.calls == [("tweak", ("base", "D2", None))]
    session.answers["tweak"] = Stale()
    assert client.post("/api/lab/tweak", json={"layout": "Tonnetz C", "field": "base", "value": "D2"}).json() == {
        "problem": "layout changed, reload"}
    issue = LayoutIssue(Severity.ERROR, SourceRef("tonnetz-c.yaml", 3), "base", "130 is outside 0–127",
                        "base is 0–127")
    session.answers["tweak"] = Invalid((issue,))
    answer = client.post("/api/lab/tweak", json={"field": "base", "value": 130})
    assert answer.status_code == 400 and answer.json()["line"] == 3 and answer.json()["field"] == "base"
    session.answers["tweak"] = WriteOutcome(OutcomeKind.REFUSED, "no generated layout is active; activate one first",
                                            code=OutcomeCode.SESSION)
    assert client.post("/api/lab/tweak", json={"field": "base", "value": "D2"}).status_code == 409


# --- the real services: the contract's texts reach the client unchanged (s31 supplier side) ---------------
@pytest.fixture
def real():
    rig = Rig()
    services = LabServices(session=Recorder(), projects=rig.memory_service, globals=GlobalSettingsService(rig.writer),
                           tracker=Recorder())
    app = FastAPI()
    app.include_router(lab_router(services))
    return TestClient(app), rig


@pytest.mark.parametrize("body, status, problem", [
    ({"entry": "Tonnetz C", "slot": 25}, 400, "slot 25: slots are 1–24"),                                 # A49
    ({"entry": "Tonnetz C", "slot": 0}, 400,
     "slot 0 is the live edit buffer; activate the layout to play it there"),                              # A50
])
def test_push_refusals_through_the_real_services(real, body, status, problem):
    client, rig = real
    answer = client.post("/api/lab/push", json=body)
    assert answer.status_code == status and answer.json()["problem"] == problem
    assert rig.memory.writes() == []


def test_a_push_through_the_real_services(real):   # A1
    client, rig = real
    answer = client.post("/api/lab/push", json={"entry": "Tonnetz C", "slot": 7})
    assert answer.status_code == 200 and answer.json()["message"] == PUSHED_7
    assert answer.json()["backup"] == "slot7-2026-10-24T20-15"


def test_globals_through_the_real_services(real):   # A62, A64, A66, A67
    client, rig = real
    fields = {f["field"]: f["text"] for f in client.get("/api/lab/globals").json()["fields"]}
    assert fields["led_level"] == "75%"
    answer = client.post("/api/lab/globals", json={"changes": {"device_mode": "standalone"}})
    assert answer.status_code == 400 and answer.json()["problem"].startswith(
        "device mode change needs confirmation: it changes how the unit starts")
    answer = client.post("/api/lab/globals", json={"changes": {"cv3_channel": 17}})
    assert answer.status_code == 400 and answer.json()["problem"] == "CV3 channel 17: channels are 1–16"
    assert client.post("/api/lab/globals", json={"changes": {"led_level": 100}}).json()["message"] == \
        "set LED level 100%"
    assert client.post("/api/lab/globals", json={"changes": {"led_level": 100}}).json()["message"] == \
        "LED level unchanged; nothing written"


def test_an_import_through_the_real_services_counts_the_items(real):   # A56
    client, rig = real
    data = base64.b64encode(file_of(items_of(rig.memory.slots[7].raw)[:580])).decode()
    answer = client.post("/api/lab/import", json={"name": "Short", "data_base64": data})
    assert answer.status_code == 400 and answer.json()["problem"].startswith("580 items, expected 592")


# --- the key for the session (2026-10-29) -----------------------------------------------------------------------
def test_the_key_reaches_the_session_and_a_malformed_one_is_refused():
    session = Recorder(set_key={"message": "key D dorian for the session (the layout's file says C major)"},
                       reset_key={"message": "key C major, as the layout's file says"})
    client, _ = client_for(session=session)
    assert client.post("/api/lab/key", json={"tonic": "D", "scale": "dorian"}).json()["message"].startswith("key D")
    client.post("/api/lab/key", json={"tonic": None})
    client.post("/api/lab/key", json={"layout": True})
    assert session.calls == [("set_key", ("D", "dorian")), ("set_key", (None, None)), ("reset_key", ())]
    bad = client.post("/api/lab/key", json={"key": "D"})
    assert bad.status_code == 400 and bad.json() == {"problem": "unknown key 'key'", "allowed": ["tonic", "scale", "layout"]}
