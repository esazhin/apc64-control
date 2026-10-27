"""s13/s14 supplier: one case per view and message type (T30). Shapes are those of docs/api.md."""
import json
from datetime import datetime

from _apc64_host.application.activity import ActivityLog
from _apc64_host.application.layout_pipeline import ValidationReport
from _apc64_host.application.play_stream import StreamClosed
from _apc64_host.application.ports import PortDirection, PortInfo
from _apc64_host.application.test_state_view import AT, R1C1, Rig
from _apc64_host.domain.calibration import Calibration
from _apc64_host.domain.controls import PadPos, Strip, TrackButton
from _apc64_host.domain.effects import ActivityEntry, ActivityResult, InputSource, PlayEvent, Press, UnitView
from _apc64_host.domain.issues import LayoutIssue, Severity, SourceRef
from _apc64_host.domain.layout import ContentHash, LayoutId, VersionId
from _apc64_host.domain.outbound import DeviceLogEntry, DeviceLogOutcome, SysexCommand
from _apc64_host.domain.unit_status import Busy, Held, Holder
from _apc64_host.notation.compiler import compile_text
from _apc64_host.presentation import view_model as vm


def same_twice(fn, *args, **kwargs):
    """Deterministic and JSON-safe: two calls give the same JSON text."""
    first, second = fn(*args, **kwargs), fn(*args, **kwargs)
    text = json.dumps(first, sort_keys=False)
    assert text == json.dumps(second, sort_keys=False)
    return json.loads(text)


def test_state_json_carries_every_section_of_the_api_state():
    rig = Rig()
    rig.session.set(Held(by="agent"))
    data = same_twice(vm.state_json, rig.view.snapshot())
    assert list(data)[:10] == ["unit", "layout", "layout_name", "file_deleted", "page", "bank", "shift", "pages",
                               "banks", "controls"]
    assert data["unit"]["status"] == "held" and data["unit"]["text"] == "Held (taken by command-line tool)"
    assert data["unit"]["view"] == "session"
    assert data["layout"] == "jam" and data["page"]["n"] == 1 and data["page"]["display"] == "Drums"
    assert data["bank"]["display"] == "Mix" and data["shift"] is False
    assert [p["defined"] for p in data["pages"]] == [True, True] + [False] * 6
    pad = data["controls"]["pad r1c1"]
    assert pad["label_base"] == "Note 36 → mpc" and pad["label_shift"] == "Note 48 → mpc"
    assert pad["empty"] is False and pad["role"] == "bindable"
    assert pad["led"]["colour"] == 5 and pad["led"]["rgb"].startswith("#") and pad["led"]["brightness"] == 0.25
    assert data["controls"]["pad r8c8"]["empty"] is True and data["controls"]["pad r8c8"]["label_base"] == ""
    assert data["controls"]["track 1"]["toggle"] is False
    assert data["controls"]["strip 1"]["bar"]["style"] == "bar"
    assert data["oled"][0] == "Jam" and len(data["oled"]) == 2
    assert data["routing"]["status"] == "expressive pads not routed in this layout"
    assert data["calibration"] is None and data["calibration_label"] == "pad position unknown"
    assert data["learn"] == {"mode": "off", "selected": None, "port": None, "device": None, "last": None}
    assert data["layouts"][0]["id"] == "jam" and data["layouts"][0]["file"] == "jam.yaml"
    assert "approximate" in data["palette_note"]


def test_busy_unit_and_issues_and_calibration_and_played_notes():
    rig = Rig(calibration=Calibration(AT, 36, 99))
    rig.session.set(Busy(holder=Holder("Bitwig Studio")))
    rig.library.set_issues(LayoutId("broken"), [LayoutIssue(Severity.ERROR, SourceRef("broken.yaml", 7), None,
                                                            "unknown device mcp", "declared devices: mpc")])
    data = vm.state_json(rig.view.snapshot())
    assert data["unit"]["text"] == "Busy: held by Bitwig Studio" and data["unit"]["holder"] == "Bitwig Studio"
    assert data["errors"] == [{"file": "broken.yaml", "line": 7, "control": None, "problem": "unknown device mcp",
                               "fix": "declared devices: mpc", "severity": "error",
                               "text": "broken.yaml line 7: unknown device mcp; declared devices: mpc"}]
    assert data["calibration"]["label"] == "calibrated 14:02 (assumed)"
    note = vm.played_json(type("P", (), dict(role="notes", note=53, label="F2 (53)", velocity=56, aftertouch=0,
                                             routed=False, pad=None, position="pad position unknown"))())
    assert note["text"] == "F2 (53) vel 56 · pad position unknown"   # A122 (with q1: C3 = 60)


def test_diff_json_has_only_what_changed_in_the_same_shapes():
    rig = Rig()
    items = []
    rig.view.subscribe(items.append)
    rig.engine.select_page(2)
    message = same_twice(vm.state_message, items[-1])
    assert message["type"] == "diff"
    assert message["data"]["changed"]["page"]["n"] == 2
    assert "unit" not in message["data"]["changed"]
    assert message["data"]["controls"]["pad r1c1"]["label_base"] == "Note 50 → mpc"
    assert vm.state_message(items[0])["type"] == "snapshot"


def test_card_json_has_both_layers_mode_ports_elsewhere_and_the_tweak_context():
    rig = Rig()
    view = rig.view.card("pad r1c1")
    data = same_twice(vm.card_json, view, layout="jam", page=1, bank=1, layer="base", base_hash="abc")
    assert data["base"] == "Note 36 → mpc ch 10, momentary" and data["shift"].startswith("Note 48 → mpc")
    assert data["mode"] == "momentary" and data["port_status"] == ["mpc connected"]
    assert data["elsewhere"] == [{"page": 2, "bank": None, "layer": "base", "binding": "Note 50",
                                  "text": "Page 2: Note 50"}]
    assert data["forms"]["base"]["assignment"].startswith("note 36 on mpc")
    assert data["forms"]["base"]["colour"]["name"] == "red"
    assert (data["layout"], data["page"], data["bank"], data["layer"], data["base_hash"]) == ("jam", 1, 1, "base", "abc")
    toggle = vm.card_json(rig.view.card("track 1"), layer="base")
    assert toggle["mode"] == "toggle" and toggle["toggle"] is False
    empty = vm.card_json(rig.view.card("pad r8c8"), layer="base")
    assert empty["base"] is None and empty["forms"] == {"base": None, "shift": None}


def test_overview_and_surface_json():
    rig = Rig()
    overview = same_twice(vm.overview_json, rig.view.overview())
    assert overview["page"] == 1 and len(overview["pages"]) == 8 and len(overview["banks"]) == 6
    assert overview["pages"][1]["base"]["pad r1c1"]["label"] == "Note 50 → mpc"
    assert overview["pages"][0]["base"]["pad r1c1"]["colour"] == 5
    surface = same_twice(vm.surface_json, rig.view.surface())
    names = [c["id"] for c in surface["controls"]]
    assert "pad r1c1" in names and "strip 8" in names and "view note" in names
    pad = next(c for c in surface["controls"] if c["id"] == "pad r1c1")
    assert pad["geometry"]["y"] == 8 and pad["role"] == "bindable" and pad["led"] == "rgb"
    assert len(surface["palette"]) == 128 and surface["approximate"] is True


def test_validation_json_matches_the_cli_and_page_text():
    text = "name: Jam\ndevices:\n  mpc: MPC Live III MIDI 1\npages:\n  1 Drums:\n    pad r9c1: note 36\n"
    result = compile_text(text, "jam.yaml")
    report = ValidationReport(result.valid, result.issues, result.warnings, result.counts, result.summary(),
                              result.ports_checked)
    data = same_twice(vm.validation_json, report)
    assert data["valid"] is False and data["summary"].startswith("invalid")
    assert data["errors"][0]["text"].startswith("jam.yaml line 6, pad r9c1: no such pad")
    good = compile_text("name: Jam\ndevices:\n  mpc: MPC\npages:\n  1:\n    pad r1c1: note 36\n", "jam.yaml")
    ok = vm.validation_json(ValidationReport(good.valid, good.issues, good.warnings, good.counts, good.summary(),
                                             good.ports_checked))
    assert ok["valid"] and ok["counts"]["pads"] == 1 and ok["ports_checked"] is False
    assert ok["summary"] == "valid: 1 page, 0 banks, 1 pad bound (ports not checked)" or "ports not checked" in ok["summary"]


def test_activity_play_and_closed_messages():
    log = ActivityLog()
    record = log.append(ActivityEntry("pad r1c1", ActivityResult.SENT, "note 36 ch 10", "MPC Live III MIDI 1",
                                      note=None, at=1761228120.1234))
    message = same_twice(vm.activity_message, record)
    assert message == {"type": "activity", "data": {
        "id": 1, "folded": False, "at": 1761228120.123, "control": "pad r1c1", "message": "note 36 ch 10",
        "port": "MPC Live III MIDI 1", "result": "sent", "reason": None, "note": None, "aftertouch": None,
        "text": "pad r1c1 → note 36 ch 10 → MPC Live III MIDI 1: sent"}}           # A120
    refused = vm.activity_json(ActivityEntry("host", ActivityResult.REFUSED, "project write (0x14)", "APC64"))
    assert refused["text"] == "refused: project write (0x14)" and refused["result"] == "refused"   # A31
    missing = vm.activity_json(ActivityEntry("pad r1c1", ActivityResult.NOT_SENT, "note 36 ch 10", "mpc",
                                             "mpc missing"))
    assert missing["text"] == "pad r1c1 → note 36 ch 10 → mpc: not sent, mpc missing"
    assert vm.activity_list_message(log.records())["data"][0]["id"] == 1
    event = PlayEvent("press", InputSource.UNIT, UnitView.SESSION, PadPos(1, 1), velocity=127,
                      sent=("note 36 ch 10 → mpc",), at=10.5)
    assert same_twice(vm.play_message, event) == {"type": "event", "data": {
        "at": 10.5, "kind": "press", "source": "unit", "view": "session", "control": "pad r1c1", "note": None,
        "value": None, "velocity": 127, "aftertouch": None, "sent": ["note 36 ch 10 → mpc"], "reason": None}}
    closed = vm.closed_message(StreamClosed("too slow").reason)
    assert closed["type"] == "closed" and closed["reason"] == "too slow"
    assert closed["data"]["text"] == "stream closed: too slow"                    # A124


def test_ports_versions_device_log_and_layout_summaries():
    ports = vm.ports_json([PortInfo("MPC Live III MIDI 1", PortDirection.BOTH)],
                          declared_missing=[("bitwig", "Bitwig Studio In")])
    assert ports == [{"name": "MPC Live III MIDI 1", "direction": "both", "present": True, "device": None},
                     {"name": "Bitwig Studio In", "direction": "declared", "present": False, "device": "bitwig"}]
    version = VersionId("20261023T104200.123Z", ContentHash("ab" * 32))
    assert vm.versions_json([version]) == [{"id": f"20261023T104200.123Z-{'ab' * 6}",
                                           "at": "2026-10-23T10:42:00.123Z", "hash": "ab" * 32}]
    entries = [DeviceLogEntry(1.0, bytes([0xF0, 0x47, 0x00, 0x53, 0x14, 0x00, 0x00, 0xF7]),
                              DeviceLogOutcome.REFUSED, SysexCommand.PROJECT_WRITE)]
    log = vm.device_log_json(entries)
    assert log[0]["hazard"] is True and log[0]["text"] == "refused: project write (0x14)"
    assert log[0]["hex"] == "F0 47 00 53 14 00 00 F7"
    rig = Rig()
    assert vm.layout_summary_json(rig.library.summaries()[0])["pages"] == 2


def test_problem_answers_are_json_safe():
    assert vm.problem("page must be 1–8", allowed=list(range(1, 9))) == {
        "problem": "page must be 1–8", "allowed": [1, 2, 3, 4, 5, 6, 7, 8]}
    assert vm.problem("no layout x", allowed=(LayoutId("jam"),)) == {"problem": "no layout x", "allowed": ["jam"]}
    assert json.dumps(vm.problem("x", when=datetime(2026, 1, 1)))
