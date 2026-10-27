# Writing APC64 Lab generated layouts

A **generated layout** is an ordinary host layout file in `layouts/` with a `lab:` section. You don't list notes
and colours pad by pad. You name a **generator** (how the 64 pads are laid out) and a **colour scheme** (how they
are lit). The lab writes all 64 pads into the APC64's live edit buffer (slot 0). You then play them in the unit's
own **Custom view**, with real velocity and per-pad aftertouch.

Port names in the examples (`MPC Live III MIDI 1`, `Bitwig Studio In`, `USB MIDI Interface MIDI 1`) are
examples from the author's setup; use the names `apc64 ports` lists on your machine.

While a generated layout is active:

- The **encoder** shifts the window one step of the current interval (right +1, left −1).
- **Tempo** cycles the interval: octave → fifth → third.
- The OLED shows the layout name and the window, for example `Tonnetz C` / `5th +2`.
- **Shift + encoder** still browses and loads host layouts.

Every write to the unit is backed up first, and slot 0 is restored when you leave the layout.

The machine-readable schema is [`lab.schema.json`](lab.schema.json). The routes and commands are in
[`lab-api.md`](lab-api.md). The host's own keys (devices, pages, banks, routing) are in
[`layout-guide.md`](layout-guide.md).

Workflow for an agent:

```sh
apc64 lab list                              # generators, their parameters, colour schemes, the active layout
apc64 lab validate layouts/tonnetz-d.yaml   # fix every issue it prints (exit 1), then save it under layouts/
apc64 lab activate "Tonnetz D"              # written to slot 0 after one session backup
apc64 lab push "Tonnetz D" 7                # optional: store it in project 7, backed up first
```

## 1. The smallest generated layout

```yaml
name: Tonnetz C
lab:
  generator: tonnetz
```

This is the Tonnetz from note 48 (the default base) with the default `fifths` colour scheme. Without a note
target (section 5), what you play is shown in the harmony views but not sent anywhere.

## 2. Note numbers and names: C3 is 60

A note is either a **number** 0–127 or a **name** with an octave, where **C3 = 60**. This is the
Ableton/Akai/MPC convention the host uses everywhere.

| name | number |  | name | number |
|---|---|---|---|---|
| C1 | 36 |  | C3 | 60 |
| C2 | 48 |  | D3 | 62 |
| D2 | 50 |  | C4 | 72 |
| F#2 | 54 |  | Bb2 | 58 |

Write `#` or `b` for sharps and flats in note names (`F#2`, `Bb2`). If you are unsure, write the number:
`base: 50` is always D2. Pitch-class keys under `colours:` take no octave and also accept `♯`/`♭` (`C`, `F#`,
`B♭`).

## 3. The generators

`apc64 lab list` shows every generator and its parameters, including any added as plugins (section 8). The
shipped ones:

**`tonnetz`**: the Tonnetz on a staggered checkerboard.

- Only the pads where column + row is even play. The others are dark and silent.
- Two pads right is a fifth, up-right a major third, up-left a minor third down.
- Pad r1c1 (bottom left) plays `base`. Every triangle of three neighbouring lit pads is a major or minor triad.

| parameter | range | default | meaning |
|---|---|---|---|
| `base` | 0–99 (a note) | 48 | the note on pad r1c1. The top pad is base + 28, so 99 is the highest base |
| `channel` | 1–16 | 1 | the channel the unit sends the pads on (the note target can re-channel them, section 5) |

**`isomorphic`**: every pad lit. A fixed step per column and per row, so every interval has the same shape
everywhere.

| parameter | range | default | meaning |
|---|---|---|---|
| `base` | 0–127 (a note) | 36 | the note on pad r1c1 |
| `column` | −12–12 | 1 | semitones per column to the right |
| `row` | −12–12 | 5 | semitones per row upwards (5 = a fourth) |
| `channel` | 1–16 | 1 | as above |

Every pad must land in 0–127: the top-right pad is `base + 7·column + 7·row`. A definition that does not fit is
refused with the pad that falls out and the base that would fit (section 9).

The OLED shows 14 characters of the name, so keep names short (a longer one is cut, with a warning).

Common isomorphic layouts:

| layout | column | row |
|---|---|---|
| chromatic fourths (guitar/bass-like) | 1 | 5 |
| chromatic fifths | 1 | 7 |
| Wicki–Hayden-like (whole tones across, fourths up) | 2 | 5 |
| harmonic table-like (fifths across, minor thirds up) | 7 | 3 |

## 4. Colour schemes and colours

`scheme` picks how the pads are lit. Any scheme works with any generator.

| scheme | what it does |
|---|---|
| `fifths` (default) | the hue goes round the circle of fifths. C is white (pressed red), and other notes are white when pressed |
| `root-highlight` | the layout's root (the pitch class of `base`) is white, its major third and fifth orange, everything else dim blue |

`colours:` overrides the rest colour of any pitch class, on top of the scheme. A colour is `[r, g, b]` (each
0–255), `"#RRGGBB"` (quoted: `#` starts a YAML comment) or a name: `off`, `black`, `white`, `red`, `orange`,
`yellow`, `green`, `cyan`, `blue`, `purple`, `magenta`, `pink`.

```yaml
name: Tonnetz roots
lab:
  generator: tonnetz
  base: C2
  scheme: root-highlight
  colours:
    C: [255, 255, 255]
    G: "#00FF80"
    E: yellow
```

The page shows the RGB values as written to the unit. How the unit renders them is not calibrated.

## 5. Where the notes go: the default target and `routing: custom:`

The pads of a generated layout play in Custom view. In that view the unit sends notes, aftertouch and the strips'
CCs on its Custom port, and the host routes them like any Custom-view playing:

- **The lab's default target.** It is set once for every generated layout with `APC64_LAB_TARGET` in
  `config.local`, for example `APC64_LAB_TARGET=MPC Live III MIDI 1 ch 2 aftertouch pass`.
- **A layout's own target.** A `routing: custom:` line in the layout overrides the default. It needs a device
  declared under `devices:`, as in any host layout.
- **Neither.** The notes are only shown, and the panel says so.

The `ch` of the routing rule is the channel the target receives. To send to the MPC on channel 2:

```yaml
name: Tonnetz on D
devices:
  mpc: MPC Live III MIDI 1
lab:
  generator: tonnetz
  base: D2
routing:
  custom: mpc ch 2 aftertouch pass
```

The aftertouch rule is `pass` (poly aftertouch as played), `pressure` (turned into channel pressure) or `drop`.
Velocity always arrives untouched.

## 6. The strips (optional)

Without a `strips:` section, the unit's strips are written back exactly as they were. With one, the listed strips
are set up in the project record that is written to slot 0. Each entry is a strip number (`3`) or a range
(`1-4`). Over a range, `cc` (and `lsb`) rise by one per strip:

| key | value | default |
|---|---|---|
| `cc` | 0–127, required | |
| `lsb` | 0–127: the strip sends 14-bit MSB/LSB pairs | 7-bit |
| `channel` (or `ch`) | 1–16 | 1 |
| `bar`, `indicator` | colours | red, white |
| `bipolar` | true / false | false |
| `outputs` | 0–7 bitmask | 7 (all) |

```yaml
name: Fourths strips
lab:
  generator: isomorphic
  base: 36
  strips:
    1-4: {cc: 30, channel: 1, bar: blue}
    5-8: {cc: 40, lsb: 72, bar: green, bipolar: true}
```

Here strips 1–4 send CC 30–33, and strips 5–8 send 14-bit CC 40/72 to 43/75. In Custom view the strips' CCs go
to the same note target as the pads (section 5), on its channel.

## 7. Other controls in a lab layout

A lab layout is still a host layout. It may have pages and banks for the other buttons and strips, used in
Session view. The one rule: **don't bind `encoder` or `tempo` on a page.** The lab section owns them, and such a
line is refused:

```text
tonnetz-c.yaml line 8: the lab section shifts the window with the encoder; remove this encoder binding; Shift + encoder still browses layouts
```

Shift-layer bindings of other controls are fine:

```yaml
name: Tonnetz + MPC
devices:
  mpc: MPC Live III MIDI 1
lab:
  generator: tonnetz
  base: 48
pages:
  1 Transport:
    play: cc 118 on mpc ch 1
    stop: cc 117 on mpc ch 1
routing:
  custom: mpc ch 1 aftertouch pass
```

## 8. Adding a generator or a colour scheme

A new generator or scheme is **one file** in `_apc64_lab/generators/`, plus its test. Nothing else changes, and
it appears after a service restart in `apc64 lab list`, the API, the panel and the schema (regenerate it with
`python -m _apc64_lab.presentation.lab_schema`).

- A **generator** file exposes `GENERATOR`: an object with a `name` (lower-case letters, digits and `-`), a tuple
  of `params` (`ParamSpec`), and `notes(params)`. `notes(params)` returns 64 notes, pad r1c1 first and row by
  row; `None` means a silent pad.
- A **scheme** file exposes `SCHEME`: a `name` and `colour(note, root)`, which returns the `(rest, pressed)`
  colours.

```python
"""'wicki-hayden': whole tones to the right, fourths upwards (an isomorphic layout with fixed steps)."""
from _apc64_lab.domain.generators import CHANNEL_PARAM, ParamKind, ParamSpec


class WickiHayden:
    name = "wicki-hayden"
    params = (ParamSpec("base", ParamKind.NOTE, 36, 0, 127, "note on pad r1c1 (C3 = 60)"), CHANNEL_PARAM)

    def notes(self, params):
        return tuple(params["base"] + 2 * x + 5 * r for r in range(8) for x in range(8))


GENERATOR = WickiHayden()
```

- A plugin that fails is listed as broken with its error, and never used.
- Two files with the same name: the second is refused at start, and the start-up message names both files.
- Plugins import only the standard library and `_apc64_lab.domain`.

## 9. Errors

Every error names the file, the line, the field, what is wrong and how to fix it. `apc64 lab validate`, the API
and the page show the same text:

```text
tonnetz-c.yaml line 3, base: 110 puts pad r8c8 at note 138; the highest base is 99
tonnetz-c.yaml line 3: no generator "tonetz"; available: isomorphic, tonnetz
tonnetz-c.yaml line 4: no colour scheme "rainbow"; available: fifths, root-highlight
tonnetz-c.yaml line 6, colour C: 300 is outside 0–255; write each of red, green and blue as 0–255
tonnetz-c.yaml line 4: unknown key 'colour'; the lab section takes generator, scheme, colours, strips and the tonnetz parameters: base, channel
tonnetz-c.yaml line 5, strip 9: no such strip; strips are 1–8, e.g. '3' or '1-8'
tonnetz-c.yaml line 5, strip 1-4: a strip takes cc, lsb, channel, bar, indicator, bipolar, outputs; write e.g. '{cc: 20, channel: 1, bar: red}'
tonnetz-c.yaml line 2: the lab section names no generator; add 'generator: <name>'; available: isomorphic, tonnetz
```

**Common mistakes**

| wrong | right |
|---|---|
| `base: C3` meaning 48 | `base: C2` or `base: 48`: C3 is 60 |
| `generator: Tonnetz` | `generator: tonnetz`: names are lower case |
| `colour:` / `color:` | `colours:` (pitch class → colour) |
| `channel: 2` to reach the MPC on channel 2 | `routing: custom: mpc ch 2`. The parameter is what the unit sends; the routing decides what arrives |
| `strips: {1-4: cc 20}` | `strips:` then `1-4: {cc: 20}`: each strip entry is a mapping |
| `strip 1: cc 20` under `banks:` to set up the unit's strips | the lab `strips:` section (banks bind strips in Session view) |
| `encoder: …` on a page of a lab layout | leave the encoder and tempo to the lab section |
| `G: #00FF80` | `G: "#00FF80"`: quote it, or YAML reads a comment |
| the lab section written inline (`lab: {generator: tonnetz}`) | valid, but write it as an indented block: page tweaks splice one line of it and refuse an inline section |

## 10. Worked examples

`layouts/tonnetz-c.yaml`, the Tonnetz from C to the MPC on channel 1:

```yaml
name: Tonnetz C
devices:
  mpc: MPC Live III MIDI 1
lab:
  generator: tonnetz
  base: 48
  scheme: fifths
routing:
  custom: mpc ch 1 aftertouch pass
```

Pad r1c1 plays 48 and is white, r1c3 plays 55 (G), r2c2 52 (E), and r1c2 and r2c1 are dark. One encoder detent
right on the octave interval plays 60 on r1c1. Tempo then gives the fifth (+7 per detent) and the third (+4).

`layouts/fourths.yaml`, chromatic fourths with every pad lit, played into the lab's default target:

```yaml
name: Fourths
lab:
  generator: isomorphic
  base: 36
  column: 1
  row: 5
  scheme: fifths
```

Pad r1c1 plays 36, r1c2 37, r2c1 41 and r8c8 78. Pads of the same pitch class share a colour.

A harmonic-table-like layout on Bitwig, channel 3, with 14-bit strips:

```yaml
name: Harmonic table
devices:
  bitwig: Bitwig Studio In
lab:
  generator: isomorphic
  base: 41
  column: 7
  row: 3
  scheme: root-highlight
  strips:
    1-8: {cc: 20, lsb: 52, channel: 3}
routing:
  custom: bitwig ch 3 aftertouch pressure
```

The highest pad is 41 + 49 + 21 = 111, which fits in 0–127.

## 11. From the page

The **Lab** choice beside the surface shows:

- the generated layouts, generators and schemes;
- the active layout, with its window and `encoder: shift · Tempo: interval`;
- the encoder and Tempo buttons, and Leave;
- the base and scheme tweaks: one line of the file, which hot-reloads at the same window;
- the harmony views and their input choice;
- the 24 slots, the backups and the library: push, preview, back up, restore, capture and import;
- the global settings. A device-mode or sync change asks for the confirmation the service requires.

Bulk edits (`apc64 lab bulk-edit 5 "all pads channel 3"`) are made by the agent. The page shows their results:
read the slot, or open the library.
