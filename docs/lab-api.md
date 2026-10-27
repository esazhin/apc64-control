# APC64 Lab: HTTP API and the `apc64 lab` command

Port names in the examples (`MPC Live III MIDI 1`, `Bitwig Studio In`, `USB MIDI Interface MIDI 1`) are
examples from the author's setup; use the names `apc64 ports` lists on your machine.

The lab adds routes beside the host's (see [`api.md`](api.md)) on the same service: port **5058**, loopback and the
home network, no login, behind the same network guard. The page's Lab panel and `apc64 lab …` use these same
routes, so a command gives the same result and the same message from the page, the CLI or an agent (inv9).
Writing generated layouts: see [`lab-guide.md`](lab-guide.md) and [`lab.schema.json`](lab.schema.json).

## Answers

- A **write or command** answers `200 {"result", "backup", "message"}`, where `result` is one of `pushed`,
  `restored`, `unchanged`, `backed_up`, `stored` or `activated`. `backup` names the backup taken first, when
  there was one. A few commands add what they produced, for example `set` (a backup set) or `pads`/`strips`
  (an import).
- A **refusal or failure** answers `{"problem", "fix"?, "field"?, "result": "refused"|"failed", "backup", "code"}`,
  with a status by `code`:

  | code | status | for example |
  |---|---|---|
  | `invalid` | 400 | `slot 25: slots are 1–24`, `CV3 channel 17: channels are 1–16` |
  | `busy` | 409 | `busy: push to slot 5 in progress` |
  | `not_held` | 409 | `take control of the APC64 first; nothing read or written` |
  | `session` | 409 | `slot 0 belongs to the running lab session; leave it first, it restores slot 0 itself` |
  | `taken` | 409 | `name "Live set B" is already in the library` |
  | `firmware` | 409 | `the APC64 reports firmware 1.2.0.0; memory writes are verified only on 1.2.1.6` |
  | `not_found` | 404 | `no backup slot7-2026-10-24T12-00` |
  | `corrupt` | 422 | `slot7-2026-10-24T12-00 holds 512 bytes, expected 880; not restored` |
  | `storage` | 500 | `could not save a backup (backups/…: Permission denied)` |
  | `unit` | 502 | `could not back up slot 7; nothing written`, `slot 7 may be partial; restore slot7-2026-10-24T20-30` |

- A **layout issue** (validate, tweak) answers `400 {"problem", "fix", "file", "line", "field", "text", "issues"}`.
  The top-level fields are the first issue's, and `issues` lists every issue in line order, each with its `text`.
- A **malformed request** answers `400 {"problem", "allowed"?}`, and nothing is read or written.
- `message` and `problem` are the one text: the page and the CLI show them verbatim.

Calls that read or write the unit can take seconds: a read waits up to 2 s for the unit, and backing up all
slots takes 26 reads.

## The panel's state

### `GET /api/lab`

```json
{"kind": "lab",
 "generators": [{"name": "tonnetz", "file": "_apc64_lab/domain/generators.py",
                 "params": [{"name": "base", "kind": "note", "default": 48, "min": 0, "max": 127, "doc": "note on pad r1c1 (C3 = 60)"},
                            {"name": "channel", "kind": "channel", "default": 1, "min": 1, "max": 16, "doc": "…"}]},
                {"name": "spiral", "file": "_apc64_lab/generators/spiral.py", "broken": true, "error": "division by zero"}],
 "schemes": [{"name": "fifths", "file": "…"}, {"name": "root-highlight", "file": "_apc64_lab/generators/root_highlight.py"},
             {"name": "scale", "file": "_apc64_lab/generators/scale.py",
              "params": [{"name": "scale", "kind": "choice", "default": "major", "choices": ["chromatic", "major", "…"], …},
                         {"name": "root", "kind": "pitch-class", "default": null, …}]}],
 "active": {"layout": "tonnetz-c", "name": "Tonnetz C", "preview": false, "interval": "5th", "offset": 2,
            "counts": {"octave": 0, "fifth": 2, "third": 0}, "transposition": 14, "unit_view": "custom",
            "session_backup": "slot0-2026-10-24T20-15", "oled": ["Tonnetz C", "5th +2"], "starting": false,
            "definition": {"generator": "tonnetz", "params": {"base": 48, "channel": 1}, "scheme": "fifths",
                           "scheme_params": {}},
            "pads": [{"pad": "r1c1", "note": 62, "rest": "#FF0000", "silent": false, "name": "D"}, "… 64 in all"],
            "rows": null, "scale": null, "neck": null,
            "window": {"steps": ["Oct", "5th", "3rd"], "step": "5th", "label": "5th +2"}},
 "message": null, "recovery": null,
 "target": {"default": "MPC Live III MIDI 1 ch 2 aftertouch pass", "routed": true, "from": "layout",
            "text": "MPC Live III MIDI 1 ch 1 aftertouch pass"},
 "warnings": []}
```

- `active` is null when no generated layout or preview plays.
- `pads[].rest` is the RGB written to the unit. It is exact, not a palette approximation. `pads[].name` is the
  note's spelling for the page's pad grid: the generator's own (each `modes` row in its mode), else the scale
  overlay's where the note is in the scale, else the fixed table.
- `rows` is the generator's 8 row names, bottom first, or null: the `modes` explorer gives
  `["Locrian", "Phrygian", "Aeolian", "Dorian", "Mixolydian", "Ionian", "Lydian", "Chromatic"]`.
- `scale` is the `scale` scheme's overlay, or null:
  `{"key": "dorian", "name": "Dorian", "root": 2, "root_name": "D", "pcs": [0, 2, 4, 5, 7, 9, 11], "names": {"2": "D", …}}`.
- `window` is the window as the page shows it: the step kinds Tempo cycles, the current one and row 2's text. A
  generator with its own window (the guitar) has no `counts` (`{}`), `interval` is its step kind and `offset` and
  `transposition` its position, and `window` adds the range and the page stops:
  `{"steps": ["Fret", "Page"], "step": "Fret", "position": 3, "label": "Fret 3-10", "lowest": 0, "highest": 17,
  "pages": [0, 8, 16, 17], "shown": 8, "unit": "Frets"}`. `label` is the page's window line (the step kind);
  with a `unit`, the OLED's row 2 (`oled`) reads `Frets 3-10` instead, the kind and the neck's end flashing there
  for about a second (`Step: Page`, `Neck end`).
- `neck` is a guitar layout's fretboard, or null: the strings highest first, each with its open note, letter and the
  channel it sends on, the number of frets, how many are on the pads, and `first`, the fret in column 1 (the window):
  `{"strings": [{"string": 1, "open": 64, "name": "E", "channel": 1}, …, {"string": 6, "open": 40, "name": "E",
  "channel": 6}], "frets": 24, "shown": 8, "first": 3}`.
- A generator parameter of kind `notes` (the guitar's `tuning`) takes one of its `choices` (presets) or a list of
  `min`–`max` notes; `definition.params` holds the preset's name or the list.
- `definition.scheme_params` holds the scheme's parameters as written (`{"scale": "dorian"}`); a scheme lists its
  `params` under `schemes` when it has any.
- `message` carries texts such as `Press Custom` (only when the request for Custom view could not be sent),
  `Custom view off` (the unit is in another view: its own button, or a view button on the page) and
  `lab session ended quietly (project view); nothing restored; session backup slot0-… kept`.
- `layouts` lists the generated layouts: `{layout, name, generator, valid: true}`, or `{layout, name, valid: false,
  error}` for a layout file whose `lab:` section does not compile (an unknown generator, a bad parameter), with
  its first error. Pushed again whenever the layout files change.
- Every activation asks the unit for Custom view while it is in another one, a switch within a running session
  included. The unit obeys and does not report it, so `unit_view` is `custom` as soon as the request was sent.
- `recovery` is `{backup, message}` when a session never ended cleanly. Restore that backup to slot 0, or dismiss
  it.
- `target.text` is `notes are only shown: no default target and no layout target` when nothing routes the notes.
- `warnings` lists start-up refusals, such as two plugins with one name.

The same JSON is pushed on `/ws` as `{"type": "topic", "topic": "lab", "data": {…, "kind": "lab"}}` after every
change. A page that connects gets the latest one at once.

### `POST /api/lab/validate {text, file}`

The layout text compiled with the lab section, ports checked; nothing is applied.

- `200 {"valid": true, "issues": [], "warnings": […], "summary": "valid: 1 page, 0 banks, 1 button, 1 encoder bound"}`
- `400 {"problem": "110 puts pad r8c8 at note 138", "fix": "the highest base is 99", "file": "tonnetz-c.yaml",
  "line": 3, "field": "base", "valid": false, "issues": [{"text": "tonnetz-c.yaml line 3, base: 110 puts pad r8c8 at note 138; the highest base is 99", …}]}`

Send the text, never a path: `{"path": …}` is refused.

### `POST /api/lab/activate {layout}`

The layout (file name or display name) loads at the host's single load point. A generated one starts a lab
session: one backup of slot 0, then the write at `Oct +0`, then a background backup of slots 1–24 (reused when
younger than 10 minutes). Loading a host layout ends the session and restores slot 0.

- `200 {"result": "activated", "message": "activated Tonnetz C"}`
- `404 {"problem": "no layout Tonetz C", "fix": "layouts: fourths, jam, tonnetz-c"}`

### `POST /api/lab/leave`

Ends the generated layout or preview and restores slot 0 from the session backup, when slot 0 still holds what
the lab wrote.

- `200 {"result": "restored", "message": "slot 0 restored; the unit shows the project as unsaved, nothing was saved"}`
- `{"result": "unchanged", "message": "no lab session is running; nothing written"}`

### `POST /api/lab/tweak {layout?, field, value}`

Changes one `lab:` field of the active generated layout, or of the named one. Fields: `base`, `scheme`, a
generator or scheme parameter (`scale`, `root`, the guitar's `tuning` preset or `frets`), or `colours.C`. The file changes by one spliced line and hot-reloads at the same window.

- `200 {"result": "saved", "message": "saved lab.base = D2; the layout reloads"}`
- `409 {"problem": "layout changed, reload"}`
- `409 {"problem": "no generated layout is active; activate one first"}`
- `400` with the layout issue, when the new value does not compile

The encoder and Tempo are the host's routes: `POST /api/control/encoder/move {"value": ±steps}`, and
`POST /api/control/tempo/press` then `/release`.

### `POST /api/lab/recovery/dismiss`

`200 {"result": "unchanged", "message": "recovery dismissed; slot0-… stays listed"}`, or `no recovery is pending`.

## Harmony

### `GET /api/lab/harmony`

```json
{"kind": "harmony", "held": [{"note": 48, "name": "C2", "pc": 0}, {"note": 52, "name": "E2", "pc": 4}, {"note": 55, "name": "G2", "pc": 7}],
 "chord": "C", "triads": [{"root": 0, "quality": "major", "label": "C", "display": "C"}], "degrees": {},
 "hints": [], "neighbours": [{"root": 0, "quality": "minor", "label": "Cm", "display": "Cm"},
                             {"root": 9, "quality": "minor", "label": "Am", "display": "Am"},
                             {"root": 4, "quality": "minor", "label": "Em", "display": "Em"}],
 "trail": ["C"], "trail_triads": [{"root": 0, "quality": "major", "label": "C", "display": "C"}], "circle": ["C", "G", "E"],
 "chord_root": 0, "chord_tones": [0, 4, 7],
 "played": [{"source": "custom", "channel": 1, "note": 48}, {"source": "custom", "channel": 1, "note": 52},
            {"source": "custom", "channel": 1, "note": 55}],
 "names": {"0": "C", "1": "D♭", "2": "D", "3": "E♭", "4": "E", "5": "F", "6": "G♭", "7": "G", "8": "A♭", "9": "A",
           "10": "B♭", "11": "B"}}
```

- Chords are written like MusicCat Explorer writes them (`C`, `Am`, `C/E`, `G7`, `Bm7♭5`, `F°`, `C+`), or as the held
  notes upwards from the bass when nothing matches (`C D♭ D`).
- **Spelling from context** (2026-10-27): the held notes, the chord and the trail are spelled from what is held. When
  the held notes form a chord, every held note is spelled in that chord (E major: `E G♯ B`; B♭ major: `B♭ D F`), its
  root with the fewest accidentals over the chord (`G♯m`, not `A♭m` with its C♭; `D♭`, not `C♯` with its E♯; a key
  that holds the root wins). Otherwise, when the active layout's colour scheme has a key (`scheme: scale`), the key's
  names; otherwise each note as its interval above the lowest held note (E + a major third: `G♯`). `names` gives all
  12 pitch classes as spelled now (C first, keyed by pitch class), for the views. `held[].name` carries the octave
  of the letter (C3 = 60; 59 spelled C♭ is `C♭3`, which only happens in a key that has C♭).
- **Readable spellings:** C♭, F♭, E♯, B♯ and double ♯/♭ are never produced unless the active key itself spells
  the note so (G♭ major's C♭); that note alone falls back to the fixed table: B F A♭ is `F°/B`, C°7's diminished
  seventh reads A.
- **Display vs lookup:** `circle`, the keys of `degrees` and each triad's `label` keep the fixed table
  `C C♯ D E♭ E F F♯ G A♭ A B♭ B`, so the views can look places up by them; each triad's `display` is its name as
  spelled now (with E major held the neighbours display `Em, C♯m, G♯m`, their labels `Em, C♯m, A♭m`), and the page
  shows lattice nodes and held circle keys by `names`.
- With one pitch class held, `degrees` labels every pitch class from it (`{"G": "♭3", "B": "5", …}`), and `hints`
  are the six triads that contain it.
- `chord` is `—` when nothing is held.
- `chord_root` and `chord_tones` are the named chord's root and its pitch classes (G7: `7`, `[7, 11, 2, 5]`), for the
  pad grid's rings; `null` and `[]` when no chord template matches (one note, two notes, a cluster).
- `played` is every held voice: its source (`custom`, `notes`, `input`), the channel it arrived on when the source is
  the APC64's Custom port (`null` otherwise) and its note. One pitch held on two strings of a guitar layout is two
  voices on two channels; the neck view puts each on its string.
- The trail (amended 2026-10-27) is the last 8 chords held: any chord the namer recognises (three or more pitch
  classes forming one of its chords; one note, an interval or an unnamed set is not a chord, so a two-note power
  chord is not an entry either). The same chord again in a row adds nothing (same root and quality: a new inversion
  or bass is not new). A chord that grows with nothing released in between replaces its own entry (C E G, then B:
  the entry becomes `Cmaj7`). `trail_triads` are the entries' major or minor triads (an entry without one, such as
  `Dsus4` or `F°`, is in `trail` only), so the Tonnetz and the circle draw the trail through triads.
- The JSON is pushed on `/ws` (kind `harmony`) for every note played.

### `POST /api/lab/harmony/trail/clear`

Empties the trail: `{"trail": [], "message": "trail cleared"}`. The new state is pushed on `/ws` at once.

### `GET /api/lab/harmony/inputs`, `POST /api/lab/harmony/inputs {inputs: [port, …]}`

The harmony views follow the APC64's Custom and Notes ports, plus any MIDI inputs chosen here. The choice is
remembered.

- `{"apc64": ["APC64 Custom", "APC64 Notes"], "inputs": ["Keystation 49 MIDI 1"], "message": "harmony follows the APC64 and Keystation 49 MIDI 1"}`
- `[]` follows the APC64 only: `harmony follows the APC64 only`.
- Each choice is also pushed on `/ws` (topic `lab`, kind `inputs`, the same JSON without `message`), so every open
  page ticks the same inputs.
- An APC64 port is refused: `APC64 Notes is the APC64's own port; the APC64's Custom and Notes ports are followed already`.

## Project memory

Every write to the unit runs the same way: read the slot, back it up, merge (unknown bytes kept), skip the write
if nothing changed, write, read back. A read-back that differs is rolled back from the backup.

### `GET /api/lab/slots/{n}`

Slot 0–24, read from the unit:
`{"slot": 7, "pads": [{"note", "aftertouch", "channel", "rest", "pressed", "outputs", "unknown"}, …64],
"strips": [{"resolution", "cc", "lsb", "channel", "bar", "indicator", "outputs", "bipolar", "unknown"}, …8], "raw": "0c 00 01 …"}`.
`502 {"problem": "slot 7 read returned 700 bytes, expected 880; nothing read"}`.

### `POST /api/lab/push {entry, slot, offset?}`

Stores a generated layout or a library entry in slot 1–24. A generated layout is stored where it sits on the
pads now; `offset` gives the window in semitones instead.

- `200 {"result": "pushed", "backup": "slot7-2026-10-24T20-15", "message": "pushed to slot 7; takes effect when project 7 is next loaded"}`
- `{"result": "unchanged", "message": "slot 7 unchanged; nothing written"}`
- `400 slot 25: slots are 1–24`
- `400 slot 0 is the live edit buffer; activate the layout to play it there`
- `502 could not back up slot 7; nothing written`
- `502 slot 7 read returned 700 bytes, expected 880; nothing written`
- `502 write to slot 7 failed, restored from backup`
- `502 slot 7 may be partial; restore slot7-2026-10-24T20-30`
- `409 busy: push to slot 5 in progress`
- `409 take control of the APC64 first; nothing read or written`
- `404 no layout or library entry "x"` (with `fix: "available: …"`)

### `POST /api/lab/preview {entry}`

Plays a captured or imported library entry live in slot 0, through a lab session with the same backup and
restore. A generated layout is activated.
`200 {"result": "activated", "message": "previewing Live set B in slot 0; leave to restore slot 0"}`.

### `POST /api/lab/backup {all: true}` or `{slot: 0–24 | "globals"}`

- `{all: true}`: `backed up slots 0–24 and the global settings as set-2026-10-24T20-15`. A slot that does not
  answer gives `502 backup set set-… is incomplete: slot 9 did not answer`.
- `{slot: 7}`: `backed up slot 7 as slot7-2026-10-24T20-15`, or `{"result": "unchanged", "message": "slot 7
  unchanged since slot7-2026-10-24T12-00; no new backup"}` (a backup equal to the newest is recorded once).

### `GET /api/lab/backups`

`{"backups": [{"id": "slot7-2026-10-24T20-15", "target": "slot7", "taken_at": "2026-10-24T20:15:00", "size": 880,
"sha256": "…"}, …], "sets": [{"id": "set-…", "taken_at": "…", "kind": "all"|"session", "complete": true,
"members": {"slot0": "slot0-…", …}}]}`.
A backup is named by its slot and the minute it was taken, with a `-2` suffix for a second one in the same
minute. Backups are never deleted.

### `POST /api/lab/restore {backup, slot}`

Restores one backup to one slot, after backing up what the slot holds now. There is no whole-set restore.

- `restored slot 7 from slot7-2026-10-24T12-00; takes effect when project 7 is next loaded`
- A slot-0 backup restores only to slot 0, and only while no session runs: `restored slot 0 from slot0-…; the unit
  shows the project as unsaved, nothing was saved`. That is also how a pending recovery is done.
- A globals backup restores with `slot: "globals"`: `restored the global settings from globals-…`.
- `422 slot7-2026-10-24T12-00 holds 512 bytes, expected 880; not restored`
- `404 no backup slot7-…`
- `400 slot 0 is restored only from a slot-0 backup, not slot7-…`

### `POST /api/lab/import {name?, data_base64, file?}`

An Akai Project Editor `.APC64` file goes into the library; nothing is written to the unit. Without `name`, the
file name is used.

- `200 {"result": "stored", "message": "imported \"Boss RC-600\" (64 pads, 8 strips); nothing written to the unit", "pads": 64, "strips": 8}`
- `400 580 items, expected 592`
- `400 item 341 ends past the end of the file at byte 4100`
- `409 name "Boss RC-600" is already in the library`

### `GET /api/lab/library`

`[{"name": "Tonnetz C", "kind": "definition", "layout": "tonnetz-c", "generator": "tonnetz"},
{"name": "Live set B", "kind": "captured", "source": "slot 12", "pads": 64, "strips": 8},
{"name": "Boss RC-600", "kind": "imported", "source": "Boss RC-600.APC64", …}, {"name": "x", "kind": "corrupt", "error": "…"}]`.
Generated layouts come from `layouts/`, and captured and imported entries from `library/`.

### `POST /api/lab/library/capture {slot, name}`

`saved slot 12 to the library as "Live set B"`, or `409 name "Live set B" is already in the library` (fix:
`choose another name`). Names are unique, ignoring case.

### `POST /api/lab/bulk-edit {target, edits: [text, …]}`

A validated edit of a stored project (slot 1–24), written through the guarded write path, or of a captured or
imported library entry, stored back. An edit is `<selection> <field> <value>`:

- **selections:** `all pads`, `pad r3c4`, `pads r1c1-r2c8`, `all strips`, `strip 3`, `strips 1-4`;
- **pad fields:** `channel`, `colour`, `pressed`, `aftertouch on|off`, `outputs`, `transpose ±n`;
- **strip fields:** `channel`, `bar`, `indicator`, `bipolar on|off`, `outputs`.

- `edited slot 5 (all pads channel 3); takes effect when project 5 is next loaded`
- `edited library entry "Live set B" (pads r1c1-r2c8 colour red); nothing written to the unit`
- `400 "Tonnetz C" is a generated layout` (fix: `edit its lab section, or push it to a slot and edit the slot`)
- A transpose that leaves 0–127 is refused, naming the worst pad.

## Global settings

### `GET /api/lab/globals`

`{"fields": [{"field": "device_mode", "label": "Device mode", "value": 0, "text": "Ableton Live", "hazard": true,
"options": [[0, "Ableton Live"], [1, "Standalone"]]}, …, {"field": "led_level", "label": "LED level", "value": 2,
"text": "75%", "hazard": false, "options": [[25, "25%"], [50, "50%"], [75, "75%"], [100, "100%"]]}], "raw": "01 00 …"}`.

The fields are `device_mode`, `standalone_sync`, `sync_out`, `cv1_source`…`cv8_source` (number and manual name,
`[TBD]`), `cv1_channel`…`cv8_channel`, `drum1_note`…`drum16_note` and `led_level`.

### `POST /api/lab/globals {changes: {field: value, …}, confirm?: true}`

One backup and one write for all the changes. Fields already at their value are left out.

- `set LED level 100% and CV2 channel 4`
- `LED level unchanged; nothing written`
- `400 device mode change needs confirmation: it changes how the unit starts; repeat the command with confirm`
  (also for `standalone_sync` and `sync_out`, which change the clock)
- `400 CV3 channel 17: channels are 1–16`
- `400 LED level 60%: levels are 25, 50, 75 or 100%`
- `400 no setting 'brightness'` (the fix lists the fields)

## The `apc64 lab` command

The command is mounted in `apc64` (also `python -m _apc64_host lab …`). Each command calls the route shown and
prints its `message`. A refusal prints the `problem`, then the `fix` when the problem does not already say it, on
stderr, and exits 1. `--json` prints the API's JSON instead. When the service is not running, every command says
`service not running on port 5058` and exits 2. The exception is `apc64 lab validate`: it then compiles the file
here and says `(ports not checked)`.

| command | API | example output |
|---|---|---|
| `apc64 lab list` | `GET /api/lab` | `generators:` / `  tonnetz  base 0–127 (default 48), channel 1–16 (default 1)` / … / `active: Tonnetz C  5th +2  (encoder: shift · Tempo: interval)` |
| `apc64 lab validate PATH` | `POST /api/lab/validate` | `valid: 1 page, 0 banks, 1 button, 1 encoder bound`, or one issue per line (exit 1) |
| `apc64 lab activate NAME` | `POST /api/lab/activate` | `activated Tonnetz C` |
| `apc64 lab leave` | `POST /api/lab/leave` | `slot 0 restored; the unit shows the project as unsaved, nothing was saved` |
| `apc64 lab tweak FIELD VALUE [--layout NAME]` | `POST /api/lab/tweak` | `saved lab.base = D2; the layout reloads` |
| `apc64 lab push ENTRY SLOT [--offset N]` | `POST /api/lab/push` | `pushed to slot 7; takes effect when project 7 is next loaded` |
| `apc64 lab preview ENTRY` | `POST /api/lab/preview` | `previewing Live set B in slot 0; leave to restore slot 0` |
| `apc64 lab backup [--all \| --slot N \| --globals]` | `POST /api/lab/backup` | `backed up slots 0–24 and the global settings as set-2026-10-24T20-15` (the default is `--all`) |
| `apc64 lab backups [--slot N]` | `GET /api/lab/backups` | `slot7-2026-10-24T20-15  slot7  880 bytes` |
| `apc64 lab restore BACKUP SLOT` | `POST /api/lab/restore` | `restored slot 7 from slot7-2026-10-24T12-00; takes effect when project 7 is next loaded` |
| `apc64 lab import NAME FILE` | `POST /api/lab/import` | `imported "Boss RC-600" (64 pads, 8 strips); nothing written to the unit` |
| `apc64 lab library` | `GET /api/lab/library` | `Live set B  captured from slot 12  64 pads, 8 strips` |
| `apc64 lab capture SLOT NAME` | `POST /api/lab/library/capture` | `saved slot 12 to the library as "Live set B"` |
| `apc64 lab bulk-edit TARGET EDIT [EDIT …]` | `POST /api/lab/bulk-edit` | `edited slot 5 (all pads channel 3); takes effect when project 5 is next loaded` |
| `apc64 lab globals` | `GET /api/lab/globals` | `LED level: 75%`, one line per field |
| `apc64 lab globals FIELD=VALUE … [--confirm]` | `POST /api/lab/globals` | `set LED level 100% and CV2 channel 4` / `CV3 channel 17: channels are 1–16` (exit 1) |
| `apc64 lab harmony` | `GET /api/lab/harmony` | `chord: C` / `held: C2 E2 G2` / `triads: C` / `neighbours: Cm, Am, Em` / `trail: C` / `circle of fifths: C – G – E` |
| `apc64 lab trail [clear]` | `GET /api/lab/harmony` / `POST /api/lab/harmony/trail/clear` | `trail: C → Am → Dsus4 → G7` / `trail cleared` |
| `apc64 lab inputs [PORT …] [--none]` | `GET`/`POST /api/lab/harmony/inputs` | `harmony follows the APC64 and Keystation 49 MIDI 1` |
| `apc64 lab slot N` | `GET /api/lab/slots/{n}` | `slot 7` / `  pad r1c1: note 48 ch 1 rest #FFFFFF pressed #FF0000 aftertouch` / … |
| `apc64 lab dismiss-recovery` | `POST /api/lab/recovery/dismiss` | `recovery dismissed; slot0-… stays listed` |

A typical agent session:

```sh
apc64 lab list                                   # what exists, what plays now
apc64 lab validate layouts/tonnetz-d.yaml        # fix every issue it prints; save it under layouts/
apc64 lab activate "Tonnetz D"                   # play it in Custom view; encoder/Tempo move the window
apc64 lab harmony                                # what is held
apc64 lab backup                                 # all 25 slots and the globals, before bigger work
apc64 lab push "Tonnetz D" 7                     # store it as project 7 (backed up first)
apc64 lab globals led_level=100                  # one backup, one write
```

## Configuration

These keys go in `config.local`, or the environment, next to the host's:

| key | default | meaning |
|---|---|---|
| `APC64_LAB_TARGET` | empty | the default note target for generated layouts: `<port> ch <1–16> [aftertouch pass\|pressure\|drop]`. A bad value stops the service at start, naming the key |
| `APC64_LAB_BACKUPS_DIR` | `backups` | unit-memory backups: dated raw files, git-ignored |
| `APC64_LAB_LIBRARY_DIR` | `library` | captured and imported projects (JSON; your own data, git-ignored here) |

With `--simulate`, the lab keeps its files under `<state dir>/simulated/`, so a simulated unit never mixes its
backups with the real one's.
