"""The performer's routes and commands (contract 2 §2.10) over the real PerformerService and pattern files: the same
answer from the API and from `apc64 lab performer|patterns|pattern|validate-pattern`."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from _apc64_lab.application.test_performer import PATTERNS, Rig
from _apc64_lab.composition import offline_pattern
from _apc64_lab.presentation.api import LabServices, lab_router
from _apc64_lab.presentation.cli import LabCli
from _apc64_lab.presentation.test_api import Recorder
from _apc64_lab.presentation.test_cli import ClientTransport, DownTransport, run

BAD = "name: Bad\nlength: 8\nlanes:\n  1: x . . .\n"


def client(rig=None):
    rig = rig or Rig()
    services = LabServices(Recorder(), Recorder(), Recorder(), Recorder(), performer=rig.service, patterns=PATTERNS)
    app = FastAPI()
    app.include_router(lab_router(services))
    return TestClient(app), rig


def test_the_performer_state_and_its_changes():
    c, rig = client()
    state = c.get("/api/lab/performer").json()
    assert state["kind"] == "performer" and state["pattern"]["id"] == "arpeggio-manual-bass"
    answer = c.post("/api/lab/performer", json={"pattern": "waltz", "latch": True, "bpm": 90, "play": "pressed"})
    assert answer.status_code == 200 and answer.json()["message"] == \
        "pattern Waltz 3/4; play pressed; tempo 90 BPM; latch on"
    assert c.post("/api/lab/performer", json={"play": None}).json()["play"] == "all"
    assert c.post("/api/lab/performer/stop", json={}).json()["message"] == "pattern stopped"


def test_refusals_say_what_and_how():
    c, rig = client()
    bad = c.post("/api/lab/performer", json={"pattern": "polka"})
    assert bad.status_code == 400 and bad.json()["problem"].startswith('no pattern "polka"; available: ') and bad.json()["field"] == "pattern"
    assert c.post("/api/lab/performer", json={"tempo": 90}).json() == {
        "problem": "unknown key 'tempo'", "allowed": ["enabled", "pattern", "latch", "play", "bpm", "clock",
                                                                   "pattern_data", "edits", "revert", "new_pattern",
                                                                   "chord_type", "slot"]}
    assert c.post("/api/lab/performer", json={"latch": "yes"}).json()["problem"] == "'latch' is true or false"
    rig.service.on_layout_loaded(object(), None)
    idle = c.post("/api/lab/performer", json={"latch": True})
    assert idle.status_code == 409 and idle.json()["problem"] == "no generated layout is active"


def test_patterns_listed_shown_and_validated():
    c, _ = client()
    listed = c.get("/api/lab/patterns").json()
    assert [row["id"] for row in listed] == ["arpeggio", "arpeggio-manual-bass", "strum", "travis", "waltz"]
    shown = c.get("/api/lab/patterns/Travis pick").json()
    assert shown["id"] == "travis" and [lane["lane"] for lane in shown["lanes"]] == [1, 2, 3, "R", "A"]
    assert shown["lanes"][3] == {"lane": "R", "manual": False, "cells": "X...x..."}
    assert c.get("/api/lab/patterns/polka").status_code == 404
    bad = c.post("/api/lab/patterns/validate", json={"text": BAD, "file": "bad.yaml"})
    assert bad.status_code == 400 and bad.json()["text"] == (
        "bad.yaml line 4, lane 1: 4 steps; length is 8; write one cell per step: . (rest), x (hit) or X (accent); "
        "spaces and | are ignored")
    good = c.post("/api/lab/patterns/validate", json={"text": "name: G\nlanes:\n  1: x . x . x . x .\n"})
    assert good.json()["summary"] == "pattern.yaml: G, 4/4 in 1/8 steps, 8 steps, 1 lanes"


def test_the_commands_print_the_same(tmp_path):
    c, rig = client()
    transport = ClientTransport(c)
    code, out, _ = run(["performer"], transport)
    assert code == 0 and out.splitlines()[0] == ("performer: on · Guitar picker · strings · latch off · play all · "
                                                 "100 BPM")
    assert run(["performer", "latch", "on"], transport)[1] == "latch on\n"
    assert run(["performer", "tempo", "clock", "MPC", "Live", "III", "MIDI", "1"], transport)[1] == \
        "tempo from the MIDI clock of MPC Live III MIDI 1\n"
    assert run(["performer"], transport)[1].splitlines()[0].endswith(
        "clock MPC Live III MIDI 1: no clock heard from MPC Live III MIDI 1 yet (the MPC sends its clock while its "
        "sequencer plays, to the outputs its sync settings send clock to)")
    assert run(["performer", "tempo", "clock", "auto"], transport)[1] == \
        "tempo from the MIDI clock of the first input that sends one\n"
    assert run(["performer", "play", "pattern"], transport)[1] == "play all\n"
    assert run(["performer", "stop"], transport)[1] == "pattern stopped\n"
    code, _, err = run(["performer", "jump"], transport)
    assert code == 1 and err.startswith("write: on | off | stop")
    code, out, _ = run(["pattern", "waltz"], transport)
    assert out.splitlines()[:2] == ["Waltz 3/4  3/4 · 1/4 · 6 steps · play all", "   1: . x x | . x x"]
    assert out.splitlines()[-1] == "  strum: . d d | . d d"
    assert run(["patterns"], transport)[1].splitlines()[0] == "arpeggio  Arpeggio 8ths  4/4 · 1/8 · 8 steps · play all"
    path = tmp_path / "bad.yaml"
    path.write_text(BAD)
    code, _, err = run(["validate-pattern", str(path)], DownTransport(), LabCli(pattern_offline=offline_pattern))
    assert code == 1 and err.startswith("bad.yaml line 4, lane 1: 4 steps; length is 8")


def test_the_editor_writes_validates_deletes_and_restores_through_the_api_and_the_commands(tmp_path):
    import shutil
    from pathlib import Path
    from _apc64_lab.application.pattern_library import PatternLibrary
    from _apc64_lab.application.test_performer import GUITAR
    from _apc64_lab.infrastructure.pattern_files import PatternFiles
    shutil.copytree(Path(__file__).resolve().parents[2] / "patterns", tmp_path / "patterns")
    library = PatternLibrary(PatternFiles(tmp_path / "patterns", tmp_path / "versions"))
    rig = Rig(GUITAR, patterns=library)
    services = LabServices(Recorder(), Recorder(), Recorder(), Recorder(), performer=rig.service, patterns=library)
    app = FastAPI()
    app.include_router(lab_router(services))
    c = TestClient(app)
    shown = c.get("/api/lab/patterns/waltz").json()
    assert shown["file"] == "waltz.yaml" and shown["text"].startswith("# Waltz") and len(shown["hash"]) == 12
    data = {**shown["data"], "name": "Waltz 2"}
    assert c.post("/api/lab/patterns/validate", json={"data": data}).json()["valid"]
    bad = c.post("/api/lab/patterns/validate", json={"data": {**data, "step": "1/5"}})
    assert bad.status_code == 400 and bad.json()["issues"][0]["field"] == "step"
    stale = c.post("/api/lab/patterns/save", json={"id": "waltz", "data": data, "base": "000000000000"})
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
    saved = c.post("/api/lab/patterns/save", json={"id": "waltz", "data": data, "base": shown["hash"]})
    assert saved.status_code == 200 and saved.json()["message"] == "saved patterns/waltz.yaml (Waltz 2)"
    created = c.post("/api/lab/patterns/save", json={"data": {**data, "name": "Waltz three"}, "create": True})
    assert created.json()["id"] == "waltz-three"
    played = c.post("/api/lab/performer", json={"pattern_data": {**data, "lanes": {"1": "x"}}, "edits": None})
    assert played.status_code == 400 and played.json()["issues"][0]["field"] == "lane 1"
    assert c.post("/api/lab/performer", json={"pattern_data": data}).json()["problem"] == \
        "send 'pattern_data' with 'edits': the id of the pattern it edits (null for a new one)"
    playing = c.get("/api/lab/performer").json()["pattern"]
    edit = {**playing["data"], "swing": 60}
    stale = c.post("/api/lab/performer", json={"pattern_data": edit, "edits": "waltz"})
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
    kept = c.post("/api/lab/performer", json={"pattern_data": edit, "edits": playing["id"]}).json()
    assert kept["pattern"]["edited"] and kept["edits"][0]["id"] == playing["id"]
    transport = ClientTransport(c)
    assert run(["performer"], transport)[1].splitlines()[1:3] == [
        f"pattern: {edit['name']} ({playing['id']}, edited, not saved) · stopped",
        f"unsaved edits (kept until the service restarts): {playing['id']}"]
    assert run(["performer", "revert", playing["id"]], transport)[1] == f"{playing['id']}: the unsaved edit dropped\n"
    c.post("/api/lab/performer", json={"pattern_data": edit, "edits": playing["id"]})
    saved = c.post("/api/lab/patterns/save", json={"id": playing["id"], "data": edit, "base": playing["hash"],
                                                   "edits": playing["id"]})
    assert saved.status_code == 200 and c.get("/api/lab/performer").json()["edits"] == []
    c.post("/api/lab/performer", json={"pattern_data": {**data, "name": "Brand new"}, "edits": None})
    c.post("/api/lab/performer", json={"pattern": "waltz"})
    assert run(["performer", "new"], transport)[1] == "pattern Brand new (new, not saved)\n"
    transport = ClientTransport(c)
    versions = run(["pattern-versions", "waltz"], transport)[1].split()
    assert len(versions) == 1
    assert run(["restore-pattern", "waltz", versions[0]], transport)[1].startswith("restored patterns/waltz.yaml")
    path = tmp_path / "mine.yaml"
    path.write_text("name: Mine\nlanes:\n  R: x . x . x . x .\n")
    assert run(["write-pattern", str(path)], transport)[1] == "created patterns/mine.yaml (Mine)\n"
    code, _, err = run(["write-pattern", str(path), "--new"], transport)
    assert code == 1 and err.startswith("patterns/mine.yaml exists")
    path.write_text(BAD)
    code, _, err = run(["write-pattern", str(path), "--id", "mine"], transport)
    assert code == 1 and err.startswith("mine.yaml line 4, lane 1: 4 steps")
    assert run(["delete-pattern", "mine"], transport)[1].startswith("deleted patterns/mine.yaml; kept as version ")
    assert c.post("/api/lab/patterns/delete", json={"id": "polka"}).status_code == 404


def test_chord_types_and_slots_from_the_api_and_the_commands():   # Phase 2
    from _apc64_lab.application.test_performer_chords import PICKER
    c, _ = client(Rig(PICKER.format(tuning="e-standard")))
    answer = c.post("/api/lab/performer", json={"chord_type": "m7"}).json()
    assert answer["message"] == "chord type m7: one note held is its root" and answer["chords"]["selected"] == "m7"
    both = c.post("/api/lab/performer", json={"slot": 4, "chord_type": None}).json()
    assert both["message"] == "pattern Strum d-u; chord type off: what you fret plays" and both["slot"] == 4
    assert c.post("/api/lab/performer", json={"slot": 3}).json()["problem"].startswith("slot 3 holds no pattern")
    assert c.post("/api/lab/performer", json={"chord_type": "polka"}).status_code == 400
    transport = ClientTransport(c)
    assert run(["performer", "type", "sus4"], transport)[1] == "chord type sus4: one note held is its root\n"
    assert run(["performer", "slot", "2"], transport)[1] == "pattern Travis pick\n"
    lines = run(["performer"], transport)[1].splitlines()
    assert "chord type: sus4 (maj, min, 7, maj7, m7, sus2, sus4, dim)" in lines
    assert "slots: 1 1-2-3 + bass · *2 Travis pick · 4 Strum d-u" in lines
    assert "pads: top row: chord types · bottom row: pattern slots" in lines
