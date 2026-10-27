"""T36: the `apc64 lab …` commands (s28 supplier, s29 consumer; inv9).

Over an HTTP double: each command parses its arguments, sends its request and prints the returned message (exit 0),
or the problem on stderr (exit 1). Through the real router and services: the contract's texts come out as given."""
import argparse
import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from _apc64_lab.application.global_settings import GlobalSettingsService
from _apc64_lab.application.test_project_memory import PUSHED_7, Rig
from _apc64_lab.presentation.api import LabServices, lab_router
from _apc64_lab.presentation.cli import LabCli
from _apc64_lab.presentation.test_api import Recorder


class FakeTransport:
    def __init__(self, answers=None):
        self.requests, self.answers = [], answers or {}

    def request(self, method, path, body=None):
        self.requests.append((method, path, body))
        return self.answers.get((method, path), (200, {"result": "unchanged", "backup": None, "message": "done"}))


class ServiceDown(Exception):
    """As the host transport raises it when nothing answers."""


class DownTransport:
    def request(self, method, path, body=None):
        raise ServiceDown("connection refused")


class ClientTransport:
    """The real router over TestClient, as the host's HttpTransport would reach it."""

    def __init__(self, client):
        self.client = client

    def request(self, method, path, body=None):
        answer = self.client.request(method, path, json=body) if body is not None else self.client.request(method, path)
        return answer.status_code, answer.json()


def run(argv, transport, cli=None):
    parser = argparse.ArgumentParser(prog="apc64")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    cli = cli or LabCli()
    cli.register(sub, common)
    args = parser.parse_args(["lab", *argv])
    out, err = io.StringIO(), io.StringIO()
    code = cli.run(args, transport, out, err, args.json)
    return code, out.getvalue(), err.getvalue()


# --- the T36 rows -------------------------------------------------------------------------------------------
def test_push_prints_the_message_and_exits_0():   # A1, A60
    transport = FakeTransport({("POST", "/api/lab/push"): (200, {"result": "pushed", "backup": "slot7-2026-10-24T20-15",
                                                                 "message": PUSHED_7})})
    code, out, err = run(["push", "Tonnetz C", "7"], transport)
    assert (code, out, err) == (0, PUSHED_7 + "\n", "")
    assert transport.requests == [("POST", "/api/lab/push", {"entry": "Tonnetz C", "slot": 7})]


def test_a_refused_globals_change_prints_the_problem_once_and_exits_1():   # A66
    transport = FakeTransport({("POST", "/api/lab/globals"): (400, {
        "problem": "CV3 channel 17: channels are 1–16", "fix": "channels are 1–16", "field": "cv3_channel"})})
    code, out, err = run(["globals", "cv3_channel=17"], transport)
    assert (code, out, err) == (1, "", "CV3 channel 17: channels are 1–16\n")
    assert transport.requests == [("POST", "/api/lab/globals", {"changes": {"cv3_channel": 17}})]


def test_a_fix_the_problem_does_not_say_is_printed_after_it():
    transport = FakeTransport({("POST", "/api/lab/restore"): (404, {
        "problem": "no backup slot7-2026-10-24T12-00", "fix": "list the backups with 'apc64 lab backups'"})})
    code, _, err = run(["restore", "slot7-2026-10-24T12-00", "7"], transport)
    assert code == 1 and err.splitlines() == ["no backup slot7-2026-10-24T12-00",
                                              "list the backups with 'apc64 lab backups'"]


# --- each command sends its request (s29.c1) ----------------------------------------------------------------
@pytest.mark.parametrize("argv, sent", [
    (["activate", "Tonnetz C"], ("POST", "/api/lab/activate", {"layout": "Tonnetz C"})),
    (["leave"], ("POST", "/api/lab/leave", {})),
    (["tweak", "base", "D2"], ("POST", "/api/lab/tweak", {"field": "base", "value": "D2"})),
    (["tweak", "row", "4", "--layout", "Fourths"], ("POST", "/api/lab/tweak", {"field": "row", "value": 4,
                                                                              "layout": "Fourths"})),
    (["push", "Tonnetz C", "8", "--offset", "7"], ("POST", "/api/lab/push", {"entry": "Tonnetz C", "slot": 8,
                                                                            "offset": 7})),
    (["preview", "Live set B"], ("POST", "/api/lab/preview", {"entry": "Live set B"})),
    (["backup"], ("POST", "/api/lab/backup", {"all": True})),
    (["backup", "--all"], ("POST", "/api/lab/backup", {"all": True})),
    (["backup", "--slot", "7"], ("POST", "/api/lab/backup", {"slot": 7})),
    (["backup", "--globals"], ("POST", "/api/lab/backup", {"slot": "globals"})),
    (["restore", "globals-2026-10-24T12-00", "globals"], ("POST", "/api/lab/restore", {
        "backup": "globals-2026-10-24T12-00", "slot": "globals"})),
    (["capture", "12", "Live set B"], ("POST", "/api/lab/library/capture", {"slot": 12, "name": "Live set B"})),
    (["bulk-edit", "5", "all pads channel 3", "pads r1c1-r2c8 colour red"], ("POST", "/api/lab/bulk-edit", {
        "target": "5", "edits": ["all pads channel 3", "pads r1c1-r2c8 colour red"]})),
    (["globals", "led_level=100", "cv2_channel=4"], ("POST", "/api/lab/globals", {
        "changes": {"led_level": 100, "cv2_channel": 4}})),
    (["globals", "device_mode=standalone", "--confirm"], ("POST", "/api/lab/globals", {
        "changes": {"device_mode": "standalone"}, "confirm": True})),
    (["inputs", "Keystation 49 MIDI 1"], ("POST", "/api/lab/harmony/inputs", {"inputs": ["Keystation 49 MIDI 1"]})),
    (["inputs", "--none"], ("POST", "/api/lab/harmony/inputs", {"inputs": []})),
    (["trail", "clear"], ("POST", "/api/lab/harmony/trail/clear", {})),
    (["trail"], ("GET", "/api/lab/harmony", None)),
    (["dismiss-recovery"], ("POST", "/api/lab/recovery/dismiss", {})),
])
def test_each_command_sends_its_request(argv, sent):
    answers = {("POST", "/api/lab/harmony/inputs"): (200, {"apc64": ["APC64 Custom"], "inputs": [], "message": "ok"}),
               ("GET", "/api/lab/harmony"): (200, {"trail": ["C", "Am"]})}
    transport = FakeTransport(answers)
    code, out, _ = run(argv, transport)
    assert code == 0 and transport.requests == [sent]


LAB_STATE = {"kind": "lab", "generators": [
    {"name": "tonnetz", "file": "_apc64_lab/domain/generators.py", "params": [
        {"name": "base", "kind": "note", "default": 48, "min": 0, "max": 127, "doc": ""},
        {"name": "channel", "kind": "channel", "default": 1, "min": 1, "max": 16, "doc": ""}]},
    {"name": "spiral", "file": "_apc64_lab/generators/spiral.py", "broken": True, "error": "division by zero"}],
    "schemes": [{"name": "fifths", "file": "x"}, {"name": "root-highlight", "file": "y"}],
    "active": {"layout": "tonnetz-c", "name": "Tonnetz C", "preview": False, "oled": ["Tonnetz C", "5th +2"],
               "session_backup": "slot0-2026-10-24T20-15"},
    "message": None, "recovery": None, "target": {"default": None, "routed": False,
                                                  "text": "notes are only shown: no default target and no layout target"},
    "warnings": []}


def test_list_shows_generators_with_parameters_broken_ones_and_the_active_layout():   # A17, A19
    transport = FakeTransport({("GET", "/api/lab"): (200, LAB_STATE)})
    code, out, _ = run(["list"], transport)
    assert code == 0
    assert out.splitlines() == [
        "generators:",
        "  tonnetz  base 0–127 (default 48), channel 1–16 (default 1)",
        "  spiral  broken: division by zero  (_apc64_lab/generators/spiral.py)",
        "colour schemes: fifths, root-highlight",
        "active: Tonnetz C  5th +2  (encoder: shift · Tempo: interval)",
        "  session backup: slot0-2026-10-24T20-15",
        "notes: notes are only shown: no default target and no layout target"]


def test_list_shows_a_guitar_layouts_tuning_and_its_own_window_steps():   # the guitar amendment
    guitar = {"name": "guitar", "file": "_apc64_lab/generators/guitar.py", "params": [
        {"name": "tuning", "kind": "notes", "default": "e-standard", "min": 4, "max": 8, "doc": "",
         "choices": ["e-standard", "drop-d"]},
        {"name": "frets", "kind": "int", "default": 24, "min": 12, "max": 36, "doc": ""}]}
    state = {**LAB_STATE, "generators": [guitar], "active": {
        "layout": "guitar", "name": "Guitar", "preview": False, "oled": ["Guitar", "Page 8-15"], "counts": {},
        "window": {"steps": ["Fret", "Page"], "step": "Page"}, "session_backup": "slot0-2026-10-27T10-00"}}
    _, out, _ = run(["list"], FakeTransport({("GET", "/api/lab"): (200, state)}))
    assert "  guitar  tuning: e-standard, drop-d, or a list of 4–8 notes (default e-standard), frets 12–36 (default 24)" \
        in out.splitlines()
    assert "active: Guitar  Page 8-15  (encoder: one page · Tempo: Fret ↔ Page)" in out.splitlines()


def test_reading_commands_print_their_lines():
    harmony = {"kind": "harmony", "held": [{"note": 48, "name": "C2", "pc": 0}, {"note": 52, "name": "E2", "pc": 4},
                                           {"note": 55, "name": "G2", "pc": 7}],
               "chord": "C", "triads": [{"root": 0, "quality": "major", "label": "C"}], "degrees": {},
               "hints": [], "neighbours": [{"root": 0, "quality": "minor", "label": "Cm"},
                                           {"root": 9, "quality": "minor", "label": "Am"},
                                           {"root": 4, "quality": "minor", "label": "Em"}],
               "trail": ["C"], "circle": ["C", "G", "E"]}
    transport = FakeTransport({("GET", "/api/lab/harmony"): (200, harmony),
                               ("GET", "/api/lab/globals"): (200, {"fields": [
                                   {"field": "led_level", "label": "LED level", "value": 2, "text": "75%"}]}),
                               ("GET", "/api/lab/backups"): (200, {"backups": [
                                   {"id": "slot7-2026-10-24T12-00", "target": "slot7", "size": 880}], "sets": []}),
                               ("GET", "/api/lab/library"): (200, [
                                   {"name": "Tonnetz C", "kind": "definition", "layout": "tonnetz-c",
                                    "generator": "tonnetz"},
                                   {"name": "Live set B", "kind": "captured", "source": "slot 12", "pads": 64,
                                    "strips": 8}])})
    assert run(["harmony"], transport)[1].splitlines() == [
        "chord: C", "held: C2 E2 G2", "triads: C", "neighbours: Cm, Am, Em", "trail: C", "circle of fifths: C – G – E"]
    assert run(["globals"], transport)[1] == "LED level: 75%\n"
    assert run(["backups", "--slot", "7"], transport)[1] == "slot7-2026-10-24T12-00  slot7  880 bytes\n"
    assert run(["library"], transport)[1].splitlines() == [
        "Tonnetz C  generated (tonnetz, tonnetz-c.yaml)", "Live set B  captured from slot 12  64 pads, 8 strips"]


def test_json_prints_the_api_answer():
    transport = FakeTransport({("GET", "/api/lab"): (200, LAB_STATE)})
    code, out, _ = run(["list", "--json"], transport)
    assert code == 0 and json.loads(out)["active"]["name"] == "Tonnetz C"


def test_import_sends_the_file_as_base64(tmp_path):
    preset = tmp_path / "Boss RC-600.APC64"
    preset.write_bytes(b"\x03\x00\x00\x00")
    transport = FakeTransport()
    code, _, _ = run(["import", "Boss RC-600", str(preset)], transport)
    assert code == 0 and transport.requests == [("POST", "/api/lab/import", {
        "name": "Boss RC-600", "file": "Boss RC-600.APC64", "data_base64": "AwAAAA=="})]


def test_a_malformed_pair_is_refused_before_anything_is_sent():
    transport = FakeTransport()
    code, _, err = run(["globals", "led_level"], transport)
    assert code == 1 and err == "'led_level' is not FIELD=VALUE; write e.g. led_level=100\n"
    assert transport.requests == []


# --- validate: through the service, and offline ----------------------------------------------------------------
def test_validate_prints_every_issue_and_exits_1(tmp_path):   # A10
    path = tmp_path / "tonnetz-c.yaml"
    path.write_text("name: Tonnetz C\nlab:\n  base: 110\n  generator: tonnetz\n")
    issue = "tonnetz-c.yaml line 3, base: 110 puts pad r8c8 at note 138; the highest base is 99"
    transport = FakeTransport({("POST", "/api/lab/validate"): (400, {"problem": "…", "issues": [{"text": issue}]})})
    code, out, err = run(["validate", str(path)], transport)
    assert (code, out, err) == (1, "", issue + "\n")
    assert transport.requests[0][2] == {"text": path.read_text(), "file": "tonnetz-c.yaml"}


def test_validate_without_the_service_compiles_here(tmp_path):
    from _apc64_lab.composition import offline_validation
    path = tmp_path / "t.yaml"
    path.write_text("name: T\nlab:\n  generator: tonnetz\n  scheme: root-highlight\n")
    code, out, _ = run(["validate", str(path)], DownTransport(), LabCli(offline_validation))
    assert code == 0 and out.strip().endswith("(ports not checked)")
    path.write_text("name: T\nlab:\n  generator: tonetz\n")
    code, _, err = run(["validate", str(path)], DownTransport(), LabCli(offline_validation))
    assert code == 1 and err == 't.yaml line 3: no generator "tonetz"; available: guitar, isomorphic, modes, tonnetz\n'


def test_without_an_offline_compiler_service_down_reaches_the_host_command():
    with pytest.raises(ServiceDown):
        run(["list"], DownTransport())


# --- through the real router and services (s29 supplier) ------------------------------------------------
@pytest.fixture
def real():
    rig = Rig()
    services = LabServices(session=Recorder(), projects=rig.memory_service, globals=GlobalSettingsService(rig.writer),
                           tracker=Recorder())
    app = FastAPI()
    app.include_router(lab_router(services))
    return ClientTransport(TestClient(app)), rig


def test_the_real_texts_come_out_as_the_contract_gives_them(real):   # A1, A49, A50, A66
    transport, rig = real
    assert run(["push", "Tonnetz C", "7"], transport)[:2] == (0, PUSHED_7 + "\n")
    assert run(["push", "Tonnetz C", "25"], transport)[0::2] == (1, "slot 25: slots are 1–24\n")
    assert run(["push", "Tonnetz C", "0"], transport)[0::2] == (
        1, "slot 0 is the live edit buffer; activate the layout to play it there\n")
    assert run(["globals", "cv3_channel=17"], transport)[0::2] == (1, "CV3 channel 17: channels are 1–16\n")
    code, out, _ = run(["globals", "led_level=100", "cv2_channel=4"], transport)
    assert (code, out) == (0, "set LED level 100% and CV2 channel 4\n")
