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
- A generator may bring its own steps instead: the guitar moves by **Fret** or **Page** (Tempo toggles them) and
  the OLED shows the frets on the pads, `Guitar` / `Frets 3-10` (section 3).
- **Shift + encoder** still browses and loads host layouts.
- With a performer (section 12), **Play** toggles the latch and **Stop** stops the pattern.

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

Common isomorphic layouts (the ones with a file ship in `layouts/`, section 10):

| layout | column | row | file |
|---|---|---|---|
| chromatic fourths (guitar/bass-like) | 1 | 5 | `fourths.yaml` |
| chromatic fifths | 1 | 7 | |
| thirds grid: every 2×2 block a major and a minor triad | 4 | 3 | `thirds-grid.yaml` |
| Wicki–Hayden, square approximation (whole tones across, fourths up) | 2 | 5 | `wicki-hayden.yaml` |
| Janko (whole tones across, a semitone up) | 2 | 1 | `janko.yaml` |
| fifths grid: a row runs round the circle of fifths | 7 | 1 | `fifths-grid.yaml` |
| harmonic table-like (fifths across, minor thirds up) | 7 | 3 | |

The Wicki–Hayden keyboard is hexagonal: each row is offset half a key, the fifth is up-right and the fourth
up-left. On the square grid the fifth stays up-right but the fourth is straight up, so it is an approximation;
every scale and chord still has one shape in every key.

**`modes`**: the modes explorer. Rows 1–7, bottom to top, are the seven parallel modes of one root in the order of
the major scale's modes: Ionian, Dorian, Phrygian, Lydian, Mixolydian, Aeolian, Locrian. Each row plays its mode
from the root (column 1) to the octave (column 8), so a column is one scale degree in every mode. Row 8 is dark.

- The notes where a mode differs from Ionian (the major scale) keep the scheme's full colour: Dorian's ♭3 and ♭7,
  Lydian's ♯4, Locrian's ♭2 ♭3 ♭5 ♭6 ♭7. The root and the octave are white (pressed red); the notes a mode shares
  with Ionian are the scheme's colour, dimmed (so Ionian's row is dimmed but for its root and octave).
- **Its own window: the key.** The encoder moves the key, the root of every row: by a **Semitone**, or after Tempo
  by a **Fifth** (round the circle of fifths: C G D A …). The twelve keys go round: a step up from B comes back to C
  (an octave lower, so the pads stay near the base). The OLED's row 2 names the key, `Key Db`; Tempo flashes `Step:
  Fifth` or `Step: Semitone`. The colours follow the key (the pads look the same in every key) and the page spells
  each row in its mode of the key from the key's root as the key is named (C, D♭, D, E♭, E, F, G♭, G, A♭, A, B♭,
  B), each letter once, whatever accidentals that takes: every row starts on the same name (E♭ Phrygian: E♭ F♭ G♭
  A♭ B♭ C♭ D♭; E♭ Locrian: E♭ F♭ G♭ A♭ B𝄫 C♭ D♭). The key's own name never needs a double accidental (the OLED's `Key Gb` is G♭).
- The page names the rows (Ionian … Locrian).

| parameter | range | default | meaning |
|---|---|---|---|
| `base` | 0–115 (a note) | 48 | the root: pad r1c1 and every row's first pad. The top pad is base + 12 |
| `channel` | 1–16 | 1 | as above |

```yaml
name: Modes D
lab:
  generator: modes
  base: D2
  scheme: fifths
```

Here every row starts on 50 (D2): the bottom row plays D Ionian, D E F♯ G A B C♯ D, and the Dorian row (row 2)
D E F G A B C D, with its F and C (the notes it lowers from Ionian) at full colour in columns 3 and 7. Five encoder
detents right show `Key G`; Tempo, then one detent right, `Key D` again (G up a fifth).

**`guitar`**: a guitar (or bass) neck. Rows are strings, columns are frets.

- The highest string is on the top used row, the lowest on the bottom one. 8 strings use rows 1–8 and 7 strings
  rows 1–7 (the extra low string takes the bottom row); 6 or fewer start at row 2, so 6 strings are rows 2–7 and a
  4-string bass rows 2–5. The rows left over are silent (kept free for a later step: chord types and patterns).
- Column 1 is the fret the window shows first. At the start that is fret 0, the open strings, so the pads show
  frets 0–7 and a pad plays its string's open note + its fret.
- Every place of a note shares its colour with the default `fifths` scheme: the unit cannot highlight the other
  places of a played note (in Custom view it ignores the host's LED messages), so the colour does it. `scale` and
  the other schemes work as on any layout; the layout's root (the `scale` scheme's default root) is the lowest
  string's note.
- The rows are named by string number and letter (`6 E` … `1 E`) on the page.

| parameter | value | default | meaning |
|---|---|---|---|
| `tuning` | a preset below, or a list of 4–8 notes | `e-standard` | the open strings, **low to high** |
| `frets` | 12–36 | 24 | the neck's length |

The presets, as MIDI numbers low to high (any case, and spaces for `-`, are accepted: `Drop D`):

| strings | presets |
|---|---|
| 6 | `e-standard` 40 45 50 55 59 64, `drop-d` 38 45 50 55 59 64, `eb-standard` 39 44 49 54 58 63, `d-standard` 38 43 48 53 57 62, `drop-c` 36 43 48 53 57 62, `dadgad` 38 45 50 55 57 62, `open-g` 38 43 50 55 59 62, `open-d` 38 45 50 54 57 62 |
| 7 | `b-standard-7` 35 40 45 50 55 59 64, `drop-a-7` 33 40 45 50 55 59 64 |
| 8 | `fs-standard-8` 30 35 40 45 50 55 59 64, `drop-e-8` 28 35 40 45 50 55 59 64 |
| bass | `bass-4` 28 33 38 43, `bass-5` 23 28 33 38 43 |

A tuning of your own is a list, low to high, of numbers or names. **Mind the octave numbers:** this project names
C3 = 60 (section 2), so a guitar's low E, MIDI 40, is **E1** here (many guitar books call it E2), and E standard is
`[E1, A1, D2, G2, B2, E3]`. Numbers are never ambiguous: `[40, 45, 50, 55, 59, 64]`.

```yaml
name: Guitar Drop D
lab:
  generator: guitar
  tuning: drop-d
  frets: 22
  fret_marks: off      # every pad in its scheme colour (default on: the inlay frets marked)
```

```yaml
name: Bass EADG
lab:
  generator: guitar
  tuning: [E0, A0, D1, G1]
  scheme: scale
  scale: minor-pentatonic
```

**One MIDI channel per string.** String 1 (the highest) sends on channel 1, string 2 on channel 2, and so on (a
6-string's low E on channel 6). In Custom view the unit sends only a note and its channel, so without this the low
E's fret 5 and the open A (both 45) would be the same message, and the page could not tell which string you
played. The routing rule still decides what arrives (section 5): every string reaches the target on the rule's
channel. Two strings playing one pitch reach a one-channel target as two note-ons of the same note; the first
note-off ends it there (MIDI cannot tell them apart).

**The window: Fret and Page.** The window's position is the fret in column 1; the pads show that fret and the 7
above it, from 0 (frets 0–7) to `frets` − 7 (17 for 24 frets: frets 17–24).

- **Fret**: each encoder detent moves one fret (one semitone).
- **Page**: each detent moves to the next or previous page position: the multiples of 8 below the end of the neck,
  then the end itself. For 24 frets that is 0, 8, 16, 17 (frets 0–7, 8–15, 16–23, then 17–24). From fret 3 a page
  down goes to 0, from 17 to 16, and from 16 a page up to 17.
- **The OLED's row 2 always reads the frets on the pads**, `Frets 8-15` (up to `Frets 29-36`), whichever step is
  current. The page's window line keeps showing the step kind (`Page 8-15 · steps Fret / Page`).
- **Tempo** toggles Fret ↔ Page; the position stays. Every activation starts at Fret, fret 0. Row 2 flashes the new
  kind, `Step: Page` or `Step: Fret`, for about a second, then reads the frets again.
- A step past either end is refused: the window stays and row 2 flashes `Neck end` for about a second. Several
  detents in one turn are taken or refused together, and a step that would put a pad outside 0–127 is refused the
  same way. A newer step or toggle ends a flash at once.
- A tuning or `frets` change from the page reloads at the same fret while the new neck still has it.
- **Fret marks.** The pad columns on the inlay frets, 3, 5, 7, 9, 15, 17, 19, 21 (and 27–33 on a long neck), keep
  the scheme's full colour, and the other columns are shaded (their colour at 45 %; a colour already dark, such as
  `scale`'s notes outside the scale, stays as it is), so the inlays read on the unit like dots on a neck. 12, 24
  and 36, the double inlays, are lifted toward white. The marks move with the window, since the pads are rewritten
  at each step; pressed colours are unchanged. `fret_marks: off` (or `false`) turns them off.
- `push` stores the layout at the current window (the transposition is the fret number in semitones).

**On the page** the Harmony main view of a guitar layout is the neck (section 11).

## 4. Colour schemes and colours

`scheme` picks how the pads are lit. Any scheme works with any generator.

| scheme | what it does |
|---|---|
| `fifths` (default) | the hue goes round the circle of fifths. C is white (pressed red), and other notes are white when pressed |
| `root-highlight` | the layout's root (the pitch class of `base`) is white, its major third and fifth orange, everything else dim blue |
| `scale` | a scale overlay: the scale's root white (pressed red), its other notes in the `fifths` hue, every note outside it dim but lit |

**The `scale` scheme** works with any generator. It takes two parameters, written in the lab section like a
generator's:

| parameter | value | default | meaning |
|---|---|---|---|
| `scale` | a scale name from the table below | `major` | the scale lit. Any case, and spaces for `-`, are accepted (`Harmonic Minor`) |
| `root` | a note name without octave (`D`, `F#`, `B♭`) | the layout's root | the scale's root; without it, the pitch class of `base` |

The outside notes stay lit (dim blue-grey), so the layout's geometry stays readable. The page dims their names too
and spells the scale's notes in its key (D harmonic minor has C♯, not D♭).

```yaml
name: D Dorian 4ths
lab:
  generator: isomorphic
  base: D1
  column: 1
  row: 5
  scheme: scale
  scale: dorian
```

```yaml
name: Janko A minor
lab:
  generator: isomorphic
  base: 48
  column: 2
  row: 1
  scheme: scale
  scale: harmonic-minor
  root: A
```

The scales (from the harmony core's library; `apc64 lab list` lists them). The first group is the APC64 Note
view's own; Akai does not publish the notes of its "Flamenco" and "Hungarian", so the library defines its own
under unambiguous names and does not claim they are the unit's.

| group | scales |
|---|---|
| the Note view's own | `chromatic`, `major`, `melodic-minor` (ascending), `harmonic-minor`, `major-pentatonic`, `minor-pentatonic`, `dorian`, `phrygian`, `lydian`, `mixolydian`, `aeolian`, `locrian`, `blues` (1 ♭3 4 ♭5 5 ♭7), `whole-tone` |
| the library's own | `flamenco` (1 ♭2 ♭3 3 4 5 ♭6 ♭7), `hungarian-minor` (1 2 ♭3 ♯4 5 ♭6 7), `hungarian-major` (1 ♯2 3 ♯4 5 6 ♭7) |
| major and minor variants | `harmonic-major`, `double-harmonic` (Byzantine), `neapolitan-major`, `neapolitan-minor`, `phrygian-dominant` |
| melodic minor's modes | `dorian-b2`, `lydian-augmented`, `lydian-dominant`, `mixolydian-b6`, `locrian-natural2`, `altered` |
| symmetric and bebop | `octatonic-half-whole`, `octatonic-whole-half`, `bebop-dominant`, `bebop-major` |
| pentatonic and others | `hirajoshi`, `in` (Sakura), `iwato`, `prometheus`, `enigmatic` |

Aliases are accepted too: `ionian`, `minor` and `natural-minor`, `super-locrian`, `byzantine`, `sakura`,
`jazz-minor`, `spanish`. A scale parameter written without `scheme: scale` is a warning (it is unused), so switching
the scheme on the page keeps the file valid.

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
- Optional, as the shipped `modes`, `guitar` and `scale` plugins use them: a generator's `marks(params)` (64 of
  `"root"`, `"accent"`, `"dim"` or `None`), `row_labels(params)` (8 names, bottom first) and `pad_names(params,
  transposition)`; a scheme's `params` with `configured(values)` (the scheme bound to them) and, on the bound
  scheme, `overlay(root)` (the scale the page dims by).
- Also optional (the `guitar` plugin): `channels(params)` (64 channels 1–16, or `None` for the `channel` parameter,
  r1c1 first: pads on channels of their own), `root(params)` (the layout's root pitch class when it is not
  `base`'s), `window(params)` (a `WindowSpec` from `_apc64_lab.domain.window`: the generator's own step kinds and
  transposition range instead of octave / fifth / third) and `neck(params)` (a `Neck` the page draws as a
  fretboard). A parameter of kind `ParamKind.NOTE_LIST` takes a preset name from its `choices` or a list of
  `minimum`–`maximum` notes.

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
tonnetz-c.yaml line 3: no generator "tonetz"; available: guitar, isomorphic, modes, tonnetz
tonnetz-c.yaml line 4: no colour scheme "rainbow"; available: fifths, root-highlight, scale
tonnetz-c.yaml line 6, colour C: 300 is outside 0–255; write each of red, green and blue as 0–255
tonnetz-c.yaml line 4: unknown key 'colour'; the lab section takes generator, scheme, colours, strips, performer and the tonnetz parameters: base, channel
tonnetz-c.yaml line 5, strip 9: no such strip; strips are 1–8, e.g. '3' or '1-8'
tonnetz-c.yaml line 5, strip 1-4: a strip takes cc, lsb, channel, bar, indicator, bipolar, outputs; write e.g. '{cc: 20, channel: 1, bar: red}'
tonnetz-c.yaml line 2: the lab section names no generator; add 'generator: <name>'; available: guitar, isomorphic, modes, tonnetz
tonnetz-c.yaml line 5, root: 'H' is not a note name; write C, C♯ (or C#), D♭ (or Db) … B, without an octave
```

A guitar layout's tuning and frets are refused the same way:

```text
guitar.yaml line 4, tuning: 3 notes; write 4 to 8 notes, low to high, or one of: e-standard, drop-d, eb-standard, d-standard, drop-c, dadgad, open-g, open-d, b-standard-7, drop-a-7, fs-standard-8, drop-e-8, bass-4, bass-5
guitar.yaml line 4, tuning: note 2: 'H1' is not a note; write a number 0–127 or a name like C1 (36), F#2 or Bb3 (C3 = 60)
guitar.yaml line 4: no tuning "drop-f"; did you mean drop-d? available: e-standard, drop-d, eb-standard, d-standard, drop-c, dadgad, open-g, open-d, b-standard-7, drop-a-7, fs-standard-8, drop-e-8, bass-4, bass-5
guitar.yaml line 5, frets: 40 is outside 12–36; frets is 12–36
```

A misspelt scale names the nearest one, then every scale: `no scale "dorain"; did you mean dorian? available:
chromatic, major, …`.

**Common mistakes**

| wrong | right |
|---|---|
| `base: C3` meaning 48 | `base: C2` or `base: 48`: C3 is 60 |
| `generator: Tonnetz` | `generator: tonnetz`: names are lower case |
| `colour:` / `color:` | `colours:` (pitch class → colour) |
| `tuning: [E2, A2, D3, G3, B3, E4]` for a guitar in E standard | `[E1, A1, D2, G2, B2, E3]` or `[40, 45, 50, 55, 59, 64]`: C3 is 60 |
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

`layouts/thirds-grid.yaml`, a major third per column and a minor third per row:

```yaml
name: Thirds grid
lab:
  generator: isomorphic
  base: 36
  column: 4
  row: 3
  scheme: fifths
```

Pad r1c1 plays 36 (C), r1c2 40 (E), r2c1 39 (E♭) and r2c2 43 (G): the block's bottom row with the pad up-right is C
major, its left column with that pad C minor. Every 2×2 block holds both triads of its bottom-left note. The top
pad is 36 + 28 + 21 = 85.

`layouts/wicki-hayden.yaml` (column 2, row 5, from 36: up to 85) and `layouts/janko.yaml` (column 2, row 1, from 48:
up to 69, each note again two rows up and one column left) follow the table in section 3.

`layouts/fifths-grid.yaml`, a fifth per column and a semitone per row:

```yaml
name: Fifths grid
lab:
  generator: isomorphic
  base: 36
  column: 7
  row: 1
  scheme: fifths
```

Row 1 plays C G D A E B F♯ C♯ (36, 43 … 85), and each row up is the same a semitone higher, so neighbouring keys
sit side by side and a key's IV, I and V are three pads in a row. A semitone per row (rather than two) keeps the
range playable: 36 to 92.

`layouts/modes-c.yaml`, the modes explorer from C2:

```yaml
name: Modes
lab:
  generator: modes
  base: 48
  scheme: fifths
```

Row 1 plays C Ionian (48 50 52 53 55 57 59 60), row 4 C Lydian with its F♯ (column 4) at full colour, row 7 C
Locrian (48 49 51 53 54 56 58 60); row 8 is dark. The OLED reads `Key C`; one detent right, `Key Db`, and every row
starts on 49.

`layouts/guitar.yaml`, a 6-string neck in E standard:

```yaml
name: Guitar
lab:
  generator: guitar
  tuning: e-standard
  frets: 24
  scheme: fifths
```

Row 2 is the low E: r2c1 plays 40 and r2c6 45, the same note as r3c1, the open A, and in the same hue (column 6 is
fret 5, an inlay: full colour; column 1, the open string, is shaded). Row 7 is the high E (64 to 71); rows 1 and 8
are dark. r7c1 sends on channel 1 and r2c1 on channel 6. Two encoder detents right show frets 2–9 (`Frets 2-9`,
r2c1 plays 42); Tempo (`Step: Page` for a second), then one detent right: `Frets 8-15`.
`layouts/guitar-7.yaml` (B standard, rows 1–7 from 35) and `layouts/guitar-8.yaml` (F♯ standard, all 8 rows from 30)
are the same with more strings.

## 11. From the page

The **Lab** choice beside the surface shows:

- the generated layouts, generators and schemes;
- the active layout, with its window and what the encoder and Tempo do there (`encoder: shift · Tempo: interval`,
  or a guitar layout's `encoder: one fret · Tempo: Fret ↔ Page`);
- the encoder and Tempo buttons, and Leave;
- the base, tuning (a guitar layout's presets) and scheme tweaks: one line of the file, which hot-reloads at the
  same window;
- the performer (section 12): on/off, pattern, play mode, latch, tempo or clock, Stop, the pattern as a grid;
- the harmony views and their input choice;
- the 24 slots, the backups and the library: push, preview, back up, restore, capture and import;
- the global settings. A device-mode or sync change asks for the confirmation the service requires.

**The harmony views follow the active layout.** The main view is the Tonnetz for a `tonnetz` layout and, for every
other layout (isomorphic, modes, a plugin, a library preview, a plain host layout), the 64 pads in the layout's own
8×8 shape: each in the colour written to the unit with its note's name, the held notes lit, the chord's tones ringed
and its root dotted, the notes outside a `scale` overlay dimmed, and the modes explorer's row names beside the rows.
A host layout shows the pads it binds to notes, in the host replica's approximate colours; one that binds none says
so. Beside the Tonnetz the small pad replica stays. The circle of fifths is always there: the major keys outside,
their relative minors inside (C/Am … F♯·G♭/D♯m·E♭m … F/Dm); the held notes light and are joined, a held major triad
lights its key outside and a minor triad its key inside, and the trail runs through the keys.

**The chord, its spelling and the trail.** The chord row names what is held and lists the held notes, spelled from
their context: in the chord they form (E major: `E G♯ B`; B♭ major: `B♭ D F`; G♯ minor rather than A♭ minor with its
C♭; never C♭, F♭, E♯, B♯ or a double ♯/♭ unless the key needs it, so B F A♭ reads `F°/B`), else in the layout's
key when its scheme is `scale`, else as intervals above the lowest note (E and the note a
major third up: `E G♯`). The neck, the lattice, the hints and the held keys on the circle show the same spelling. The **trail** below it is the last 8 chords
you held, any chord with a name (a triad, a seventh, sus, °, +; one note or an interval is not a chord): the same
chord again adds nothing, and a chord that grows while you hold it replaces its own entry (C, then + B: `Cmaj7`).
**Clear** beside it empties it (also `apc64 lab trail clear`). On the Tonnetz and the circle the trail runs through
each chord's major or minor triad; a chord without one (`Dsus4`, `F°`) shows in the text only.

**A guitar layout's main view is its neck**: a horizontal fretboard with the nut on the left, every fret to the end
of the neck (spaced like a real neck, narrowing toward the body but kept readable), the inlays, the strings as on the
unit (the highest on top, lower strings thicker) and their letters at the nut. A box marks the frets the pads show
and moves with the window. A note you play is a solid dot with its name on the string and fret you played it on
(known from the string's channel); every other place of that pitch on the neck is a ring, and a note from another
input (which has no string) is a ring at all its places. Nothing moves while notes come and go. The small pad
replica stays beside it.

**Full view.** The two small buttons on the Harmony heading show the harmony views alone, large, across the
whole screen: the main view and the circle of fifths side by side, the chord and its trail big above them, the hints
below (a tall or narrow screen stacks them and scrolls). **Main: Auto / Tonnetz / Pads** in its heading (and
**Neck** for a guitar layout) overrides the main view there; the choice is remembered in this browser (Auto by
default). With the neck shown, **Left-handed** draws it with the nut on the right (this page only; remembered in this
browser too). **Full screen** does it in the same page (Esc or Leave goes back). **New tab** opens the page's address with `?view=harmony`, e.g. `http://<this machine>:5058/?view=harmony`:
bookmark it, or open it on a tablet or a second screen on the network. Both stay live and show the input choice.

Bulk edits (`apc64 lab bulk-edit 5 "all pads channel 3"`) are made by the agent. The page shows their results:
read the slot, or open the library.

## 12. The performer: patterns over what you hold

A generated layout can carry a **performer**: a pattern that plays automatic strumming or fingerpicking over the
notes you hold. The pattern starts the moment you press a note, so you time the chord changes; the notes go to the
layout's note target (section 5), like the pads. The format of a pattern, and the exact rules, are in
[`performer-format.md`](performer-format.md); the patterns live in `patterns/`.

```yaml
name: Guitar picker
lab:
  generator: guitar
  tuning: e-standard
  performer:
    pattern: arpeggio-manual-bass   # a file in patterns/ (its name without .yaml) or the pattern's name
    latch: off                      # on: the last chord keeps playing after you let go
    tempo: 96                       # BPM, quarter notes a minute
```

`layouts/guitar-picker.yaml` is this layout. The block's keys:

| key | value | default | meaning |
|---|---|---|---|
| `pattern` | a pattern's file name or name, required | | what plays |
| `latch` | `on`, `off` | `off` | releasing keeps the last held notes playing until Stop or a new chord |
| `play` | `all`, `pressed` | the pattern's | `all`: every string plays at its hits, one you do not press rings open; `pressed`: only pressed strings play |
| `tempo` | 20–300, or `clock` | 100 | the speed in BPM, or the MIDI clock of `clock` |
| `clock` | a MIDI input, as `apc64 ports` lists it, or `auto` | | with `tempo: clock`: the input that sends the clock (the MPC can); `auto` follows the first input that sends one |
| `addressing` | `strings`, `voices` | `strings` for the guitar, else `voices` | how lanes map to what is held |

**Strings are lanes.** The guitar sends each string on its own channel (section 3), so the performer knows which
string a note is on: lane 1 of a pattern is string 1 (the high E), lane 6 the low E. On other layouts lane 1 is the
highest note you hold, lane 2 the next (`voices`); `addressing: strings` there is refused.

**Play: all or pressed.** With `all` (the default) every string plays at its hits, and a string you do not press
rings open, as on a guitar: an open A minor (x02210) presses only three strings, yet a 5-3-2-1 arpeggio plays four
notes, the A string open. With `pressed` only the strings you press play. Either way the timing never moves: a
missing note leaves its step silent. Pressing starts the pattern and letting go of everything stops it one step later
(an open string is not a press); that last step plays nothing, so an ending never rings the open strings. Letting go
of a chord string by string rings nothing open either; a single finger lifted from a chord you keep holding (C →
Cmaj7) rings its open string from the next hit after about a tenth of a second.

**Manual strings.** A pattern may leave strings to you (`manual: [4, 5, 6]`): what you press there passes straight
through, as played, with its aftertouch. With `arpeggio-manual-bass`, hold A minor on strings 1-3 and play an
alternating bass by hand on strings 5 and 6: 5 + 123, 6 + 123 …; change to C and play 5 + 123, 4 + 123. The 1-2-3
pattern goes on over the new notes without restarting.

**On the unit.** In Custom view only Shift, Tempo, Play, Stop and the encoder reach the host. With a performer block,
**Play** toggles the latch and **Stop** stops the pattern at once, all its notes off; the OLED's row 2 says so for a
second (`Latch on`, `Latch off`, `Stopped`; the pattern's name when it changes). The encoder and Tempo stay the
window (frets and pages). Because the section owns Play and Stop then, a page binding of `play` or `stop` is refused:

```text
guitar-picker.yaml line 10, play: the lab section's performer toggles the latch with Play; remove this play binding, or the performer block
```

**On the page.** The Lab panel's **Performer** section, under the active layout: On/Off, the pattern, the play mode,
Latch, Stop, the tempo in BPM (it applies as you type or click its arrows; no Set button) or the clock of an input
(with the tempo it measures and what the clock is doing), and the pattern as a grid, a row
per string (manual strings marked), the playing step lit. A choice there lasts for the session; the layout file's
block sets them again at the next activation. On a generated layout without a block, On turns a performer on for
the session; the unit's Play and Stop then stay unbound. `apc64 lab performer …` does the same from the command line
([`lab-api.md`](lab-api.md)).

**What the harmony views show.** What you hold, as without the performer (the chord, the trail, the dots on the neck),
not the notes the pattern plays. The replica's played-notes row shows what sounds.

**Tempo from the MPC.** `tempo: clock` and `clock: <the MPC's port>` follow its MIDI clock (24 ticks a quarter
note): the clock sets the speed, the pattern still starts when you press (it is not locked to the MPC's bars).
`clock: auto` (or **auto** in the page's clock list) listens to every input and follows the first that sends a
clock, so you need not know which of the MPC's ports carries it. The MPC sends its clock **only while its sequencer
plays**, and only to the outputs its sync settings send clock to: turn on MIDI clock output there and press Play on
the MPC. The page says what it hears: `no clock heard from MPC Live III MIDI 1 yet …`, `following MPC Live III MIDI
1: 98.0 BPM`, and when the MPC stops, `the clock stopped; keeping 98.0 BPM` (the pattern goes on at that tempo). It
also names the other inputs a clock was heard from lately, which helps when trying the ports one by one. The tempo is
measured over four beats and held, so a clock jittering over USB reads steady (125.0, not 124.6 … 125.4); a real
tempo change is followed within about a beat.

**Writing a pattern.** One file in `patterns/`, checked with `apc64 lab validate-pattern patterns/my-pick.yaml`:

```text
my-pick.yaml line 9, lane 2: 7 steps; length is 8; write one cell per step: . (rest), x (hit) or X (accent); spaces and | are ignored
```

A wrong block in the layout is refused at its line like any lab field:

```text
guitar-picker.yaml line 6: no pattern "travs"; did you mean travis? available: arpeggio, arpeggio-manual-bass, strum, travis, waltz
guitar-picker.yaml line 7: '400' is not a tempo; write a BPM 20–300 (quarter notes a minute), or 'tempo: clock' with 'clock: <MIDI input>'
guitar-picker.yaml line 7: tempo: clock names no clock input; add 'clock: <MIDI input>', e.g. the MPC's port as 'apc64 ports' lists it
```

### Chord-aware lanes: R and A, and no wrong bass

With `play: all` an unpressed string rings open, but never **below the chord's root string**: the root is the
chord the held notes make (the harmony views' chord; with the open strings that would ring when the notes alone make
none), the root string the lowest string sounding it. So a C (x32010) never rings the open low E, a D (xx0232) leaves
the A and low E strings silent, and E, G, F and Em keep the low E. A pressed string below the root still plays.

A pattern may write two lanes that follow the chord instead of a fixed string: **`R`**, the root string, and **`A`**,
its alternate bass (root on string 6 or 5: string 4; on 4: string 3; otherwise the next string up). The shipped
Travis pick plays its thumb on R and A, so it is right on every chord (on E the low E and the D string, on C the A and
D strings, on D the D and G strings). A string R or A covers at a step plays once. On the page R and A are the last
two rows of the grid. (`docs/performer-format.md` section 10.)

### Chord types and pattern slots on the pads

```yaml
name: Guitar picker
lab:
  generator: guitar
  tuning: e-standard
  performer:
    pattern: arpeggio-manual-bass
    chords: [maj, min, 7, maj7, m7, sus2, sus4, dim]                         # the top row, left to right
    slots: [arpeggio-manual-bass, travis, arpeggio, strum, waltz, ~, ~, ~]   # the bottom row (~: an empty pad)
```

On a guitar with 6 strings or fewer the strings use rows 2–7, and the performer puts its **control pads** on the free
rows: the top row chooses a **chord type** (amber; the chosen one bright), the bottom row a **pattern slot** (blue;
the one playing bright; an empty slot is dark and silent). They send notes 0–15 on channel 16, which the host takes
and never forwards (a layout whose strings use channel 16 would be refused). On 7 strings the top row holds the
slots and **Shift + a pad** chooses the chord type of its column; on 8 strings Shift + a pad chooses the chord type
of its column, Shift + a pad on the top row the slot. Shift alone and Shift + encoder (the layout browser) work as
before. `chords` takes 1–8 types from `maj min 7 maj7 m7 sus2 sus4 dim aug 6 m6 dim7 m7b5 7sus4 add9 5` (default the
first eight); `slots` 1–8 patterns.

A chosen chord type **stays chosen** until another is chosen, or the same pad again (off: what you fret plays). With
a type chosen, **one note** pressed on a pattern string is the **root**: the chord is voiced on the strings from that
note on its string (C on the A string as `maj`: x32010; A on the A string as `m7`: x02010; F on the low E: 133211 —
CAGED by the root's string, open strings in the open position) and the pattern plays it from that press. Two notes or
more play as fretted. A type changed while the root is held re-voices it (the strings that change end at once, the
next hits play the new notes). Manual strings stay yours. The harmony views and the neck show the voicing (its notes
as dots on their strings); the OLED flashes the chord (`Am7`) or `Type off`, and a slot's pattern name. The page's
Performer section shows the type and the slot and chooses them too (`apc64 lab performer type m7`, `… slot 2`).

```text
guitar-picker.yaml line 7, chords: no chord type 'min7b5'; did you mean m7b5? chord types: key, key 7, maj, min, 7, maj7, m7, sus2, sus4, dim, aug, 6, m6, dim7, m7b5, 7sus4, add9, 5, mM7, maj7#5, 7b5, 7#5, mM7b5, b5
```

### Chords in key

```yaml
name: Picker in key
lab:
  generator: guitar
  tuning: e-standard
  scheme: scale
  scale: major
  root: C
  performer:
    pattern: travis
    chords: [key, key 7, maj, min, 7, m7, sus4, dim]
```

The **key** is the layout's scale: `scheme: scale` with its `scale` and `root` (section 4). The pads light in key,
the notes of the scale in their colours and every other note dark, so you see what is in key. Without a scale (the
`fifths` scheme) there is no key: playing is free, chromatic.

Two chord types play **the key's own chords**: **`key`**, the triad the key stacks on the note you press (in C
major: C, Dm, Em, F, G, Am, Bdim), and **`key 7`**, its seventh (Cmaj7, Dm7, Em7, Fmaj7, G7, Am7, Bm7b5); the
chord is named by its intervals, so a harmonic minor key gives its mM7, maj7#5 and dim7 too. It is **strict**: a
note out of key plays nothing (no borrowing), and the key's chords need a seven-note scale (a pentatonic key has
none). Two notes or more play as fretted, as with every type; type off plays what you fret. `layouts/guitar-picker-
key.yaml` is this layout (with the picker's slots, Travis pick first, so a root on a bass string is voiced too);
`layouts/guitar-picker.yaml` stays the one where every chord type is yours to choose.

The page's **Key** (beside the chord types) changes the key for the session, not the file: none (chromatic), or a
tonic and one of the seven modes, harmonic or melodic minor; the pads are written again at once, and **file** goes
back to the layout's key. `apc64 lab key E dorian`, `apc64 lab key none` and `apc64 lab key layout` do the same.
A layout listing `key` without a scale is warned (`key and key 7 need a key: this scheme lights no scale; …`); the
key's chord pads then flash `No key` on the OLED until a Key is chosen (`No 7-note key` for a pentatonic one).

### Editing patterns on the page

The Performer section's grid is the pattern, editable: a click on a cell cycles `·` → `●` hit → `◉` accent → `·`, the
strum row `↓` down → `↑` up → none, and a string's box makes it manual (passed through as played). Beside it: meter,
step, length (bar lines and beat lines follow the meter), swing, spread, the pattern's play mode, name and
description. Every edit plays at once, from the next step, without a restart, and the pattern is marked unsaved.
The length shows its duration in the meter (`8 steps = 1 bar`, `12 steps = 1 ½ bars`). A new **step** re-grids the
pattern, keeping its duration and every hit at its time: 1/8 → 1/16 doubles the cells (a hit on step k moves to
2k, the strum row and R and A too); 1/16 → 1/8 halves them, a hit between the new steps moving to the nearest
(a tie: the earlier) and two hits on one step merging (an accent wins); a triplet step re-grids by time, the length
rounded to whole steps when the duration does not divide. Past 32 steps the pattern is cut to 32. The editor says
what moved, merged, was rounded or cut (`2 hits between the new steps moved to the nearest step`, `cut to 32 steps:
2 bars of 1/16; 2 hits after them were dropped`).
The service **keeps the unsaved edits of each pattern** while you choose others (the list, the slot buttons, the
unit's slot pads): come back and the edit plays and shows again; the list and the slot buttons mark it ●. The edits
last while the service runs: a restart of the service drops them. The editor always shows what plays: a slot chosen
on the unit shows its pattern here at once. **Save** writes `patterns/<name>.yaml` in the canonical form (checked
first, every issue shown by its row or field; refused if the file changed on disk since it was read), and the edit
is gone; **Save as** writes it under another file name, which then plays; **Revert** drops the edit and plays the
file; **New** and **Duplicate** make a new pattern, kept too until saved (one at a time: a second New asks before it
replaces it); **Delete** asks in the panel's own overlay. **Sequencer** (beside the Performer's `?`) opens the
editor alone across the page, the grid large enough to read from a distance (its cells fill the width, up to 32
steps) with everything needed while playing above it: the pattern list, the slots, the chord types, the tempo or
clock, latch, play mode and Stop, and the editor's toolbar and fields; **Full screen** there uses the browser's,
and Esc or **Leave** goes back. **New tab ↗** opens it at `?view=sequencer`, a tab of its own (or a tablet beside
the unit). It is the same editor on the same state: an edit there is the panel's, and every tab follows what plays.
Every text a save replaces (or a delete removes) is kept outside the repository (`apc64 lab
pattern-versions travis`, `apc64 lab restore-pattern travis <version>`). Agents write patterns with `apc64 lab
write-pattern my-pick.yaml` (or `POST /api/lab/patterns/save` with the text or the data).
