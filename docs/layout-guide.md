# Writing APC64 Host layouts

A **layout** is one YAML file in `layouts/` (for example `layouts/jam.yaml`). It says what every pad, button,
strip and the encoder sends while the APC64 Host holds the unit. The file name (without `.yaml`) is the
layout's identity; its `name:` is what the OLED and the page show.

Save a layout in `layouts/` and it is live on the unit and in the page within a second. If it has an error,
nothing changes on the unit: the previous version keeps working and the error is shown on the page and by
`apc64 validate`. Every version that went live is kept, so any change can be rolled back.

The machine-readable schema is [`docs/layout.schema.json`](layout.schema.json). Every `yaml` example in this
guide is checked by the test suite, so each one is a valid layout as written.

Port names in the examples (`MPC Live III MIDI 1`, `Bitwig Studio In`, `USB MIDI Interface MIDI 1`) are
examples from the author's setup; use the names `apc64 ports` lists on your machine.

## 1. The smallest useful layout

```yaml
name: Jam
devices: {mpc: MPC Live III MIDI 1}
pages:
  1 Drums:
    pads r1c1-r2c8: notes from 36 on mpc ch 10
banks:
  1 Mix:
    strips 1-8: cc 20-27 on mpc ch 1
```

That is 16 drum pads (notes 36–51 on MPC channel 10) and 8 strips as CC 20–27. Validate it:

```text
$ apc64 validate layouts/jam.yaml
valid: 1 page, 1 bank, 16 pads, 8 strips bound
```

## 2. The parts of a layout

| key | what it holds |
|---|---|
| `name` | Display name. The OLED shows 14 ASCII characters; longer names are cut, with a warning. |
| `devices` | Every MIDI port the layout uses, declared once by a short name. |
| `device` | Optional default device for bindings that do not say `on <device>`. |
| `pages` | Up to 8 pages, selected by the 8 scene buttons. Each holds pad and button bindings. |
| `banks` | Up to 6 strip banks, selected by the 6 strip-mode buttons. Each holds strip bindings. |
| `routing` | Where notes played in the unit's own Note/Chord/Step/Drum and Custom views go. |

Pages and banks are independent: switching the bank keeps the page and the other way round. A page or a bank
is written as its number, optionally followed by its name: `1 Drums:`, `2:` or `page 3 Keys:`.

## 3. Devices

```yaml
name: Devices
devices:
  mpc: MPC Live III MIDI 1                          # the ALSA port name …
  bitwig: Bitwig                                    # … or a unique part of it
  keys: {port: USB MIDI Interface MIDI 1, ch: 3}    # with a default channel
device: mpc
pages:
  1:
    pad r1c1: note 36                  # on mpc (the default device), channel 1
    pad r1c2: note 60 on keys          # channel 3, the device's default
    pad r1c3: cc 20 on bitwig ch 2     # an explicit channel wins
```

- A binding names its device with `on <device>`. Without it, the `device:` default is used, or the only
  declared device when there is just one.
- Channels are written 1–16: `ch 10`. Without `ch`, the device's `ch` is used, else channel 1.
- A device may not be one of the APC64's own ports: the host never sends to them.
- When a port name part matches two ports, validation says so and asks for the full name. A device whose port
  is not there right now still loads; its controls show `(missing)` until the port appears.

## 4. Control names

```text
              strips 1-8 (left)        the 8 × 8 grid                         scene 1-8 (right)
   strip 1 … strip 8          pad r8c1 pad r8c2 … pad r8c8   ← row 8 is the top     scene 1  (page 1)
                              …                                                     …
                              pad r1c1 pad r1c2 … pad r1c8   ← row 1 is the bottom  scene 8  (page 8)
                              track 1  track 2  … track 8      (track buttons)
                              trackctl 1        … trackctl 8   (track-control row)
   stripmode 1-6 select banks;  shift;  encoder, encoder press
   tempo clear duplicate quantize fixed undo · play rec stop · up down left right · recarm mute solo clipstop
```

| bindable on pages | names |
|---|---|
| grid pads | `pad r1c1` … `pad r8c8` (row 1 is the bottom row, column 1 the left) |
| track buttons, track-control row | `track 1` … `track 8`, `trackctl 1` … `trackctl 8` |
| other buttons | `tempo`, `clear`, `duplicate`, `quantize`, `fixed`, `undo`, `play`, `rec`, `stop`, `up`, `down`, `left`, `right`, `recarm`, `mute`, `solo`, `clipstop` |
| encoder | `encoder` (turn), `encoder press` — base layer only |
| bindable in banks | `strip 1` … `strip 8` |

Not bindable: `scene 1`–`scene 8` (they select pages), `stripmode 1`–`stripmode 6` (they select banks), `shift`
(it selects the Shift layer), and the unit's own view buttons. Shift + encoder browses layouts, so the encoder
cannot be bound on the Shift layer.

**Range forms** bind a run of controls in one line: `pads r1c1-r2c8` (16 pads, in reading order from the
bottom-left: r1c1, r1c2, … r1c8, r2c1, … r2c8), `tracks 1-8`, `trackctls 1-4`, `strips 1-8`.

## 5. Bindings

A binding is a short phrase: a **message**, then where it goes, then **options**.

| message | sends |
|---|---|
| `note 36`, `note C1` | note-on on press, note-off on release |
| `cc 20`, `cc 20 value 64` | CC 20 = 127 (or 64) on press, CC 20 = 0 on release |
| `program 5` | a program change on press |
| `none` | nothing: unbinds this control (useful inside a range) |
| strips only: `cc 20` | the strip position as a 7-bit CC (position ÷ 128) |
| strips only: `cc14 20` | the 14-bit position as CC 20 (MSB) then CC 52 (LSB); `cc14 20/40` names the LSB |
| strips only: `pitchbend` | the full 14-bit position as pitch bend |

On a range, numbers can count up: `notes from 36` (36, 37, 38, …), `notes 36-51`, `cc from 20`, `cc 20-27`
(an explicit range must have one value per control). A plain `note 36` on a range makes every control send 36.

Then, in any order:

| option | meaning |
|---|---|
| `on mpc` | the device (see §3) |
| `ch 10` | the channel, 1–16 |
| `toggle` | a latching toggle: each press flips on/off (127/0); `toggle 100/0` sets the values. Releases send nothing |
| `momentary` | the default: on while held |
| `velocity 100` | a fixed note velocity (Session-view pads otherwise send 127, what the unit reports) |
| `colour red` | the LED colour (25 % when idle, full while pressed or toggled on) |
| `label "Kick"` | the text the page shows instead of the generated `Note 36 → mpc` |
| `feedback` | the LED follows the same message coming back from the device (see §7) |
| strips: `touch note 60` | a message on touching the strip (note-off on release) |
| strips: `bar` or `bipolar` | the LED bar style (a white bar by default) |

Several messages are joined with ` + ` and sent in the written order:

```yaml
name: Messages
devices: {mpc: MPC Live III MIDI 1}
pages:
  1 Scenes:
    track 1: cc 20 value 127 + program 5
    track 2: [cc 21, program 6]             # a YAML list works too
    pad r1c1: note C1 velocity 100 colour orange label "Kick"
    pad r1c2: {send: note 38, colour: yellow, label: "Snare: tight"}   # the same words as keys
```

If a label contains ` #` or `: `, quote the whole binding (`pad r1c1: 'note 36 label "No. #1"'`) or use the
key form as in `pad r1c2` above — otherwise YAML reads the rest of the line as a comment or a key.

**Colours** are names or palette indexes 0–127: `off`, `dimwhite`, `grey`, `white`, `red`, `orange`, `yellow`,
`lime`, `green`, `mint`, `teal`, `cyan`, `blue`, `purple`, `magenta`, `pink` (also `dim white`, `gray`, `violet`).
The page shows them in approximate colours: the APC64's exact palette is not known.

**Note names** use the Ableton/Akai/MPC convention, **C3 = 60**: C-2 = 0, C1 = 36, C2 = 48, C3 = 60, C4 = 72.
Sharps and flats are written `F#2`, `Bb2`. The page always shows the number next to a name.

## 6. Pages, the Shift layer and precedence

```yaml
name: Live set
devices: {mpc: MPC Live III MIDI 1}
pages:
  1 Drums:
    pads r1c1-r2c8: notes from 36 ch 10 colour red
    pad r1c3: note 40 ch 10 colour yellow     # one pad of the range, different
    pad r1c4: none                            # and one left empty
    play: cc 118
    stop: cc 117
    encoder: cc 30                            # turning keeps a value 0–127, starting at 64
    shift:
      pads r1c1-r2c8: notes from 52 ch 10 colour purple
      play: cc 119
  2 Keys:
    pads r1c1-r8c8: notes from 24 ch 2 colour blue
  3:                                          # an unnamed page shows as "Page 3"
    tracks 1-8: cc from 40 toggle colour green
```

- The **Shift layer** applies while Shift is held (on the unit or in the page). A control with no Shift binding
  sends nothing while Shift is held — there is no fall-back to the base layer.
- **Precedence:** a single-control entry overrides the range that covers it on the same page and layer. Two
  ranges, or two single entries, that bind the same control on the same page and layer are an error naming
  both lines.
- Pressing an empty page's scene button keeps the current page. The scene LEDs show full = current page,
  dim = defined, off = empty. A release always goes to what the press triggered, even if you switched page.
- Toggle states are kept per page and layer, and survive a reload of the file when that binding did not change.

## 7. Banks, strips and feedback

```yaml
name: Mixer
devices:
  bitwig: {port: Bitwig Studio In, ch: 1}
pages:
  1 Transport:
    play: cc 118 toggle feedback colour green
    rec: cc 119 toggle feedback colour red off dimwhite
    mute: cc 120 toggle feedback cc 64 from bitwig
banks:
  1 Volume:
    strips 1-8: cc from 20 touch note from 60 feedback
  2 Pan:
    strips 1-8: cc from 30 bipolar colour blue feedback
  3 Fine:
    strip 1: cc14 40
    strip 2: pitchbend ch 2 touch note 70
```

- **Feedback** lets incoming MIDI drive an LED or a strip bar. Plain `feedback` follows the binding's own
  message coming back on the device's input port; `feedback cc 64 from bitwig ch 1` names another message.
  Value 0 shows the off look (`off <colour>`, else the dimmed colour), any other value the on colour.
  `colours 0:off 64:yellow 127:green` sets a colour per value. Feedback also sets a toggle's state, so the
  next press sends the opposite. Feedback never writes the OLED.
- A strip bar shows its feedback value when it has feedback, otherwise its last touched position. Strips cannot
  be toggles.

## 8. Expressive playing: routing the unit's own views

In Session view the pads are fixed-velocity triggers (velocity 127, no aftertouch), bound as above. In the
unit's own **Note, Chord, Step and Drum** views the pads send real velocity and poly aftertouch on the APC64's
Notes port, and in **Custom** view on its Custom port. `routing` says where those notes go:

```yaml
name: Keys
devices: {mpc: MPC Live III MIDI 1}
routing:
  notes: mpc ch 2 aftertouch pass                  # Note/Chord/Step/Drum views
  custom: mpc ch 3 aftertouch drop transpose -12   # Custom view
pages:
  1 Controls:
    tracks 1-8: cc from 20
```

- Velocity always reaches the target untouched. `aftertouch pass` forwards poly aftertouch, `pressure` turns
  it into channel pressure (the highest of the held notes), `drop` forwards none.
- `transpose 12` shifts notes; `remap 36>38 37>40` replaces listed notes (then transposes). A note pushed
  outside 0–127 is dropped and listed in the activity list.
- Routing does not change with pages and banks. Without a rule, played notes are shown but not sent anywhere.
- The mapping form also works: `notes: {device: mpc, ch: 2, aftertouch: pressure, remap: {36: 38}}`.

## 9. Generated layouts

Layouts are plain files, so a script can write them. This Python writes a chromatic grid, one fourth per row:

```python
lines = ["name: Fourths", "devices: {synth: Bitwig Studio In}", "pages:", "  1 Grid:"]
for row in range(1, 9):
    lines.append(f"    pads r{row}c1-r{row}c8: notes from {36 + (row - 1) * 5} on synth ch 1")
open("layouts/fourths.yaml", "w").write("\n".join(lines) + "\n")
```

which produces:

```yaml
name: Fourths
devices: {synth: Bitwig Studio In}
pages:
  1 Grid:
    pads r1c1-r1c8: notes from 36 on synth ch 1
    pads r2c1-r2c8: notes from 41 on synth ch 1
    pads r3c1-r3c8: notes from 46 on synth ch 1
    pads r4c1-r4c8: notes from 51 on synth ch 1
    pads r5c1-r5c8: notes from 56 on synth ch 1
    pads r6c1-r6c8: notes from 61 on synth ch 1
    pads r7c1-r7c8: notes from 66 on synth ch 1
    pads r8c1-r8c8: notes from 71 on synth ch 1
```

## 10. Errors

Every error names the file, the line, the control, what is wrong and how to fix it, and all errors of a file
come at once in line order. The page, `apc64 validate` and the API show the same text:

```text
jam.yaml line 12, pads r1c1-r1c8: expected ':' after the control name; write "pads r1c1-r1c8: notes 36"
jam.yaml line 8, pad r9c1: no such pad, pads are r1c1–r8c8
jam.yaml line 14: unknown device mcp, declared devices: mpc
jam.yaml line 11: lines 10 and 11 both bind pads r1c5–r1c8 on page 1 base layer; keep one
jam.yaml line 40, page 9: the APC64 has 8 scene buttons, so pages are 1–8
jam.yaml line 22, strip 1: a strip position cannot be a toggle; remove "toggle"
```

Warnings (a name too long for the OLED, a device whose port is absent right now) never stop a layout.

**Common mistakes**

| wrong | right |
|---|---|
| `pads r1c1-r1c8 notes 36` | `pads r1c1-r1c8: notes 36` — every entry is `<control>: <binding>` |
| `pad 1: note 36` | `pad r1c1: note 36` — pads are named by row and column |
| `scene 1: cc 20` | scenes select pages and cannot be bound; use `track 1` or another button |
| `strip 1: cc 20` under `pages:` | strips go under `banks:` |
| `cc 20 program 5` | `cc 20 + program 5` — several messages need ` + ` |
| `ch 0` or `ch 17` | channels are 1–16 |
| `notes 36-50` on 16 pads | `notes 36-51` or `notes from 36` — one value per control |
| `9 Extra:` under pages | pages are 1–8, banks 1–6 |

## 11. Tweaks from the page

A tweak saved on the page (assignment, label, colour, momentary/toggle) changes one control only: it adds,
replaces or removes one `<control>: <binding>` line, written in this same notation, and leaves every other
line, range and comment as it was. Setting a control back to what its range gives removes that line again.
If the file changed since the page read it, the tweak is refused with "layout changed, reload".
