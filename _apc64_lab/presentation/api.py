"""The /api/lab… router (contract §3.5, s27 supplier, s29 supplier, s31 consumer; inv9, inv10).

Every lab action the page and the `apc64 lab` command take goes through these routes, so the page, the CLI and an
agent get the same result and the same one message (inv9). The router maps requests onto the lab's use cases and
their answers onto JSON:

- a WriteOutcome that went through is 200 `{result, backup, message}` (§3.5), plus what the command produced
  (a backup-set id, an import summary);
- a refused or failed one is `{problem, fix?, field?, result, backup}` with the status of its code: invalid 400;
  busy, not_held, session, taken and firmware 409 (A7 is busy); not_found 404; corrupt 422; storage 500; unit 502;
- a layout issue (validate, tweak) is 400 `{problem, fix, file, line, field, issues}`;
- a malformed request is 400 `{problem, allowed?}`, and nothing is read or written.

Calls that touch the unit or files block (a read waits up to 2 s, 'back up all' is 26 reads), so those routes are
plain functions, run by FastAPI's threadpool; routes that hand work to the host engine (activate, preview, tweak,
the harmony inputs) run on the loop, as the engine's ports require. Beyond §3.5: leave, preview,
bulk-edit, recovery/dismiss and harmony/inputs, each with its `apc64 lab` twin.
"""
import asyncio
import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from _apc64_host.domain.issues import DomainInvariantError, in_line_order

from ..domain.memory import OutcomeCode, OutcomeKind, WriteOutcome

STATUS = {OutcomeCode.INVALID: 400, OutcomeCode.BUSY: 409, OutcomeCode.NOT_HELD: 409, OutcomeCode.SESSION: 409,
          OutcomeCode.TAKEN: 409, OutcomeCode.FIRMWARE: 409, OutcomeCode.NOT_FOUND: 404,
          OutcomeCode.CORRUPT: 422, OutcomeCode.STORAGE: 500, OutcomeCode.UNIT: 502}
STALE = "layout changed, reload"


@dataclass
class LabServices:
    """What the router calls (constructor-injected by the lab composition root; doubles in tests)."""
    session: Any                 # SessionService: state, activate, leave, tweak, dismiss_recovery
    projects: Any                # ProjectMemory: backups, slots, push, preview, restore, import, capture, bulk edit
    globals: Any                 # GlobalSettingsService: read, change
    tracker: Any                 # HarmonyTracker: state, inputs, select_inputs
    validate: Callable[[str, str], Any] | None = None   # (text, file) → the host's compile result


class Problem(Exception):
    def __init__(self, status: int, body: dict):
        self.status, self.body = status, body
        super().__init__(body.get("problem"))


def _bad(problem: str, allowed=None) -> Problem:
    body = {"problem": problem}
    if allowed is not None:
        body["allowed"] = list(allowed)
    return Problem(400, body)


async def _body(request: Request) -> dict:
    raw = await request.body()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise _bad("the request body is not JSON") from None
    if not isinstance(data, dict):
        raise _bad("the request body must be a JSON object")
    return data


def _text(data: dict, key: str, allowed, required: bool = True) -> str | None:
    value = data.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise _bad(f"send '{key}'", allowed)
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _bad(f"'{key}' must be text", allowed)
    return str(value).strip()


def outcome_response(outcome: WriteOutcome) -> JSONResponse:
    """A WriteOutcome as §3.5's JSON with its status (the one message, never rephrased)."""
    if outcome.ok:
        body = outcome.to_json()
        for key, value in (outcome.extra or {}).items():
            body.setdefault(key, value)
        return JSONResponse(body)
    status = STATUS.get(outcome.code, 502 if outcome.result is OutcomeKind.FAILED else 409)
    body = {"problem": outcome.message, "result": str(outcome.result), "backup": outcome.backup}
    if outcome.fix:
        body["fix"] = outcome.fix
    if outcome.field:
        body["field"] = outcome.field
    if outcome.code is not None:
        body["code"] = str(outcome.code)
    return JSONResponse(body, status_code=status)


def issue_json(issue) -> dict:
    """§3.5 {file, line, field, problem, fix} plus the one rendered text."""
    return {"file": issue.source.file, "line": issue.source.line, "field": issue.control, "problem": issue.problem,
            "fix": issue.fix, "severity": str(issue.severity), "text": issue.message()}


def issues_response(issues, extra: dict | None = None) -> JSONResponse:
    ordered = [issue_json(i) for i in in_line_order(issues)]
    first = ordered[0] if ordered else {"problem": "invalid", "fix": None, "file": None, "line": None, "field": None}
    body = {"problem": first["problem"], "fix": first["fix"], "file": first["file"], "line": first["line"],
            "field": first["field"], "text": first.get("text"), "valid": False, "issues": ordered, **(extra or {})}
    return JSONResponse(body, status_code=400)


def answer(value) -> JSONResponse:
    """A use case's answer: a WriteOutcome, a tweak answer (Saved, Stale, Invalid) or plain JSON."""
    if isinstance(value, WriteOutcome):
        return outcome_response(value)
    if value is None:
        return JSONResponse({"problem": "the host is not ready for that yet; try again in a moment"}, status_code=409)
    if hasattr(value, "issues") and not isinstance(value, dict):          # tweaks.Invalid
        return issues_response(value.issues)
    if type(value).__name__ == "Stale":                                    # tweaks.Stale
        return JSONResponse({"problem": getattr(value, "message", STALE) or STALE}, status_code=409)
    if hasattr(value, "to_json"):
        return JSONResponse(value.to_json())
    return JSONResponse(value)


def lab_router(services: LabServices) -> APIRouter:
    s = services
    router = APIRouter()

    async def handle(request: Request | None, work, blocking: bool = False):
        """Reads the body, runs work(body) (in a worker thread when it blocks) and maps refusals."""
        try:
            body = await _body(request) if request is not None else {}
            if blocking:
                return await asyncio.to_thread(work, body)
            return work(body)
        except Problem as error:
            return JSONResponse(error.body, status_code=error.status)
        except DomainInvariantError as error:
            return JSONResponse({"problem": f"{error.problem}{error.joiner}{error.fix}", "fix": error.fix,
                                 "field": error.field}, status_code=400)

    # --- the lab panel's state (§3.5) ------------------------------------------------------------------
    @router.get("/api/lab")
    async def lab_state():
        return JSONResponse(s.session.state().to_json())

    @router.post("/api/lab/validate")
    async def validate(request: Request):
        def work(data):
            allowed = ["text", "file"]
            if "path" in data and "text" not in data:
                raise _bad("send the layout text, not a path: the service never reads paths you name", allowed)
            text = data.get("text")
            if not isinstance(text, str):
                raise _bad("send the layout text as 'text'", allowed)
            file = str(data.get("file") or "layout.yaml").replace("\\", "/").rsplit("/", 1)[-1] or "layout.yaml"
            result = s.validate(text, file)
            errors = [i for i in result.issues if i.is_error]
            warnings = [issue_json(i) for i in result.warnings]
            if errors or not result.valid:
                return issues_response(errors or result.issues, {"warnings": warnings})
            return JSONResponse({"valid": True, "issues": [], "warnings": warnings, "summary": result.summary()})
        return await handle(request, work)

    @router.post("/api/lab/activate")
    async def activate(request: Request):
        return await handle(request, lambda d: answer(s.session.activate(_text(d, "layout", ["layout"]))))

    @router.post("/api/lab/leave")
    async def leave(request: Request):
        return await handle(request, lambda d: answer(s.session.leave()), blocking=True)

    @router.post("/api/lab/tweak")
    async def tweak(request: Request):
        def work(data):
            allowed = ["layout", "field", "value"]
            field = _text(data, "field", allowed)
            value = data.get("value")
            if value is None or isinstance(value, (dict, list)):
                raise _bad("send the new 'value'", allowed)
            result = s.session.tweak(field, value, _text(data, "layout", allowed, required=False))
            if type(result).__name__ == "Saved":
                path = field if field.startswith("lab.") else f"lab.{field}"
                return JSONResponse({"result": "saved", "backup": None, "hash": str(result.hash),
                                     "message": f"saved {path} = {value}; the layout reloads"})
            return answer(result)
        return await handle(request, work)

    @router.post("/api/lab/recovery/dismiss")
    async def dismiss_recovery(request: Request):
        return await handle(request, lambda d: answer(s.session.dismiss_recovery()), blocking=True)

    # --- harmony (§3.5, §2.7 q7) -----------------------------------------------------------------------
    @router.get("/api/lab/harmony")
    async def harmony():
        return JSONResponse({"kind": "harmony", **s.tracker.state().to_json()})

    @router.get("/api/lab/harmony/inputs")
    async def harmony_inputs():
        return JSONResponse(s.tracker.inputs())

    @router.post("/api/lab/harmony/inputs")
    async def select_inputs(request: Request):
        def work(data):
            ports = data.get("inputs")
            if not isinstance(ports, list) or not all(isinstance(p, str) for p in ports):
                raise _bad("send 'inputs' as a list of MIDI input port names ([] follows the APC64 only)",
                           ["inputs"])
            return JSONResponse(s.tracker.select_inputs(ports))
        return await handle(request, work)

    # --- project memory (pi5) --------------------------------------------------------------------------
    @router.get("/api/lab/slots/{n}")
    async def slot(n: str):
        return await handle(None, lambda d: answer(s.projects.slot(n)), blocking=True)

    @router.post("/api/lab/push")
    async def push(request: Request):
        def work(data):
            allowed = ["entry", "slot", "offset"]
            entry = _text(data, "entry", allowed)
            if data.get("slot") is None:
                raise _bad("send the 'slot' (1–24)", allowed)
            offset = data.get("offset")
            if offset is not None and (isinstance(offset, bool) or not isinstance(offset, int)):
                raise _bad("'offset' is a whole number of semitones", allowed)
            return answer(s.projects.push(entry, data["slot"], offset))
        return await handle(request, work, blocking=True)

    @router.post("/api/lab/preview")
    async def preview(request: Request):
        return await handle(request, lambda d: answer(s.projects.preview(_text(d, "entry", ["entry"]))))

    @router.post("/api/lab/backup")
    async def backup(request: Request):
        def work(data):
            if data.get("all") is True:
                return answer(s.projects.backup_all())
            if data.get("slot") is None:
                raise _bad("send {all: true}, or the 'slot' (0–24 or 'globals')", ["all", "slot"])
            return answer(s.projects.backup(data["slot"]))
        return await handle(request, work, blocking=True)

    @router.get("/api/lab/backups")
    async def backups():
        return await handle(None, lambda d: JSONResponse(s.projects.backups()), blocking=True)

    @router.post("/api/lab/restore")
    async def restore(request: Request):
        def work(data):
            allowed = ["backup", "slot"]
            backup_id = _text(data, "backup", allowed)
            if data.get("slot") is None:
                raise _bad("send the 'slot' to restore to (1–24, 0 for a slot-0 backup, or 'globals')", allowed)
            return answer(s.projects.restore(backup_id, data["slot"]))
        return await handle(request, work, blocking=True)

    @router.post("/api/lab/import")
    async def import_preset(request: Request):
        def work(data):
            allowed = ["name", "data_base64", "file"]
            encoded = data.get("data_base64")
            if not isinstance(encoded, str) or not encoded.strip():
                raise _bad("send the .APC64 file as 'data_base64'", allowed)
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                raise _bad("'data_base64' is not base64", allowed) from None
            return answer(s.projects.import_preset(_text(data, "name", allowed, required=False), raw,
                                                   _text(data, "file", allowed, required=False)))
        return await handle(request, work, blocking=True)

    @router.get("/api/lab/library")
    async def library():
        return await handle(None, lambda d: JSONResponse(s.projects.library()), blocking=True)

    @router.post("/api/lab/library/capture")
    async def capture(request: Request):
        def work(data):
            allowed = ["slot", "name"]
            if data.get("slot") is None:
                raise _bad("send the 'slot' (0–24)", allowed)
            return answer(s.projects.capture(data["slot"], _text(data, "name", allowed)))
        return await handle(request, work, blocking=True)

    @router.post("/api/lab/bulk-edit")
    async def bulk_edit(request: Request):
        def work(data):
            allowed = ["target", "edits"]
            target = _text(data, "target", allowed)
            edits = data.get("edits", data.get("edit"))
            if isinstance(edits, str):
                edits = [edits]
            if not isinstance(edits, list) or not edits or not all(isinstance(e, str) for e in edits):
                raise _bad("send 'edits' as a list of edits, e.g. [\"all pads channel 3\"]", allowed)
            return answer(s.projects.bulk_edit(target, edits))
        return await handle(request, work, blocking=True)

    # --- global settings (pi6) -------------------------------------------------------------------------
    @router.get("/api/lab/globals")
    async def globals_read():
        return await handle(None, lambda d: answer(s.globals.read()), blocking=True)

    @router.post("/api/lab/globals")
    async def globals_change(request: Request):
        def work(data):
            allowed = ["changes", "confirm"]
            changes = data.get("changes")
            if not isinstance(changes, dict) or not changes:
                raise _bad("send 'changes' as {field: value}, e.g. {\"led_level\": 100}", allowed)
            confirm = data.get("confirm", False)
            if not isinstance(confirm, bool):
                raise _bad("'confirm' is true or false", allowed)
            return answer(s.globals.change(changes, confirm))
        return await handle(request, work, blocking=True)

    return router
