# APC64 Host — HTTP/WebSocket API and the `apc64` command

The page in the browser and the `apc64` command use **the same API**, so anything the page can do, an agent can
do too, with the same result. The service listens on port **5058** (dual-stack, `[::]:5058`), on loopback and
the home network. There is no login.

Port names in the examples (`MPC Live III MIDI 1`, `Bitwig Studio In`, `USB MIDI Interface MIDI 1`) are
examples from the author's setup; use the names `apc64 ports` lists on your machine.

- **Who may call:** clients in the configured private ranges (loopback, 10/8, 172.16/12, 192.168/16, 169.254/16,
  IPv6 `::1`, `fe80::/10`, `fc00::/7`; change with `APC64_ALLOWED_NETWORKS`). Everyone else gets
  `403 {"problem": "not on the home network"}`.
- **Cross-site requests** (a page from another site in your browser) are refused with
  `403 {"problem": "cross-site request refused"}`: an `Origin` header must name the same host and port as the
  `Host` header, and the `Host` must be this machine (an IP address, `localhost`, or a name whose first label is
  the machine's host name). Requests without an `Origin` (curl, the CLI) pass.
- **Bodies** are JSON objects. Answers: **200** with the route's JSON; **400** `{problem, allowed?}` for a
  malformed or out-of-range request (nothing changes); **409** `{problem}` for a refusal (`already held`,
  `APC64 is not held`, `layout changed, reload`, `no layout x`, `Busy: held by Bitwig Studio`, …).
- **Names:** controls are named as in layouts: `pad r1c1`…`pad r8c8` (row 1 at the bottom), `track 1`…`8`,
  `trackctl 1`…`8`, `scene 1`…`8`, `stripmode 1`…`6`, `strip 1`…`8`, `strip 1 touch`, `tempo`, `clear`,
  `duplicate`, `quantize`, `fixed`, `undo`, `play`, `rec`, `stop`, `up`, `down`, `left`, `right`, `recarm`,
  `mute`, `solo`, `clipstop`, `shift`, `encoder`, `encoder press`, and the unit's own `view session`, `view note`,
  `view chord`, `view step`, `view project`, `view custom`. In a URL, encode the space (`pad%20r1c1`).
  A layout is named by its file name without `.yaml` (`jam`); its display name (`Jam`) is accepted where a layout
  is loaded.
- **Times** (`at`) are seconds since the epoch, except version times (ISO 8601, UTC).
- **Colours** carry the palette index and an `rgb` that is an **approximation** (Ableton palette): the APC64's
  exact colours are not known.

Examples below use `curl` against `http://127.0.0.1:5058`; the same calls work from any home-network address.

## The unit

### `GET /api/state` — everything the page shows

```sh
curl -s http://127.0.0.1:5058/api/state
```
```json
{"unit": {"status": "held", "text": "Held (taken by command-line tool)", "held": true, "holder": null,
          "taken_by": "agent", "firmware": "1.2.1.6", "warnings": [], "notices": [], "view": "session"},
 "layout": "jam", "layout_name": "Jam", "file_deleted": false,
 "page": {"n": 1, "name": "Drums", "display": "Drums", "defined": true, "current": true},
 "bank": {"n": 1, "name": "Mix", "display": "Mix", "defined": true, "current": true},
 "shift": false,
 "pages": [{"n": 1, "name": "Drums", "display": "Drums", "defined": true, "current": true}, "… 8 in all"],
 "banks": [{"n": 1, "name": "Mix", "display": "Mix", "defined": true, "current": true}, "… 6 in all"],
 "controls": {"pad r1c1": {"label_base": "Note 36 → mpc", "label_shift": "", "empty": false, "missing": [],
                           "toggle": null, "led": {"colour": 5, "behaviour": 1, "rgb": "#ff0000",
                           "brightness": 0.25, "animation": null, "off": false},
                           "bar": null, "role": "bindable", "selected": false},
              "strip 1": {"label_base": "CC20 → mpc", "…": "…",
                          "bar": {"value": 0, "colour": 3, "rgb": "#ffffff", "style": "bar", "lit": true}},
              "…": "every physical control"},
 "oled": ["Jam", "P1 Drums | B1"],
 "errors": [{"file": "broken.yaml", "line": 7, "control": null, "problem": "unknown device mcp",
             "fix": "declared devices: mpc", "severity": "error",
             "text": "broken.yaml line 7: unknown device mcp; declared devices: mpc"}],
 "warnings": [],
 "routing": {"notes": "mpc ch 2", "custom": null, "status": ""},
 "calibration": null, "calibration_label": "pad position unknown", "calibration_step": "idle",
 "learn": {"mode": "off", "selected": null, "port": null, "device": null, "last": null},
 "played": [{"role": "notes", "note": 53, "label": "F2 (53)", "velocity": 56, "aftertouch": 0, "routed": true,
             "pad": null, "position": "pad position unknown", "text": "F2 (53) vel 56 · pad position unknown"}],
 "layouts": [{"id": "jam", "name": "Jam", "file": "jam.yaml", "valid": true, "pages": 2, "banks": 1,
              "errors": 0, "warnings": 0, "deleted": false}],
 "palette_note": "approximate colours (Ableton palette); the APC64's exact RGB is not known"}
```

- `unit.status` is one of `absent`, `asking`, `declined`, `busy`, `no_permission`, `held`, `unplugged`,
  `maybe_stuck`; `unit.text` is the sentence the page shows (`Take control of APC64?`,
  `Busy: held by Bitwig Studio`, `No permission to open APC64`, `APC64 unplugged: released`,
  `APC64 may still be in DAW mode: Take to reset, or replug it`, …). `notices` carries extra sentences such as
  `APC64 Notes busy: expressive pads not routed`, `No APC64 identity reply`, `Released after an internal error`
  or `second APC64 ignored`; `warnings` e.g. `untested firmware 1.2.2.0`. `view` is the unit's pad mode
  (`session`, `note`, `chord`, `step`, `drum`, `project`, `custom`, `overview`).
- `controls[id]`: `label_base`/`label_shift` are what the control does on each layer right now (`""` = empty);
  `empty` is for the current layer; `missing` lists devices whose port is absent; `toggle` is a toggle's latch
  state; `led` and `bar` are what the unit shows (or would show while held).
- `errors` lists every invalid layout file's issues in file/line order, with the same `text` the CLI prints.
- `played` is the played-notes row: notes sounding from the unit's own views, labelled with their pad position
  only when calibrated (`calibrated 14:02 (assumed)`), else `pad position unknown`.

### `GET /api/unit` — just `state.unit`

### `POST /api/unit/take` — say yes

Body: `{"source": "agent"}` (the CLI) or `{"source": "banner"}` (the page; from another home-network machine it
counts as that browser's yes). An agent's take counts as the user's yes, since the agent acts on their instruction.

```sh
curl -s -X POST http://127.0.0.1:5058/api/unit/take -H 'content-type: application/json' -d '{"source":"agent"}'
```
```json
{"result": "taken", "text": "Held", "status": "held", "status_text": "Held (taken by command-line tool)", "by": "agent"}
```
Refusals are 409 with the sentence: `already held`, `Busy: held by Bitwig Studio`,
`No permission to open APC64`, `APC64 not connected`, `No APC64 identity reply`.

### `POST /api/unit/decline` — say no

`{}` → `{"status": "declined", "text": "Not held"}`. The port stays free; the next appearance asks again.

### `POST /api/unit/release` — hand the unit back

LEDs and OLED are cleared, DAW mode is switched off and the port is freed (Bitwig can open it at once).

```json
{"result": "released", "text": "Not held", "status": "asking", "status_text": "Take control of APC64?"}
```
When nothing is held: `409 {"problem": "APC64 is not held"}`.

## Ports and layouts

### `GET /api/ports`

Every MIDI port by name (never the APC64's own), then the live layout's declared devices whose port is missing.

```json
[{"name": "MPC Live III MIDI 1", "direction": "both", "present": true, "device": null},
 {"name": "Bitwig Studio In", "direction": "declared", "present": false, "device": "bitwig"}]
```

### `GET /api/layouts`

```json
[{"id": "jam", "name": "Jam", "file": "jam.yaml", "valid": true, "pages": 2, "banks": 1, "errors": 0,
  "warnings": 0, "deleted": false}]
```
`deleted: true` means the file was deleted while the layout is still live from memory.

### `POST /api/validate` — check layout text, never apply it

Body: `{"text": "<the YAML>", "file": "draft.yaml"}`. The file name only labels the issues; the service never
reads a path you name (a `{"path": …}` body is refused with 400). Port names are checked against the ports
present now.

```sh
python - <<'EOF' | curl -s -X POST http://127.0.0.1:5058/api/validate -H 'content-type: application/json' -d @-
import json; print(json.dumps({"text": open("layouts/jam.yaml").read(), "file": "jam.yaml"}))
EOF
```
```json
{"valid": false, "summary": "invalid: 1 error",
 "errors": [{"file": "x.yaml", "line": 3, "control": "page 9", "problem": "the APC64 has 8 scene buttons",
             "fix": "so pages are 1–8", "severity": "error",
             "text": "x.yaml line 3, page 9: the APC64 has 8 scene buttons, so pages are 1–8"}],
 "warnings": [], "counts": null, "ports_checked": true}
```
A valid answer reads e.g. `"summary": "valid: 1 page, 1 bank, 16 pads, 8 strips bound"` with
`counts: {pages, banks, pads, buttons, strips, encoders, routes}`.

### `GET /api/layouts/{id}/versions` — every version that went live, newest first

```json
[{"id": "20261023T104200.123Z-67137b308ee0", "at": "2026-10-23T10:42:00.123Z", "hash": "67137b30…"}]
```

### `POST /api/layouts/{id}/restore` — bring a version back

Body `{"id": "20261023T104200.123Z-67137b308ee0"}` → `{"restored": "…", "at": "…", "layout": "jam"}`. The version
is written back as the layout file and goes live like any other write (within about a second); every version
stays listed. Unknown version: 409 with `allowed` (the newest 20 ids).

## Navigation

All four answer with the whole state (as `GET /api/state`) after the change was handled; the last switch wins.

| route | body | refusal |
|---|---|---|
| `POST /api/layout` | `{"name": "Tonnetz C"}` or `{"name": "tonnetz"}` | 409 `{"problem": "no layout Ambient", "allowed": ["jam", "tonnetz"]}` |
| `POST /api/page` | `{"n": 3}` | 400 `{"problem": "page must be 1–8", "allowed": [1, …, 8]}` |
| `POST /api/bank` | `{"n": 2}` | 400 `{"problem": "bank must be 1–6", "allowed": [1, …, 6]}` |
| `POST /api/shift` | `{"held": true}` | 400 `{"problem": "held must be true or false"}` |

Loading a layout opens its page 1 and bank 1. Selecting an empty page or bank keeps the current one (the OLED
says `Page 5 empty`). Shift held in the page counts as Shift held on the unit.

```sh
curl -s -X POST http://127.0.0.1:5058/api/page -H 'content-type: application/json' -d '{"n":2}'
```

## Playing the replica

The same path as the unit's own controls: the binding of the current page, bank and Shift state is sent.

| route | body | does |
|---|---|---|
| `POST /api/control/{id}/press` | `{"value": 127}` (velocity, optional) | press; `strip n` means its touch, `encoder` its press |
| `POST /api/control/{id}/release` | `{}` | release |
| `POST /api/control/{id}/move` | `{"value": 0–16383}` for `strip n`; `{"value": ±steps}` for `encoder` | strip position or encoder turn |

```sh
curl -s -X POST 'http://127.0.0.1:5058/api/control/pad%20r1c1/press' -H 'content-type: application/json' -d '{}'
curl -s -X POST 'http://127.0.0.1:5058/api/control/pad%20r1c1/release' -H 'content-type: application/json' -d '{}'
curl -s -X POST 'http://127.0.0.1:5058/api/control/strip%204/move' -H 'content-type: application/json' -d '{"value":16383}'
```
Answers: the state. Refused with 400: an unknown control, the unit's own view buttons
(`view note is the unit's own button; it never reaches the host`), a move on a control that does not move.
Replica input works when no APC64 is attached: the bound MIDI is still sent.

## Reading controls

### `GET /api/controls/{id}` — the detail card

```json
{"control": "pad r1c1", "display": "Pad r1c1", "role": "bindable",
 "base": "Note 36 → mpc ch 10, momentary", "shift": "Note 48 → mpc ch 10, momentary", "mode": "momentary",
 "toggle": null, "feedback": null, "port_status": ["mpc connected"],
 "elsewhere": [{"page": 2, "bank": null, "layer": "base", "binding": "Note 50", "text": "Page 2: Note 50"}],
 "reachable": "unverified: live check pending",
 "lines": ["Base: Note 36 → mpc ch 10, momentary", "Shift: Note 48 → mpc ch 10, momentary", "mpc connected",
           "Page 2: Note 50", "Shift layer: unverified: live check pending"],
 "led": {"colour": 5, "behaviour": 1, "rgb": "#ff0000", "brightness": 0.25, "animation": null, "off": false},
 "selected": false,
 "forms": {"base": {"assignment": "note 36 on mpc ch 10", "label": null,
                    "colour": {"index": 5, "name": "red", "rgb": "#ff0000"}, "mode": "momentary"},
           "shift": {"assignment": "note 48 on mpc ch 10", "label": null, "colour": null, "mode": "momentary"}},
 "layout": "jam", "page": 1, "bank": 1, "layer": "base", "base_hash": "67137b308ee0b9c5…"}
```
`role` is `bindable`, `navigation` (scene and strip-mode buttons), `modifier` (Shift) or `device_local` (the
unit's own view buttons). `reachable` says whether the Shift layer of that control is known to reach the host.
`base_hash` is the layout file's hash when the card was read: send it with a tweak. Unknown control: 400.

### `GET /api/overview` — every page and bank of the live layout

```json
{"layout_name": "Jam", "page": 1, "bank": 1,
 "pages": [{"n": 1, "name": "Drums", "defined": true,
            "base": {"pad r1c1": {"label": "Note 36 → mpc", "colour": 5, "rgb": "#ff0000"}}, "shift": {}}],
 "banks": [{"n": 1, "name": "Mix", "defined": true,
            "base": {"strip 1": {"label": "CC20 → mpc", "colour": 3, "rgb": "#ffffff"}}, "shift": {}}],
 "palette_note": "approximate colours (Ableton palette); the APC64's exact RGB is not known"}
```
(8 pages and 6 banks are always listed; empty ones have `defined: false`.)

### `GET /api/surface` — the physical unit

```json
{"controls": [{"id": "pad r1c1", "name": "pad r1c1", "role": "bindable", "display": "Pad r1c1",
               "geometry": {"x": 9.5, "y": 8, "w": 1.0, "h": 1.0}, "led": "rgb",
               "shift_reach": "unverified: live check pending"}],
 "palette": [{"index": 5, "name": "red", "rgb": "#ff0000"}],
 "palette_note": "approximate colours (Ableton palette); the APC64's exact RGB is not known", "approximate": true}
```

### `GET /api/activity?limit=200` — what was sent, newest first (at most 200)

```json
[{"id": 1, "folded": false, "at": 1792745943.639, "control": "pad r1c1", "message": "note 36 ch 10",
  "port": "MPC Live III MIDI 1", "result": "sent", "reason": null, "note": null, "aftertouch": null,
  "text": "pad r1c1 → note 36 ch 10 → MPC Live III MIDI 1: sent"}]
```
`result`: `sent`, `not_sent` (with `reason`, e.g. `mpc missing`), `refused` (`text`: `refused: project write
(0x14)`), `unbound` (`pad r8c8: unbound`) or `dropped` (`dropped: note 144 out of range`). A played note's
aftertouch updates its own entry (`folded: true`, same `id`).

### `GET /api/device-log?limit=N` — frames offered to the APC64, in send order

```json
[{"at": 1792745943.617, "hex": "F0 47 00 53 10 00 10 01 4C 61 79 6F 75 74 …", "command": "oled_text",
  "outcome": "sent", "hazard": false, "text": "oled_text"},
 {"at": 1792745950.002, "hex": "F0 47 00 53 14 00 00 F7", "command": "project_write", "outcome": "refused",
  "hazard": true, "text": "refused: project write (0x14)"}]
```
Project and global-settings reads and writes (0x13, 0x14, 0x17, 0x18) are never sent; each attempt appears here
as a hazard.

## Changing a control

### `POST /api/tweak` — one control, one field, saved as one line of the layout file

```json
{"control": "pad r1c3", "field": "colour", "value": "red", "base_hash": "67137b308ee0b9c5…",
 "layer": "base", "page": 1, "layout": "jam"}
```
- `field`: `assignment` (a binding phrase in layout notation, e.g. `note 38 on mpc ch 10`, `cc 74 on mpc ch 1`,
  or `none`/empty to unbind), `label` (empty removes it), `colour` (a name or an index 0–127; empty removes it) or
  `mode` (`momentary` or `toggle`; not for strips).
- `layer` (`base`/`shift`), `page` (pads and buttons) or `bank` (strips) and `layout` default to what is shown.
- `base_hash` is required: the card's `base_hash`.

Answers: `200 {"ok": true, "hash": "<new hash>"}`; `409 {"problem": "layout changed, reload"}` when the file
changed since the card was read (re-read the card and try again); `400 {"problem": "<first issue>", "issues":
[…]}` when the result would be invalid (e.g. `… channel must be 1–16`) — the file is untouched. The tweak goes
live through the normal reload. Ranges, comments and every other line stay byte-identical; a control inside a
range gets one override line, and tweaking it back to the range's value removes that line.

### `POST /api/learn` — learn by touch, MIDI-learn

| body | effect |
|---|---|
| `{"mode": "touch"}` | touching a control on the unit selects it (in `state.learn.selected`) and sends nothing |
| `{"mode": "midi", "port": "mpc", "control": "pad r2c1"}` | the next note, CC, program change or pitch bend arriving on that device's (or ALSA port's) input becomes the control's binding on the current page/bank and layer |
| `{"mode": "off"}` | stop; nothing changes if nothing arrived |

Answer: `{"mode": "touch", "selected": null, "port": null, "device": null, "last": null}` (`last` says what the
last capture did, e.g. `pad r2c1: cc 74 on mpc ch 1 saved`). Unknown port: 409 with the layout's devices.

### `POST /api/calibrate` — Note-view pad positions

`{"step": "start"}` → `{"step": "waiting for bottom-left", "text": "press the bottom-left pad", "problem": null,
"calibration": null}`. In the unit's Note view press the bottom-left pad, then the top-right pad. Positions are
then shown as `calibrated <time> (assumed)` — the unit's Note settings cannot be read, so they stay an
assumption. `{"step": "cancel"}` stops.

## WebSockets

### `/ws` — the page's live state

On every (re)connect: `{"type": "snapshot", "data": <GET /api/state>}`, then
`{"type": "activity_list", "data": [<activity entries, newest first>]}`. Then, in order:
`{"type": "diff", "data": {"changed": {<top-level state fields that changed>}, "controls": {<id>: <control>}}}`
and `{"type": "activity", "data": <one entry>}` (a folded entry repeats its `id`). A client that stops reading for
long is sent a fresh snapshot instead of the backlog.

### `/ws/play` — what is played, for agents

From the moment of connecting, one message per event, in order:

```json
{"type": "event", "data": {"at": 1792745943.656, "kind": "release", "source": "replica", "view": "session",
 "control": "pad r1c1", "note": null, "value": null, "velocity": null, "aftertouch": null,
 "sent": ["note-off 36 ch 10"], "reason": null}}
```
`kind`: `press`, `release`, `move`, `turn`, `note_on`, `note_off`, `aftertouch`, `nav`, `shift`, `view`,
`layout`; `source`: `unit` or `replica`. A watcher more than 5 s behind gets
`{"type": "closed", "reason": "too slow", "data": {"reason": "too slow", "text": "stream closed: too slow"}}` and
the socket closes (code 4000); the unit and the other watchers are unaffected.

```sh
python -m websockets ws://127.0.0.1:5058/ws/play     # or: apc64 watch
```

## The `apc64` command

Installed into the repo venv (`.venv/bin/apc64`); also `python -m _apc64_host <command>`. It talks to
`http://127.0.0.1:<APC64_HTTP_PORT>` (or `--url`, or `APC64_URL`). `--json` prints the API's JSON.

Exit codes: **0** done; **1** refused or invalid (the problem or the issues are printed on stderr); **2** the
service is not running (`service not running on port 5058`).

| command | API | example output |
|---|---|---|
| `apc64 take` | `POST /api/unit/take {"source":"agent"}` | `Held (taken by command-line tool)` |
| `apc64 decline` | `POST /api/unit/decline` | `Not held` |
| `apc64 release` | `POST /api/unit/release` | `Not held` / `APC64 is not held` (exit 1) |
| `apc64 ports` | `GET /api/ports` | `MPC Live III MIDI 1  (both)` |
| `apc64 layouts` | `GET /api/layouts` | `jam.yaml  Jam  2 pages, 1 bank` |
| `apc64 validate PATH` | `POST /api/validate {text, file}` | `valid: 1 page, 1 bank, 16 pads, 8 strips bound` or the issues, one per line (exit 1) |
| `apc64 load NAME` | `POST /api/layout` | `Tonnetz C: page 1 Fifths, bank 1 Mix` |
| `apc64 page N` | `POST /api/page` | `Jam: page 2 Keys, bank 1 Mix` / `page must be 1–8` + `allowed: 1, …, 8` (exit 1) |
| `apc64 bank N` | `POST /api/bank` | `Jam: page 1 Drums, bank 2 Sends` |
| `apc64 shift on\|off` | `POST /api/shift` | `Jam: page 1 Drums, bank 1 Mix, Shift held` |
| `apc64 state` | `GET /api/state` | unit, layout/page/bank, OLED, routing, learn, warnings and errors |
| `apc64 watch` | `/ws/play` | `12:00:01.234 unit pad r1c1 press vel 127 → note-on 36 vel 127 ch 10` per event until Ctrl-C; `stream closed: too slow` (exit 1) |
| `apc64 versions NAME` | `GET /api/layouts/{id}/versions` | `20261023T104200.123Z-67137b308ee0  2026-10-23T10:42:00.123Z` |
| `apc64 restore NAME VERSION` | `POST /api/layouts/{id}/restore` | `restored … it goes live like any write` |
| `apc64 card CONTROL` | `GET /api/controls/{id}` | `Pad r1c1` / `Base: Note 36 → mpc ch 10, momentary` / … |
| `apc64 overview` | `GET /api/overview` | one line per defined page and bank |
| `apc64 activity [-n N]` | `GET /api/activity` | `12:00:01  pad r1c1 → note 36 ch 10 → MPC Live III MIDI 1: sent` |
| `apc64 device-log [-n N]` | `GET /api/device-log` | `12:00:01  oled_text  F0 47 …` (`HAZARD refused: …` for refused frames) |
| `apc64 tap CONTROL [--velocity V]` | press then release | `pad r1c1: pressed and released` |
| `apc64 move CONTROL VALUE` | `POST /api/control/{id}/move` | `strip 4: 16383` |
| `apc64 turn STEPS` | `POST /api/control/encoder/move` | `encoder: +1` |
| `apc64 tweak CONTROL FIELD [VALUE] [--layer L] [--page N\|--bank N]` | card, then `POST /api/tweak` | `saved: pad r1c3 colour` / `layout changed, reload` (exit 1) |
| `apc64 learn touch\|off\|midi PORT [--control C]` | `POST /api/learn` | `learn midi on MPC Live III MIDI 1, selected pad r2c1` |
| `apc64 calibrate start\|cancel` | `POST /api/calibrate` | `press the bottom-left pad` |

**Validation without the service:** `apc64 validate PATH` compiles the file locally when the service is not
running — structure only, the summary ends with `(ports not checked)`, exit 0 when valid and 1 otherwise. Every
other command then says `service not running on port 5058` and exits 2.

A typical agent session:

```sh
apc64 validate layouts/tonnetz.yaml        # fix every issue it prints, then save it under layouts/
apc64 layouts                              # the file is picked up within a second
apc64 load "Tonnetz C" && apc64 page 3 && apc64 bank 2
apc64 state
apc64 watch --json                         # one JSON event per line while the user plays
```

Writing layouts: see `docs/layout-guide.md` and `docs/layout.schema.json`.
