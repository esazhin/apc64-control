"""The `apc64` command (contract q12, s2, s10, s29, s31; docs/api.md "Command line").

Everything the page can do, over the same HTTP API (inv22, a21): take, decline, release, ports, layouts,
validate PATH, load NAME, page N, bank N, shift on|off, state, watch, versions NAME, restore NAME VERSION,
card CONTROL, overview, activity, device-log, tap CONTROL, move CONTROL VALUE, turn STEPS, tweak, learn,
calibrate. `--json` prints the API's JSON instead of text.

Exit codes: 0 done; 1 refused or invalid (the service's problem, or the layout's issues, are printed);
2 the service is not running ("service not running on port 5058"). validate still works then: it compiles
the file here, structure only, and says 'ports not checked' (d125, s2.c4).

Contract 2 (T41): module subcommands. A CLI module has a `name`, `register(subparsers, common)` and
`run(args, transport, out, err, as_json) → exit code`; it is mounted as `apc64 <name> …` and talks to the service
over the same transport. main() takes them as `modules`; without that argument it mounts the installed ones (the
'apc64.cli' entry points, so the `apc64` script finds the layout lab's `apc64 lab …`). With no module, the
command is contract 1's, unchanged.
"""
import argparse
import json
import logging
import os
import socket as _socket
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

DEFAULT_PORT = 5058
EXIT_OK, EXIT_REFUSED, EXIT_DOWN = 0, 1, 2
CLI_ENTRY_POINTS = "apc64.cli"
log = logging.getLogger(__name__)


class ServiceDown(Exception):
    """Nothing answers on the service's port."""


class HttpTransport:
    """JSON over HTTP to the running service (stdlib only). No Origin header: the guard treats it as local."""

    def __init__(self, base: str, timeout: float = 15.0):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, body=None) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, _json(response.read())
        except urllib.error.HTTPError as error:
            return error.code, _json(error.read())
        except urllib.error.URLError as error:
            if isinstance(error.reason, (ConnectionRefusedError, _socket.gaierror, OSError)):
                raise ServiceDown(str(error.reason)) from None
            raise
        except (ConnectionRefusedError, ConnectionResetError):
            raise ServiceDown("connection refused") from None


def _json(raw: bytes):
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return {"problem": raw.decode(errors="replace")[:200]}


def connect_play(url: str):
    """The /ws/play socket: an iterator of JSON messages (websockets' sync client)."""
    from websockets.sync.client import connect
    try:
        connection = connect(url, open_timeout=10)
    except (ConnectionRefusedError, OSError) as error:
        raise ServiceDown(str(error)) from None

    class _Messages:
        def __iter__(self):
            try:
                for text in connection:
                    yield json.loads(text)
            except Exception as error:   # the service went away mid-stream
                if type(error).__name__.startswith("ConnectionClosed"):
                    return
                raise
            finally:
                connection.close()

        def close(self):
            connection.close()

    return _Messages()


def default_base(environ) -> str:
    if environ.get("APC64_URL"):
        return environ["APC64_URL"]
    port = DEFAULT_PORT
    try:
        from ..config import Config
        port = Config.load(environ).http_port
    except Exception:
        port = int(environ.get("APC64_HTTP_PORT", DEFAULT_PORT)) if str(
            environ.get("APC64_HTTP_PORT", "")).isdigit() else DEFAULT_PORT
    return f"http://127.0.0.1:{port}"


def installed_modules() -> tuple:
    """The CLI modules installed as 'apc64.cli' entry points (a factory or the module object each)."""
    from importlib.metadata import entry_points
    found = []
    for point in entry_points(group=CLI_ENTRY_POINTS):
        try:
            loaded = point.load()
            found.append(loaded() if callable(loaded) and not hasattr(loaded, "register") else loaded)
        except Exception as error:   # a broken module never stops contract 1's commands
            log.warning("apc64: the %s command could not load: %s", point.name, error)
    return tuple(found)


# --- the parser -------------------------------------------------------------------------------------------
def parser(modules=()) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="apc64", description="Drive the APC64 host service (see docs/api.md).")
    p.add_argument("--url", help="service address (default http://127.0.0.1:5058, or APC64_URL)")
    p.add_argument("--json", action="store_true", help="print the API's JSON")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")
    common = argparse.ArgumentParser(add_help=False)      # so `apc64 watch --json` works as well
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the API's JSON")

    def add(name, help_text, *args):
        command = sub.add_parser(name, help=help_text, description=help_text, parents=[common])
        for arg, kwargs in args:
            command.add_argument(*([arg] if isinstance(arg, str) else arg), **kwargs)
        return command

    add("take", "take the APC64 (counts as the user's yes: the agent acts on their instruction)")
    add("decline", "answer No to the 'Take control of APC64?' question")
    add("release", "release the APC64: LEDs and OLED cleared, DAW mode off, port free for Bitwig")
    add("ports", "list MIDI ports by name, and declared devices whose port is missing")
    add("layouts", "list layouts: file, name, valid, pages, banks")
    add("validate", "validate a layout file (any path); never applies it",
        ("path", {"help": "the YAML file"}))
    add("load", "make a layout live (file name or display name)", ("name", {}))
    add("page", "select page 1–8", ("n", {"type": int}))
    add("bank", "select strip bank 1–6", ("n", {"type": int}))
    add("shift", "hold or release Shift in the page", ("held", {"choices": ["on", "off"]}))
    add("state", "the current state: unit, layout, page, bank, Shift, OLED, routing, errors")
    add("watch", "print what is played and pressed, from now on, until interrupted")
    add("versions", "list a layout's live versions, newest first", ("name", {}))
    add("restore", "restore a version (it goes live like any write)", ("name", {}), ("version", {}))
    add("card", "everything about one control: both layers, mode, ports, elsewhere", ("control", {}))
    add("overview", "every page and bank of the live layout")
    add("activity", "the latest actions, newest first", (("--limit", "-n"), {"type": int, "default": 20}))
    add("device-log", "frames sent to the APC64 (refused ones are hazards)",
        (("--limit", "-n"), {"type": int, "default": 50}))
    add("tap", "press and release a control, as a click on the replica", ("control", {}),
        ("--velocity", {"type": int, "default": 127}))
    add("move", "move a strip to 0–16383", ("control", {}), ("value", {"type": int}))
    add("turn", "turn the encoder by steps (negative: counter-clockwise)", ("steps", {"type": int}))
    add("tweak", "change one control on the current page (or bank) and layer, saved to the layout file",
        ("control", {}), ("field", {"choices": ["assignment", "label", "colour", "mode"]}),
        ("value", {"nargs": "?", "default": None}), ("--layer", {"choices": ["base", "shift"]}),
        ("--page", {"type": int}), ("--bank", {"type": int}))
    add("learn", "learn: touch (select by touching), midi PORT (bind the next message), off",
        ("mode", {"choices": ["touch", "midi", "off"]}), ("port", {"nargs": "?"}), ("--control", {}))
    add("calibrate", "Note-view pad calibration: start (then press bottom-left, top-right) or cancel",
        ("step", {"choices": ["start", "cancel"]}))
    for module in modules:                      # contract 2: module subcommands, after contract 1's
        module.register(sub, common)
    return p


# --- running -----------------------------------------------------------------------------------------------
class Cli:
    def __init__(self, transport, out, err, as_json: bool, base: str, socket_factory, compile_offline):
        self.t, self.out, self.err, self.as_json, self.base = transport, out, err, as_json, base
        self.socket_factory, self.compile_offline = socket_factory, compile_offline

    def say(self, *lines) -> None:
        for line in lines:
            print(line, file=self.out)

    def complain(self, *lines) -> None:
        for line in lines:
            print(line, file=self.err)

    def call(self, method, path, body=None):
        """(ok, data); a refusal is printed and gives ok False."""
        status, data = self.t.request(method, path, body)
        if 200 <= status < 300:
            return True, data
        if self.as_json:
            self.say(json.dumps(data, ensure_ascii=False, indent=2))
            return False, data
        data = data if isinstance(data, dict) else {"problem": str(data)}
        self.complain(data.get("problem") or f"refused ({status})")
        for issue in data.get("issues") or ():
            self.complain(issue.get("text", issue))
        if data.get("allowed"):
            self.complain("allowed: " + ", ".join(str(a) for a in data["allowed"]))
        return False, data

    def show(self, data, lines) -> int:
        if self.as_json:
            self.say(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            self.say(*lines(data))
        return EXIT_OK

    def simple(self, method, path, body, lines) -> int:
        ok, data = self.call(method, path, body)
        return self.show(data, lines) if ok else EXIT_REFUSED

    # --- commands --------------------------------------------------------------------------------------
    def take(self, a):
        return self.simple("POST", "/api/unit/take", {"source": "agent"}, lambda d: [d["status_text"]])

    def decline(self, a):
        return self.simple("POST", "/api/unit/decline", {}, lambda d: [d.get("text", "Not held")])

    def release(self, a):
        return self.simple("POST", "/api/unit/release", {}, lambda d: [d["text"]])

    def ports(self, a):
        def lines(ports):
            for p in ports:
                if p["present"]:
                    yield f"{p['name']}  ({p['direction']})"
                else:
                    yield f"{p['name']}  (missing: declared by device {p['device']})"
        return self.simple("GET", "/api/ports", None, lambda d: list(lines(d)) or ["no MIDI ports"])

    def layouts(self, a):
        def line(x):
            status = (f"{x['pages']} page{'s' * (x['pages'] != 1)}, {x['banks']} bank{'s' * (x['banks'] != 1)}"
                      if x["valid"] else f"invalid: {x['errors']} error{'s' * (x['errors'] != 1)}")
            deleted = ", file deleted, still active" if x.get("deleted") else ""
            return f"{x['file']}  {x['name']}  {status}{deleted}"
        return self.simple("GET", "/api/layouts", None, lambda d: [line(x) for x in d] or ["no layouts"])

    def validate(self, a):
        path = Path(a.path).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            self.complain(f"cannot read {a.path}: {error.strerror or error}")
            return EXIT_REFUSED
        try:
            ok, data = self.call("POST", "/api/validate", {"text": text, "file": path.name})
            if not ok:
                return EXIT_REFUSED
        except ServiceDown:
            data = self.compile_offline(text, path.name)
            data["offline"] = True
        if self.as_json:
            self.say(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            summary = data["summary"]
            if data.get("offline") and "ports not checked" not in summary:
                summary += " (ports not checked)"
            self.say(summary, *[e["text"] for e in data["errors"]], *[f"warning: {w['text']}" for w in data["warnings"]])
        return EXIT_OK if data["valid"] else EXIT_REFUSED

    @staticmethod
    def _nav_lines(d):
        page, bank = d.get("page"), d.get("bank")
        yield (f"{d.get('layout_name') or 'no layout'}: "
               f"page {page['n'] if page else '-'} {page['display'] if page else ''}".rstrip()
               + f", bank {bank['n'] if bank else '-'} {bank['display'] if bank else ''}".rstrip()
               + (", Shift held" if d.get("shift") else ""))

    def load(self, a):
        return self.simple("POST", "/api/layout", {"name": a.name}, lambda d: list(self._nav_lines(d)))

    def page(self, a):
        return self.simple("POST", "/api/page", {"n": a.n}, lambda d: list(self._nav_lines(d)))

    def bank(self, a):
        return self.simple("POST", "/api/bank", {"n": a.n}, lambda d: list(self._nav_lines(d)))

    def shift(self, a):
        return self.simple("POST", "/api/shift", {"held": a.held == "on"}, lambda d: list(self._nav_lines(d)))

    def state(self, a):
        def lines(d):
            unit = d["unit"]
            yield f"unit: {unit['text']}" + ("" if unit["held"] else " (Not held)") + f", view {unit['view']}"
            for note in unit["warnings"] + unit["notices"]:
                yield f"  {note}"
            yield from self._nav_lines(d)
            if d.get("file_deleted"):
                yield "  file deleted, still active"
            yield f"oled: {d['oled'][0]!r} {d['oled'][1]!r}"
            routing = d["routing"]
            yield ("routing: " + ", ".join(f"{k} → {v}" for k, v in (("notes", routing["notes"]),
                                                                       ("custom", routing["custom"])) if v)
                   if routing["notes"] or routing["custom"] else f"routing: {routing['status']}")
            if d["learn"]["mode"] != "off":
                yield f"learn: {d['learn']['mode']}" + (f", selected {d['learn']['selected']}"
                                                         if d["learn"]["selected"] else "")
            for warning in d["warnings"]:
                yield f"warning: {warning}"
            for error in d["errors"]:
                yield f"error: {error['text']}"
        return self.simple("GET", "/api/state", None, lambda d: list(lines(d)))

    def watch(self, a):
        url = "ws" + self.base[4:] + "/ws/play" if self.base.startswith("http") else self.base + "/ws/play"
        stream = self.socket_factory(url)
        try:
            for message in stream:
                if message.get("type") == "closed":
                    self.complain(f"stream closed: {message.get('reason')}")
                    return EXIT_REFUSED
                if self.as_json:
                    self.say(json.dumps(message.get("data"), ensure_ascii=False))
                else:
                    self.say(event_line(message.get("data") or {}))
                    _flush(self.out)
        except KeyboardInterrupt:
            return EXIT_OK
        finally:
            closer = getattr(stream, "close", None)
            if closer:
                closer()
        return EXIT_OK

    def versions(self, a):
        return self.simple("GET", f"/api/layouts/{quote(a.name, safe='')}/versions", None,
                           lambda d: [f"{v['id']}  {v['at']}" for v in d] or [f"no versions of {a.name}"])

    def restore(self, a):
        return self.simple("POST", f"/api/layouts/{quote(a.name, safe='')}/restore", {"id": a.version},
                           lambda d: [f"restored {d['restored']} ({d['at']}); it goes live like any write"])

    def card(self, a):
        def lines(d):
            yield d["display"] + ("" if d["role"] == "bindable" else f" ({d['role'].replace('_', ' ')})")
            yield from d["lines"]
            if d.get("feedback"):
                yield f"feedback: {d['feedback']}"
        return self.simple("GET", f"/api/controls/{quote(a.control, safe='')}", None, lambda d: list(lines(d)))

    def overview(self, a):
        def lines(d):
            yield d["layout_name"] or "no layout"
            for p in d["pages"]:
                if p["defined"]:
                    yield f"page {p['n']} {p['name'] or ''}: {len(p['base'])} bound, {len(p['shift'])} on Shift"
            for b in d["banks"]:
                if b["defined"]:
                    labels = ", ".join(f"{k}: {v['label']}" for k, v in b["base"].items())
                    yield f"bank {b['n']} {b['name'] or ''}: {labels}"
        return self.simple("GET", "/api/overview", None, lambda d: list(lines(d)))

    def activity(self, a):
        return self.simple("GET", f"/api/activity?limit={a.limit}", None,
                           lambda d: [f"{_clock(e['at'])}  {e['text']}" for e in d] or ["nothing yet"])

    def device_log(self, a):
        return self.simple("GET", f"/api/device-log?limit={a.limit}", None,
                           lambda d: [f"{_clock(e['at'])}  {'HAZARD ' if e['hazard'] else ''}{e['text']}  {e['hex']}"
                                      for e in d] or ["nothing sent"])

    def tap(self, a):
        name = quote(a.control, safe="")
        ok, _ = self.call("POST", f"/api/control/{name}/press", {"value": a.velocity})
        if not ok:
            return EXIT_REFUSED
        return self.simple("POST", f"/api/control/{name}/release", {}, lambda d: [f"{a.control}: pressed and released"])

    def move(self, a):
        return self.simple("POST", f"/api/control/{quote(a.control, safe='')}/move", {"value": a.value},
                           lambda d: [f"{a.control}: {a.value}"])

    def turn(self, a):
        return self.simple("POST", "/api/control/encoder/move", {"value": a.steps}, lambda d: [f"encoder: {a.steps:+d}"])

    def tweak(self, a):
        ok, card = self.call("GET", f"/api/controls/{quote(a.control, safe='')}")
        if not ok:
            return EXIT_REFUSED
        body = {"control": a.control, "field": a.field, "value": a.value, "base_hash": card.get("base_hash"),
                "layer": a.layer or card.get("layer")}
        if a.page is not None:
            body["page"] = a.page
        if a.bank is not None:
            body["bank"] = a.bank
        return self.simple("POST", "/api/tweak", body, lambda d: [f"saved: {a.control} {a.field}"])

    def learn(self, a):
        body = {"mode": a.mode}
        if a.port:
            body["port"] = a.port
        if a.control:
            body["control"] = a.control
        return self.simple("POST", "/api/learn", body, lambda d: [
            f"learn {d.get('mode', a.mode)}" + (f" on {d['port']}" if d.get("port") else "")
            + (f", selected {d['selected']}" if d.get("selected") else "")])

    def calibrate(self, a):
        return self.simple("POST", "/api/calibrate", {"step": a.step},
                           lambda d: [d.get("text") or d.get("step", a.step)] + ([d["problem"]] if d.get("problem") else []))


def event_line(e: dict) -> str:
    what = e.get("control") or (f"note {e['note']}" if e.get("note") is not None else e.get("kind"))
    parts = [_clock(e.get("at")), e.get("source") or "", what or "", e.get("kind") or ""]
    if e.get("velocity") is not None:
        parts.append(f"vel {e['velocity']}")
    if e.get("aftertouch") is not None:
        parts.append(f"at {e['aftertouch']}")
    if e.get("value") is not None:
        parts.append(f"value {e['value']}")
    line = " ".join(p for p in parts if p)
    if e.get("sent"):
        line += " → " + "; ".join(e["sent"])
    if e.get("reason"):
        line += f" ({e['reason']})"
    return line


def _clock(at) -> str:
    if at is None:
        return "--:--:--"
    moment = datetime.fromtimestamp(at)
    return moment.strftime("%H:%M:%S.") + f"{moment.microsecond // 1000:03d}"


def _flush(stream) -> None:
    flush = getattr(stream, "flush", None)
    if flush:
        flush()


def compile_offline(text: str, file: str) -> dict:
    """Structure-only validation without the service (s29): no port catalog, so 'ports not checked'."""
    from ..notation.compiler import compile_text
    from ..domain.issues import in_line_order
    from .view_model import issue_json
    from dataclasses import asdict
    result = compile_text(text, file, None)
    return {"valid": result.valid, "summary": result.summary(),
            "errors": [issue_json(i) for i in in_line_order(result.issues)],
            "warnings": [issue_json(i) for i in result.warnings],
            "counts": asdict(result.counts) if result.counts else None, "ports_checked": False}


def main(argv=None, *, transport=None, socket_factory=connect_play, environ=None, out=None, err=None,
         compile=compile_offline, modules=None) -> int:
    environ = os.environ if environ is None else environ
    out = out or sys.stdout
    err = err or sys.stderr
    modules = installed_modules() if modules is None else tuple(modules)
    args = parser(modules).parse_args(argv)
    base = (args.url or default_base(environ)).rstrip("/")
    cli = Cli(transport or HttpTransport(base), out, err, args.json, base, socket_factory, compile)
    module = next((m for m in modules if m.name == args.command), None)
    if module is not None:
        handler = lambda a: module.run(a, cli.t, out, err, a.json)   # noqa: E731 (the module's own command)
    else:
        handler = getattr(cli, args.command.replace("-", "_"))
    try:
        return handler(args)
    except ServiceDown:
        port = urlsplit(base).port or DEFAULT_PORT
        print(f"service not running on port {port}", file=err)
        return EXIT_DOWN


if __name__ == "__main__":
    sys.exit(main())
