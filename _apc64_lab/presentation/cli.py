"""The `apc64 lab …` commands (contract s28 supplier, s29 consumer; inv9; docs/lab-api.md).

Each command calls one /api/lab route, the same one the panel uses, and prints the service's own message: the
result's `message` on success, or its `problem` (and its `fix`, when the problem does not already say it) on
stderr with exit 1. `--json` prints the API's JSON instead. When the service is not running the host command
says 'service not running on port 5058' and exits 2; `apc64 lab validate` then compiles the file here, structure
only, with the built-in and plugin generators, and says '(ports not checked)'.

The host's `apc64` command mounts this as its `lab` subcommand (T41): `register(subparsers, common)` adds the
parser, `run(args, transport, out, err, as_json)` runs one command over the host's HTTP transport.
"""
import base64
import json
from pathlib import Path
from typing import Callable
from urllib.parse import quote

EXIT_OK, EXIT_REFUSED = 0, 1


def _value(text: str):
    """A command-line value as the API takes it: a whole number when it is one, the text otherwise."""
    stripped = text.strip()
    return int(stripped) if stripped.lstrip("-").isdigit() else stripped


def param_text(p: dict) -> str:
    """'base 0–127 (default 36)', 'scale: major, dorian, … (default major)', 'root a note name (default: the root)'."""
    if p.get("kind") == "notes":
        return (f"{p['name']}: {', '.join(p['choices'])}, or a list of {p['min']}–{p['max']} notes "
                f"(default {p['default']})")
    if p.get("choices"):
        return f"{p['name']}: {', '.join(p['choices'])} (default {p['default']})"
    if p.get("kind") == "pitch-class":
        return f"{p['name']} a note name such as D or F# (default: " + (p["default"] if p.get("default") is not None
                                                                     else "the layout's root") + ")"
    return f"{p['name']} {p['min']}–{p['max']} (default {p['default']})"


def unit_hint(active: dict) -> str:
    """What the encoder and Tempo do on the active layout: its own steps (the guitar's Fret and Page), else the
    interval."""
    window = active.get("window") or {}
    if window.get("steps") and "octave" not in (active.get("counts") or {}):
        return f"encoder: one {str(window.get('step', '')).lower()} · Tempo: {' ↔ '.join(window['steps'])}"
    return "encoder: shift · Tempo: interval"


def _pairs(items) -> dict:
    changes = {}
    for item in items:
        field, sep, value = item.partition("=")
        if not sep or not field.strip():
            raise ValueError(f"'{item}' is not FIELD=VALUE; write e.g. led_level=100")
        changes[field.strip()] = _value(value)
    return changes


class LabCli:
    """The `lab` subcommand of `apc64`."""
    name = "lab"
    help = "the layout lab: generated layouts, harmony, project memory and global settings (docs/lab-api.md)"

    def __init__(self, compile_offline: Callable[[str, str], dict] | None = None,
                 pattern_offline: Callable[[str, str], dict] | None = None):
        self.compile_offline = compile_offline
        self.pattern_offline = pattern_offline

    # --- the parser ------------------------------------------------------------------------------------
    def register(self, sub, common) -> None:
        lab = sub.add_parser(self.name, help=self.help, description=self.help, parents=[common])
        commands = lab.add_subparsers(dest="lab_command", required=True, metavar="LAB_COMMAND")

        def add(name, help_text, *args):
            command = commands.add_parser(name, help=help_text, description=help_text, parents=[common])
            for arg, kwargs in args:
                command.add_argument(*([arg] if isinstance(arg, str) else arg), **kwargs)
            return command

        add("list", "generators and colour schemes with their parameters, and the active generated layout")
        add("validate", "validate a layout file with a lab section (any path); never applies it",
            ("path", {"help": "the YAML file"}))
        add("activate", "make a layout live; a generated one is written to slot 0 after one session backup",
            ("name", {"help": "layout file name or display name"}))
        add("leave", "leave the generated layout or preview: slot 0 is restored from the session backup")
        add("key", "the key of the active generated layout for the session (its scale overlay; not the file): show it, "
            "or TONIC [SCALE] (C major, F# dorian), none (chromatic), layout (the file's again)",
            ("words", {"nargs": "*", "metavar": "WORD"}))
        add("tweak", "change one lab field of the active (or named) generated layout, saved to its file",
            ("field", {"help": "base, scheme, a generator parameter, or colours.C"}), ("value", {}),
            ("--layout", {"help": "the generated layout (default: the active one)"}))
        add("push", "store a generated layout (where it sits now) or a library entry in slot 1–24",
            ("entry", {}), ("slot", {}), ("--offset", {"type": int, "help": "semitones instead of the window"}))
        add("preview", "play a captured or imported library entry live in slot 0 (leave restores slot 0)",
            ("entry", {}))
        backup = add("backup", "back up slots 0–24 and the global settings (default), one slot, or the globals")
        which = backup.add_mutually_exclusive_group()
        which.add_argument("--all", action="store_true", help="slots 0–24 and the global settings as one set")
        which.add_argument("--slot", help="one slot 0–24")
        which.add_argument("--globals", action="store_true", help="the global settings block")
        add("backups", "list the backups (newest first) and the backup sets",
            ("--slot", {"help": "only this slot (0–24) or 'globals'"}))
        add("restore", "restore one backup to one slot (the slot's current content is backed up first)",
            ("backup", {}), ("slot", {"help": "1–24, 0 for a slot-0 backup, or globals"}))
        add("import", "import an Akai Project Editor .APC64 file into the library; nothing is written to the unit",
            ("name", {"help": "the library name"}), ("file", {"help": "the .APC64 file"}))
        add("library", "the library: generated layouts, captured projects and imported presets")
        add("capture", "save what a slot holds now to the library under a new name", ("slot", {}), ("name", {}))
        add("bulk-edit", "edit a stored project (slot 1–24) or a library entry, e.g. 'all pads channel 3'",
            ("target", {}), ("edits", {"nargs": "+", "help": "one or more edits"}))
        add("globals", "read the global settings, or change them: FIELD=VALUE … (device mode and sync need --confirm)",
            ("changes", {"nargs": "*", "metavar": "FIELD=VALUE"}), ("--confirm", {"action": "store_true"}))
        add("harmony", "what is held now: chord, triads, hints, neighbours, trail, circle of fifths")
        add("trail", "the chord trail (the last 8 chords held); 'clear' empties it",
            ("action", {"nargs": "?", "choices": ["clear"], "help": "clear: empty the trail"}))
        add("inputs", "the MIDI inputs the harmony views follow besides the APC64; give ports to set them",
            ("ports", {"nargs": "*", "metavar": "PORT"}), ("--none", {"action": "store_true",
                                                                        "help": "follow the APC64 only"}))
        add("slot", "read one slot 0–24 from the unit: its pads and strips", ("n", {}))
        add("dismiss-recovery", "dismiss a pending slot-0 recovery (its backup stays listed)")
        add("performer", "the performer on the active generated layout: show it, or: on | off | stop | pattern NAME | "
            "latch on|off | play all|pressed|pattern | tempo BPM | tempo clock PORT|auto | type NAME|off | slot N | "
            "revert NAME (drop its unsaved edit) | new (the session's unsaved new pattern again)",
            ("words", {"nargs": "*", "metavar": "WORD"}))
        add("patterns", "the performer patterns in patterns/ (valid and invalid)")
        add("pattern", "show one pattern as its grid", ("name", {"help": "file name (travis) or name"}))
        add("validate-pattern", "validate a pattern file (any path); never applies it", ("path", {"help": "the YAML file"}))
        add("write-pattern", "write a pattern file (any path) into patterns/, validated first; the text it replaces "
            "is kept as a version", ("path", {"help": "the YAML or JSON file"}),
            ("--id", {"help": "the pattern's file name in patterns/ (default: the file's own name)"}),
            ("--new", {"action": "store_true", "help": "refuse to replace an existing pattern"}))
        add("delete-pattern", "delete a pattern from patterns/ (kept as a version; refused while a layout uses it)",
            ("name", {"help": "file name (travis) or name"}))
        add("pattern-versions", "the versions kept of a pattern (each text a write replaced), newest first",
            ("name", {"help": "file name (travis)"}))
        add("restore-pattern", "write a kept version of a pattern back", ("name", {"help": "file name (travis)"}),
            ("version", {"help": "as pattern-versions lists it (a unique start is enough)"}))

    # --- running ---------------------------------------------------------------------------------------
    def run(self, args, transport, out, err, as_json: bool) -> int:
        return _Run(self, args, transport, out, err, as_json).go()


class _Run:
    def __init__(self, cli: LabCli, args, transport, out, err, as_json):
        self.cli, self.a, self.t, self.out, self.err, self.as_json = cli, args, transport, out, err, as_json

    def say(self, *lines):
        for line in lines:
            print(line, file=self.out)

    def complain(self, *lines):
        for line in lines:
            print(line, file=self.err)

    def go(self) -> int:
        handler = getattr(self, "c_" + self.a.lab_command.replace("-", "_"))
        try:
            return handler()
        except ValueError as error:
            self.complain(str(error))
            return EXIT_REFUSED

    def call(self, method, path, body=None):
        status, data = self.t.request(method, path, body)
        if 200 <= status < 300:
            return True, data
        if self.as_json:
            self.say(json.dumps(data, ensure_ascii=False, indent=2))
            return False, data
        data = data if isinstance(data, dict) else {"problem": str(data)}
        issues = data.get("issues") or []
        if issues:
            self.complain(*[issue.get("text") or issue.get("problem") for issue in issues])
        else:
            problem = data.get("problem") or f"refused ({status})"
            self.complain(problem)
            fix = data.get("fix")
            if fix and fix not in problem:
                self.complain(fix)
        if data.get("allowed"):
            self.complain("allowed: " + ", ".join(str(a) for a in data["allowed"]))
        return False, data

    def simple(self, method, path, body=None, lines=None) -> int:
        ok, data = self.call(method, path, body)
        if not ok:
            return EXIT_REFUSED
        if self.as_json:
            self.say(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            self.say(*(lines(data) if lines else [data.get("message", "")]))
        return EXIT_OK

    # --- commands --------------------------------------------------------------------------------------
    def c_list(self):
        def lines(d):
            yield "generators:"
            for g in d["generators"]:
                if g.get("broken"):
                    yield f"  {g['name']}  broken: {g['error']}  ({g['file']})"
                    continue
                yield f"  {g['name']}  {', '.join(param_text(p) for p in g.get('params', []))}"
            yield "colour schemes: " + ", ".join(
                s["name"] + (f" (broken: {s['error']})" if s.get("broken") else "") for s in d["schemes"])
            for s in d["schemes"]:
                if s.get("params") and not s.get("broken"):
                    yield f"  {s['name']}  {', '.join(param_text(p) for p in s['params'])}"
            active = d.get("active")
            if active:
                kind = "preview" if active.get("preview") else "active"
                yield (f"{kind}: {active['name']}  {active['oled'][1] if active.get('oled') else ''}"
                       f"  ({unit_hint(active)})")
                yield f"  session backup: {active.get('session_backup') or 'not yet'}"
            else:
                yield "active: no generated layout"
            target = d.get("target") or {}
            if target.get("text"):
                yield f"notes: {target['text']}"
            elif target.get("default"):
                yield f"default note target: {target['default']}"
            if d.get("message"):
                yield f"message: {d['message']}"
            if d.get("recovery"):
                yield f"recovery: {d['recovery']['message']}"
            for warning in d.get("warnings") or ():
                yield f"start-up: {warning}"
        return self.simple("GET", "/api/lab", None, lambda d: list(lines(d)))

    def c_validate(self):
        path = Path(self.a.path).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            self.complain(f"cannot read {self.a.path}: {error.strerror or error}")
            return EXIT_REFUSED
        try:
            status, data = self.t.request("POST", "/api/lab/validate", {"text": text, "file": path.name})
        except Exception as error:
            if type(error).__name__ != "ServiceDown" or self.cli.compile_offline is None:
                raise
            data = self.cli.compile_offline(text, path.name)
            status = 200 if data["valid"] else 400
        if self.as_json:
            self.say(json.dumps(data, ensure_ascii=False, indent=2))
        elif data.get("valid"):
            summary = data.get("summary") or "valid"
            if data.get("offline") and "ports not checked" not in summary:
                summary += " (ports not checked)"
            self.say(summary, *[f"warning: {w['text']}" for w in data.get("warnings") or ()])
        elif data.get("issues"):
            self.complain(*[i["text"] for i in data["issues"]])
        else:
            self.complain(data.get("problem") or f"refused ({status})")
        return EXIT_OK if data.get("valid") else EXIT_REFUSED

    def c_activate(self):
        return self.simple("POST", "/api/lab/activate", {"layout": self.a.name})

    def c_leave(self):
        return self.simple("POST", "/api/lab/leave", {})

    def c_key(self):
        words = [w.strip() for w in self.a.words if w.strip()]
        if not words:
            def lines(d):
                key = (d.get("active") or {}).get("key")
                if key is None:
                    return ["key: no generated layout is active"]
                now = f"{key['tonic']} {key['scale'].replace('-', ' ')}" if key["tonic"] else "none (chromatic)"
                return [f"key: {now}" + (f" for the session (the file: {key['file'] or 'none'})" if key["session"]
                                          else " (the layout's file)")]
            return self.simple("GET", "/api/lab", None, lines)
        head = words[0].lower()
        if head == "layout" and len(words) == 1:
            body = {"layout": True}
        elif head == "none" and len(words) == 1:
            body = {"tonic": None}
        else:
            body = {"tonic": words[0], "scale": "-".join(words[1:]) or "major"}
        return self.simple("POST", "/api/lab/key", body)

    def c_tweak(self):
        body = {"field": self.a.field, "value": _value(self.a.value)}
        if self.a.layout:
            body["layout"] = self.a.layout
        return self.simple("POST", "/api/lab/tweak", body)

    def c_push(self):
        body = {"entry": self.a.entry, "slot": _value(self.a.slot)}
        if self.a.offset is not None:
            body["offset"] = self.a.offset
        return self.simple("POST", "/api/lab/push", body)

    def c_preview(self):
        return self.simple("POST", "/api/lab/preview", {"entry": self.a.entry})

    def c_backup(self):
        if self.a.slot is not None:
            body = {"slot": _value(self.a.slot)}
        elif self.a.globals:
            body = {"slot": "globals"}
        else:
            body = {"all": True}
        return self.simple("POST", "/api/lab/backup", body)

    def c_backups(self):
        wanted = None if self.a.slot is None else (
            "globals" if str(self.a.slot).strip().lower() == "globals" else f"slot{int(_value(self.a.slot))}")

        def lines(d):
            rows = [b for b in d["backups"] if wanted is None or b["target"] == wanted]
            for b in rows:
                yield f"{b['id']}  {b['target']}  {b['size']} bytes"
            if wanted is None:
                for s in d["sets"]:
                    yield f"{s['id']}  {s['kind']} set of {len(s['members'])}" + ("" if s["complete"] else ", incomplete")
            if not rows and (wanted is not None or not d["sets"]):
                yield "no backups"
        return self.simple("GET", "/api/lab/backups", None, lambda d: list(lines(d)))

    def c_restore(self):
        return self.simple("POST", "/api/lab/restore", {"backup": self.a.backup, "slot": _value(self.a.slot)})

    def c_import(self):
        path = Path(self.a.file).expanduser()
        try:
            data = path.read_bytes()
        except OSError as error:
            self.complain(f"cannot read {self.a.file}: {error.strerror or error}")
            return EXIT_REFUSED
        return self.simple("POST", "/api/lab/import", {"name": self.a.name, "file": path.name,
                                                       "data_base64": base64.b64encode(data).decode()})

    def c_library(self):
        def line(e):
            if e["kind"] == "definition":
                return f"{e['name']}  generated ({e['generator']}, {e['layout']}.yaml)"
            if e["kind"] == "corrupt":
                return f"{e['name']}  corrupt: {e['error']}"
            return f"{e['name']}  {e['kind']} from {e.get('source') or '?'}  {e.get('pads', '?')} pads, " \
                   f"{e.get('strips', '?')} strips"
        return self.simple("GET", "/api/lab/library", None, lambda d: [line(e) for e in d] or ["the library is empty"])

    def c_capture(self):
        return self.simple("POST", "/api/lab/library/capture", {"slot": _value(self.a.slot), "name": self.a.name})

    def c_bulk_edit(self):
        return self.simple("POST", "/api/lab/bulk-edit", {"target": self.a.target, "edits": list(self.a.edits)})

    def c_globals(self):
        if not self.a.changes:
            return self.simple("GET", "/api/lab/globals", None,
                               lambda d: [f"{f['label']}: {f['text']}" for f in d["fields"]])
        body = {"changes": _pairs(self.a.changes)}
        if self.a.confirm:
            body["confirm"] = True
        return self.simple("POST", "/api/lab/globals", body)

    def c_harmony(self):
        def lines(d):
            yield f"chord: {d['chord']}"
            yield "held: " + (" ".join(n["name"] for n in d["held"]) or "nothing")
            if d["triads"]:
                yield "triads: " + ", ".join(t.get("display", t["label"]) for t in d["triads"])
            if d["neighbours"]:
                yield "neighbours: " + ", ".join(t.get("display", t["label"]) for t in d["neighbours"])
            if d["hints"]:
                yield "hints: " + ", ".join(t.get("display", t["label"]) for t in d["hints"])
            if d["degrees"]:
                yield "degrees: " + " ".join(f"{pc} {label}" for pc, label in d["degrees"].items())
            yield "trail: " + (" → ".join(d["trail"]) or "empty")
            if d["circle"]:
                yield "circle of fifths: " + " – ".join(d["circle"])
        return self.simple("GET", "/api/lab/harmony", None, lambda d: list(lines(d)))

    def c_trail(self):
        if self.a.action == "clear":
            return self.simple("POST", "/api/lab/harmony/trail/clear", {})
        return self.simple("GET", "/api/lab/harmony", None,
                           lambda d: ["trail: " + (" → ".join(d["trail"]) or "empty")])

    def c_inputs(self):
        def lines(d):
            if d.get("message"):
                yield d["message"]
            yield "APC64: " + ", ".join(d["apc64"])
            yield "other inputs: " + (", ".join(d["inputs"]) or "none")
        if self.a.none or self.a.ports:
            return self.simple("POST", "/api/lab/harmony/inputs", {"inputs": [] if self.a.none else self.a.ports},
                               lambda d: list(lines(d)))
        return self.simple("GET", "/api/lab/harmony/inputs", None, lambda d: list(lines(d)))

    def c_slot(self):
        def lines(d):
            yield f"slot {d['slot']}"
            for i, pad in enumerate(d["pads"]):
                row, column = i // 8 + 1, i % 8 + 1
                yield (f"  pad r{row}c{column}: note {pad['note']} ch {pad['channel']} rest {pad['rest']}"
                       f" pressed {pad['pressed']}" + (" aftertouch" if pad["aftertouch"] else ""))
            for i, strip in enumerate(d["strips"]):
                yield f"  strip {i + 1}: cc {strip['cc']} ch {strip['channel']} bar {strip['bar']}"
        return self.simple("GET", f"/api/lab/slots/{quote(str(self.a.n), safe='')}", None, lambda d: list(lines(d)))

    def c_dismiss_recovery(self):
        return self.simple("POST", "/api/lab/recovery/dismiss", {})

    # --- the performer (§2.10) -------------------------------------------------------------------------
    def c_performer(self):
        words = [w.strip() for w in self.a.words if w.strip()]
        if not words:
            return self.simple("GET", "/api/lab/performer", None, lambda d: list(performer_lines(d)))
        head, rest = words[0].lower(), words[1:]
        if head in ("on", "off") and not rest:
            body = {"enabled": head == "on"}
        elif head == "stop" and not rest:
            return self.simple("POST", "/api/lab/performer/stop", {})
        elif head == "pattern" and rest:
            body = {"pattern": " ".join(rest)}
        elif head == "latch" and len(rest) == 1 and rest[0].lower() in ("on", "off"):
            body = {"latch": rest[0].lower() == "on"}
        elif head == "play" and len(rest) == 1 and rest[0].lower() in ("all", "pressed", "pattern"):
            body = {"play": None if rest[0].lower() == "pattern" else rest[0].lower()}
        elif head == "tempo" and len(rest) >= 2 and rest[0].lower() == "clock":
            body = {"clock": " ".join(rest[1:])}
        elif head == "tempo" and len(rest) == 1:
            try:
                body = {"bpm": float(rest[0])}
            except ValueError:
                raise ValueError(f"'{rest[0]}' is not a tempo; write e.g. 'tempo 96' or 'tempo clock <PORT>'") from None
        elif head == "type" and len(rest) == 1:
            body = {"chord_type": None if rest[0].lower() == "off" else rest[0]}
        elif head == "slot" and len(rest) == 1 and rest[0].isdigit():
            body = {"slot": int(rest[0])}
        elif head == "revert" and rest:
            body = {"revert": " ".join(rest)}
        elif head == "new" and not rest:
            body = {"new_pattern": True}
        else:
            raise ValueError("write: on | off | stop | pattern NAME | latch on|off | play all|pressed|pattern | "
                             "tempo BPM | tempo clock PORT|auto | type NAME|off | slot N | revert NAME | new")
        return self.simple("POST", "/api/lab/performer", body)

    def c_patterns(self):
        def line(row):
            if not row["valid"]:
                return f"{row['id']}  invalid: {row['error']}"
            return f"{row['id']}  {row['name']}  {row['meter']} · {row['step']} · {row['length']} steps · play {row['play']}"
        return self.simple("GET", "/api/lab/patterns", None, lambda d: [line(r) for r in d] or ["no patterns in patterns/"])

    def c_pattern(self):
        return self.simple("GET", f"/api/lab/patterns/{quote(self.a.name, safe='')}", None, pattern_lines)

    def c_validate_pattern(self):
        path = Path(self.a.path).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            self.complain(f"cannot read {self.a.path}: {error.strerror or error}")
            return EXIT_REFUSED
        try:
            status, data = self.t.request("POST", "/api/lab/patterns/validate", {"text": text, "file": path.name})
        except Exception as error:
            if type(error).__name__ != "ServiceDown" or self.cli.pattern_offline is None:
                raise
            data = self.cli.pattern_offline(text, path.name)
        if self.as_json:
            self.say(json.dumps(data, ensure_ascii=False, indent=2))
        elif data.get("valid"):
            self.say(data.get("summary") or "valid", *[f"warning: {w['text']}" for w in data.get("warnings") or ()])
        else:
            self.complain(*[i["text"] for i in data.get("issues") or ()] or [data.get("problem") or "invalid"])
        return EXIT_OK if data.get("valid") else EXIT_REFUSED

    def c_write_pattern(self):
        path = Path(self.a.path).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            self.complain(f"cannot read {self.a.path}: {error.strerror or error}")
            return EXIT_REFUSED
        body = {"id": self.a.id or path.stem, "text": text, "create": bool(self.a.new)}
        return self.simple("POST", "/api/lab/patterns/save", body, lambda d: [d["message"], *[
            f"warning: {w}" for w in d.get("warnings") or ()]])

    def c_delete_pattern(self):
        return self.simple("POST", "/api/lab/patterns/delete", {"id": self.a.name})

    def c_pattern_versions(self):
        return self.simple("GET", f"/api/lab/patterns/{quote(self.a.name, safe='')}/versions", None,
                           lambda d: [v["version"] for v in d["versions"]] or [f"no versions of {d['id']} are kept"])

    def c_restore_pattern(self):
        return self.simple("POST", "/api/lab/patterns/restore", {"id": self.a.name, "version": self.a.version})


def pattern_lines(p: dict) -> list[str]:
    """A pattern as its grid: one row per lane (manual ones named), the strum row, a | at every bar."""
    bar = p.get("bar") or 0

    def row(cells):
        return " ".join(("| " if k and bar and k % bar == 0 else "") + c for k, c in enumerate(cells))
    lines = [f"{p['name']}  {p['meter']} · {p['step']} · {p['length']} steps · play {p['play']}"]
    if p.get("description"):
        lines.append(f"  {p['description']}")
    for lane in p["lanes"]:
        lines.append(f"  {lane['lane']:>2}: " + ("manual" if lane["manual"] else row(lane["cells"])))
    if p.get("strum"):
        lines.append("  strum: " + row(p["strum"]))
    lines += [f"warning: {w}" for w in p.get("warnings") or ()]
    return lines


def clock_text(tempo: dict) -> str:
    """What the clock is doing, as the page says it."""
    chosen = "auto" if tempo.get("clock") == "auto" else tempo.get("clock")
    following = tempo.get("following")
    if tempo.get("measured"):
        text = f"following {following}: {tempo['measured']:.1f} BPM"
    elif tempo.get("stopped"):
        text = f"the clock of {following} stopped; keeping {tempo.get('bpm', 0):.1f} BPM"
    else:
        text = (f"no clock heard from {following or 'any input'} yet (the MPC sends its clock while its sequencer "
                "plays, to the outputs its sync settings send clock to)")
    heard = [port for port in tempo.get("heard") or () if port != following]
    return f"clock {chosen}: {text}" + (f"; also heard: {', '.join(heard)}" if heard else "")


def performer_lines(d: dict):
    if not d.get("available"):
        yield f"performer: {d.get('message') or 'no generated layout is active'}"
        return
    pattern = d.get("pattern")
    tempo = d.get("tempo") or {}
    speed = (clock_text(tempo) if tempo.get("source") == "clock" else f"{tempo.get('bpm', 0):g} BPM")
    yield (f"performer: {'on' if d['enabled'] else 'off'} · {d['name']} · {d['addressing']}"
           f" · latch {'on' if d['latch'] else 'off'} · play {d.get('play') or '-'} · {speed}")
    yield ("pattern: " + (f"{pattern['name']} ({pattern['id'] or 'new'}"
                          + (", edited, not saved)" if pattern.get("edited") else ")") if pattern else "none")
           + (f" · step {d['step']}/{d['length']}" if d.get("running") else " · stopped"))
    edits = d.get("edits") or ()
    if edits:
        yield "unsaved edits (kept until the service restarts): " + ", ".join(
            f"{e['name']} (new)" if e.get("new") else e["id"] for e in edits)
    if d.get("controls"):
        yield f"unit: {d['controls']}"
    chords = d.get("chords") or {}
    key = d.get("key")
    if chords.get("available"):
        yield ("key: " + (f"{key['tonic']} {key['scale'].replace('-', ' ')}" + ("" if key["chords"] else
               " (the key's chords need a seven-note scale)") if key else "none (chromatic)"))
    if chords.get("available") and d.get("from_layout"):
        voicing = d.get("voicing")
        yield ("chord type: " + (chords.get("selected") or "off") + " (" + ", ".join(chords.get("types") or ()) + ")"
               + (f" · voicing {voicing['symbol']} {voicing['shape']}" if voicing else ""))
    slots = [slot for slot in d.get("slots") or () if slot]
    if slots:
        yield "slots: " + " · ".join(("*" if d.get("slot") == slot["slot"] else "") + f"{slot['slot']} {slot['name']}"
                                     for slot in slots)
    if d.get("pads"):
        yield f"pads: {d['pads']}"
    if d.get("message"):
        yield f"message: {d['message']}"
