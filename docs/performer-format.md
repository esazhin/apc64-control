# The performer pattern format

A **performer pattern** turns what is held into a timed sequence: automatic strumming and fingerpicking. It is a
step matrix with one row (a **lane**) per string, up to 32 steps, in a meter. When notes are held, the whole pattern
plays over them; strings marked **manual** are left to the player and pass straight through.

This document is the format's specification, independent of any program. The canonical form is **JSON-compatible
data**; a YAML file is that data written more readably, so a JavaScript port reads the same files (YAML parsed to
the same data, or the JSON form). The machine-readable schema is [`performer.schema.json`](performer.schema.json).
The reference implementation is the standard-library Python package [`performer/`](../performer/README.md); in APC64
Control the patterns live in `patterns/` and are chosen per layout (`docs/lab-guide.md`, section 12).

## 1. A pattern

```yaml
name: 1-2-3 + bass
description: Arpeggio 1-2-3 over a manual bass
meter: 4/4          # beats per bar / beat unit
step: 1/8           # 1/4, 1/8, 1/16, 1/8t, 1/16t
length: 8           # steps, up to 32
lanes:              # lane: one cell per step; . rest, x hit, X accent; spaces and | ignored
  1: . . . x | . . . x
  2: . x . . | . x . .
  3: . . x . | . . x .
manual: [4, 5, 6]   # strings played by hand, passed through as played
```

The same pattern as JSON:

```json
{"name": "1-2-3 + bass", "description": "Arpeggio 1-2-3 over a manual bass", "meter": "4/4", "step": "1/8", "length": 8,
 "lanes": {"1": ". . . x . . . x", "2": ". x . . . x . .", "3": ". . x . . . x ."}, "manual": [4, 5, 6]}
```

## 2. The keys

| key | value | default | meaning |
|---|---|---|---|
| `format` | `1` | 1 | the format version |
| `name` | text, required | | the pattern's name; the APC64's OLED shows 14 characters (a longer name is a warning) |
| `description` | text | | for readers |
| `meter` | `beats/unit`: `4/4`, `3/4`, `6/8` … (beats 1–32, unit 1, 2, 4, 8 or 16) | `4/4` | where the bars fall |
| `step` | `1/4`, `1/8`, `1/16`, `1/8t`, `1/16t` | `1/8` | one step: a quarter, an eighth, a sixteenth, an eighth or a sixteenth triplet |
| `length` | 1–32 | the rows' cell count | steps in the pattern; it loops |
| `lanes` | lane (1–16, `R` or `A`) → row, required | | the cells of each lane (section 3; R and A: section 10) |
| `strum` | a row of `d`, `u`, `.` | | per step: how the hits of that step are spread (section 4) |
| `spread` | 0–100 ms | 15 | the time between strings in a strum |
| `swing` | 50–75 % | 50 | every second step later: 50 straight, 66 a triplet feel, 75 the most |
| `play` | `all`, `pressed` | `all` | which lanes play: every pattern lane (a string with nothing pressed rings open, unless it is below the chord's root), or only the pressed ones (sections 5, 10) |
| `gate` | `ring` or a number of steps (0–32) | `ring` | how long a note lasts: until its lane's next hit, or that many steps |
| `velocity` | `{hit: 1–127, accent: 1–127}` | `{hit: 100, accent: 127}` | an `x` and an `X` at a full press |
| `humanize` | `{timing: 0–50 ms, velocity: 0–64}` | none | a random ± on every hit's time and velocity |
| `manual` | a list of lanes | none | lanes played by hand: not the pattern's (section 5) |

Any other key is refused (with the nearest key named when it is a misspelling).

## 3. Rows: the grid notation

A row is text with **one cell per step**: `.` rest, `x` hit, `X` accent. Spaces and `|` are ignored, so a row can be
grouped by beat or by bar: `x . . . | x . . .` and `x...x...` are the same row. Every row has `length` cells (without
`length`, every row has the same count, which becomes the length).

- Lanes are numbered from 1. With **strings** addressing (section 5) lane 1 is the highest string: on a 6-string
  guitar lane 1 is the high E and lane 6 the low E.
- Two lanes follow the chord held instead of a fixed string: **`R`**, the chord's root string, and **`A`**, its
  alternate bass (section 10). A pattern may write them beside numbered lanes (`R: X . . . x . . .`).
- A lane not written is silent (all rests). A lane written in `manual` has no row.
- At least one cell is a hit.
- In YAML, a row must not start with `|` or `-` (YAML would read a block or a list); quote it then: `"| x . x ."`.
- In YAML, lane keys are numbers (`1:`); in JSON they are strings (`"1":`). Both mean the lane.

The `strum` row has one mark per step in the same notation: `d`, `u` or `.` (`D` and `U` are the same).

## 4. Time

- **Tempo** is in BPM, quarter notes a minute (as DAWs and MIDI clock count, 24 clock ticks a quarter), whatever
  the meter. A step lasts `60 / BPM × 4 × step` seconds: at 120 BPM a `1/8` step is 0.25 s, a `1/16` 0.125 s, a
  `1/8t` 1/6 s.
- The **meter** only places the bars: it does not change the speed. A length that is not a whole number of bars is
  a warning (the pattern loops after `length` steps all the same).
- **Swing** moves every second step (the 2nd, 4th … of the pattern) later by `(2 × swing / 100 − 1)` of a step:
  nothing at 50, a third of a step at 66.7, half a step at 75.
- **Strum.** At a step marked `d` the hits of that step are spread `spread` ms apart from the lowest lane in pitch
  (the highest lane number) to the highest (lane 1); at `u` from lane 1 down. Unmarked steps hit together.
- **Gate.** `ring`: a note sounds until its lane's next hit, or until the chord changes on that lane (section 6).
  A number: it ends that many steps after it started (`0.5` is half a step), or earlier at its lane's next hit.
- **Humanize.** Each hit moves by a random amount within ± `timing` ms and its velocity within ± `velocity`. The
  random sequence is not part of the format; a seed makes one implementation repeatable.

## 5. Lanes, addressing and manual lanes

A pattern addresses lanes 1…N. The program playing it maps lanes to what is held, in one of two ways:

- **`strings`** (the default where the instrument has strings): lane k is string k (1 the highest). A hit on lane k
  plays the note held on string k, one note per string. The APC64's guitar layout sends each string on its own MIDI
  channel, so string identity is known.
- **`voices`** (a keyboard, or any instrument without strings): lane k is the k-th held note counted from the top.
  A hit on lane 1 plays the highest held note, lane 2 the next, and so on; a lane beyond the held notes rests.

**Play mode** (`play`): which lanes sound at their hits.

- **`all`** (the default): every pattern lane plays at its hits. A string with nothing pressed plays its open
  note, as on a guitar, where open strings are not fretted: an open-position A minor (x02210) presses only the D,
  G and B strings, yet a 5-3-2-1 pattern plays four notes, the A string ringing open. A string with nothing pressed
  **below the chord's root string** stays silent (section 10), so a C (x32010) never rings the open low E; a
  pressed string there still plays. With voices addressing there is no open string: a voice beyond the held notes
  rests.
- **`pressed`**: only lanes with a pressed note play; a hit on a lane with nothing pressed is silent.

In both modes the grid is fixed: a missing note leaves its step silent and never moves a later step. A program may
override the pattern's mode (APC64 Control: the layout's performer block and the page).

**Manual lanes** (`manual: [4, 5, 6]`, strings addressing): those strings are not touched by the pattern. What the
player presses there passes straight through at once, as played (velocity and aftertouch), and never starts or
stops the pattern. So a player holds the high strings and plays an alternating bass by hand on strings 5 and 6
while the 1-2-3 pattern keeps playing over the held high notes: 5 + 123, 6 + 123, 5 + 123 … then changes the chord
(Am → C) and plays 5 + 123, 4 + 123. With voices addressing `manual` is ignored.

## 6. The engine (normative)

How a pattern plays over what is held. Times are explicit: an implementation takes each input with its time and
answers the events due up to a time, so it is deterministic and testable.

1. **Start.** The pattern starts at step 1 exactly at the first press on a pattern lane: the hits of step 1 play at
   once. Phase is locked to that press; a clock only sets the speed. In both play modes only a press starts it: an
   open string is not a press, so nothing plays while nothing is pressed.
2. **Chord changes.** While it runs, a change of what is held does not restart it: the next hits play the new notes.
3. **One note per lane.** Every hit on a lane ends the note sounding there (a hit with nothing to play leaves the lane
   silent: `pressed` mode with nothing pressed there, or a voice beyond the held notes; the grid never moves). A press of another note on a pattern lane ends that lane's note at once: the chord changed there. A
   release never cuts a note: it rings until its lane's next hit (or its gate, or the stop).
4. **Catch.** A press within 30 ms after a hit on its lane plays that hit again with the new note, so a chord
   pressed a few milliseconds after its first finger (or changed just after the beat) still sounds whole.
5. **Stop.** When every pattern lane is released, the pattern stops one step later (a grace, so a quick chord change
   with a gap goes on), ending its notes. A later press starts it again at step 1. An explicit stop ends it at once.
   The grace only keeps the time running: with nothing held (latch off) its hits play nothing, so no open string
   rings at the end; a press within it goes on in phase, and catch (rule 4) plays a hit that fell just before it.
   **Letting go.** A string released while others are still held does not ring open at once: it stays silent until
   the **settle** time (120 ms in the reference) has passed without another release, and the chord's root (section
   10) stays the one before the letting go began meanwhile. A chord let go of string by string (an ending) therefore
   never rings an open string nor wakes the bass strings below its root; when the other strings are still held
   after the settle time, the lift was meant (C → Cmaj7, the finger on string 2 lifted) and the string rings open
   from its next hit. A press ends the settling.
6. **Latch.** When on, releasing keeps the last held notes playing until a stop or a new press; the first press
   after everything was released replaces the whole set.
7. **Velocity.** A hit's velocity is its cell's (`velocity.hit` or `velocity.accent`) scaled by the press velocity of
   the note it plays: `round(cell × press / 127)`, then humanized, kept within 1–127. An open string (`play: all`)
   takes the latest pattern-lane press velocity.
8. **Manual lanes** pass presses, releases and aftertouch through at once, one note per lane (a new press there ends
   the previous one); the pattern's own notes take no aftertouch.
9. **Tempo changes** take effect from that moment; steps already due keep their times. A pattern changed while
   running goes on at the same place in time from its start (in beats), from the new pattern's next step; every
   hit of the new pattern plays (its steps are new ones, even where a step number equals one the old pattern played).
10. **The chord** (section 10): which string an `R` or `A` hit plays, and which unpressed strings stay silent in
    `all`, is decided when each hit is due, from what is held (pressed, or latched) then. A string an `R` or `A`
    hit covers at a step plays once, at the louder of the two levels. Catch (rule 4) applies to every lane whose
    note a late press changes: an open string the new root puts below it ends at once, and an `R` or `A` hit the
    new root moves plays again on its new string.
11. **Muted strings.** The program may mark strings muted (a voicing's `x`, section 11): an unpressed muted string
    never rings open; a pressed one plays. A change of the muted strings made while nothing is held (the voicing's
    root let go) takes effect at the next press, so a latched voicing keeps its muted strings.

## 7. Validation

Every refusal names its place, what is wrong and how to fix it, and all of them are reported at once. A file names
the line; this pattern file has five mistakes:

```yaml
name: Travis pick
meter: 4/4
step: 1/5
length: 8
strum: d . d
swng: 54
lanes:
  1: x . . . . . . x
  2: . . . x . . .
  4: . . x . . . x .
manual: [4, 5, 6]
```

and gets:

```text
travis.yaml line 3: '1/5' is not a step; write one of 1/4, 1/8, 1/16, 1/8t, 1/16t
travis.yaml line 5, strum: 3 steps; length is 8; write one mark per step: d, u or .
travis.yaml line 6: unknown key 'swng'; did you mean swing? a pattern takes format, name, description, meter, step, length, lanes, strum, spread, swing, play, gate, velocity, humanize, manual
travis.yaml line 9, lane 2: 7 steps; length is 8; write one cell per step: . (rest), x (hit) or X (accent); spaces and | are ignored
travis.yaml line 10: lane 4 is manual and has a row; remove its row, or take 4 out of manual
```

Warnings (the pattern still plays): a name longer than 14 characters, a length that is not a whole number of bars,
`spread` without a `strum` row.

## 8. The canonical form

Written back by a program (an editor saving a pattern), a pattern is the data with every default filled in, lane
keys as strings, and rows with a space between cells and ` | ` at every bar:

```json
{"format": 1, "name": "Waltz 3/4", "meter": "3/4", "step": "1/4", "length": 6,
 "lanes": {"1": ". x x | . x x", "2": ". x x | . x x", "3": ". x x | . x x", "5": ". . . | X . .", "6": "X . . | . . ."},
 "strum": ". d d | . d d", "spread": 8, "swing": 50, "play": "all", "gate": "ring",
 "velocity": {"hit": 100, "accent": 127}, "humanize": {"timing": 0, "velocity": 0}, "manual": []}
```

## 9. Porting

The Python package `performer/` is the reference: `pattern.py` (parsing, the issues, the canonical form),
`engine.py` (section 6), `clock.py` (the tempo of a MIDI clock: the mean of the last 24 tick intervals),
`chords.py` (the chord types and a chord's root, section 10) and `voicing.py` (section 11). It imports only the
standard library and keeps no clock or thread, so a port is a translation of five files plus their tests
(`performer/test_*.py`), which state every rule above with exact times and every voicing below by its shape.

## 10. Chord-aware lanes

A pattern written for absolute strings plays the wrong bass on a chord whose root is not on the low string: a
Travis pick with its thumb on string 6 rings the open low E under a C. Two rules follow the chord instead.

**The root and the root string.** The chord held has a root, the pitch class a chord recognition gives for the
notes held (pressed, or latched): first for those notes alone, then, if they make no chord, with the open notes of
the unpressed strings that would ring (in `play: all`; a manual or muted string does not ring). The program may
bring its own recognition (APC64 Control passes its harmony core's); the reference's (`chords.chord_root`) matches
the types below at every root, the larger types first, then the root in the bass, then the order maj, min, sus2,
sus4, 7, maj7, m7, dim7, m7b5, dim, aug. The **root string** is the lowest string sounding the root: pressed with a
note of the root's pitch class, or open where nothing is pressed and the open note is the root's pitch class. With
no chord (or the root nowhere), it is the lowest pressed string.

**Muting below the root.** In `play: all` an unpressed string below the root string stays silent; a pressed one
still plays (a C/G with G pressed on the low E plays it). In E standard the usual open chords then never sound a
wrong bass:

| chord | shape | root string | silent |
|---|---|---|---|
| E | 022100 | 6 (open) | — |
| Em | 022000 | 6 (open; E B + the open G make Em) | — |
| G | 320003 | 6 | — |
| F | 133211 | 6 | — |
| A, Am | x02220, x02210 | 5 (open) | 6 |
| C | x32010 | 5 (C + E with the open G make C) | 6 |
| D, Dm | xx0232, xx0231 | 4 (open) | 5, 6 |

**R and A.** Lane `R` plays the root string; lane `A` the alternate bass: with the root on string 6 or 5, string 4;
on string 4, string 3; otherwise the next string up (root on 3 → 2, on 2 → 1, on 1 → none; on a 7- or 8-string
root on 7 → 6, on 8 → 7). Each plays what its string plays (the note pressed there, else the open string in `all`).
Nothing held, or the string manual: the hit rests. With **voices** addressing `R` is the lowest held voice and `A`
the second lowest. A string an `R` or `A` hit covers at a step plays once, even when its own numbered lane hits
there too (at the louder level). In a strum, `R` and `A` take their string's place in the order.

```yaml
lanes:
  1: x . . . . . . x
  3: . x . . . x . .
  R: X . . . x . . .      # the root string on 1 and 3: the low E on E, the A string on C, the D string on D
  A: . . x . . . x .      # its alternate bass on 2 and 4: the D string on E and C, the G string on D
```

## 11. Voicings

A program may play a chord from **one root note and a chord type** (APC64 Control: a root pad and a chord-type pad):
the voicing builder turns them into one note per string, which the program then holds as if fretted, marking the
muted strings (rule 11). The contract (`voicing.build_voicing(opens, root, string, chord, frets)`):

- **Input.** The tuning as open notes per string (1 the highest), the root note and its string, a chord type (by
  name, from the table), the neck's length. A root below its string's open note (or past the neck) has no voicing.
- **The bass.** The root stays on its string at its fret, every lower string is muted, no note is below the root.
- **The strings above** each take a chord tone or are muted; fretted notes within a span of 4 frets; an open string
  where it is a chord tone and the shape is in the open position (no fretted note above fret 3).
- **Playable.** At the lowest fret one barre (never across an open string) or, with the root open, a finger on each
  string there; each higher fret a finger per run of neighbouring strings; four fingers at most.
- **The best shape**, in this order: the most of the chord without its fifth (root 16, each other tone 4); the
  fewest muted strings between sounding ones; the most sounding strings; the most open strings; the fifth; the
  CAGED shape of the root's string (string 6: E shape R 5 R 3 5 R; 5: A shape R 5 R 3 5; 4: D shape R 5 R 3; a
  seventh may take the octave's place; strings counted up from the root's); the fewest fretted notes below the root's
  fret; the fewest fingers; the lowest frets. With the root open (fret 0) the CAGED shape comes before the open
  strings. Ties keep the first found (windows from the lowest, strings from string 1: muted, open, then frets up).

| type | intervals | | type | intervals |
|---|---|---|---|---|
| `maj` | 0 4 7 | | `aug` | 0 4 8 |
| `min` | 0 3 7 | | `6` | 0 4 7 9 |
| `7` | 0 4 7 10 | | `m6` | 0 3 7 9 |
| `maj7` | 0 4 7 11 | | `dim7` | 0 3 6 9 |
| `m7` | 0 3 7 10 | | `m7b5` | 0 3 6 10 |
| `sus2` | 0 2 7 | | `7sus4` | 0 5 7 10 |
| `sus4` | 0 5 7 | | `add9` | 0 4 7 2 (the ninth) |
| `dim` | 0 3 6 | | `5` | 0 7 |
| `mM7` | 0 3 7 11 | | `7#5` | 0 4 8 10 |
| `maj7#5` | 0 4 8 11 | | `mM7b5` | 0 3 6 11 |
| `7b5` | 0 4 6 10 | | `b5` | 0 4 6 (symbol `C(b5)`) |

The first eight are the default set. In E standard: E 022100, Am x02210, C x32010, D xx0232, G 320003, A x02220,
Em 022000, Dm xx0231, F (root on 6, fret 1) 133211, E7 020100, A7 x02020, C7 x32310, Cmaj7 x32000, Am7 x02010,
Asus4 x02230; up the neck A on string 6 577655 (E shape), Bm on string 5 x24432 (A shape), G on string 4 xx5787
(D shape). Drop D: D on string 6 000232. `performer/test_voicing.py` holds the full list. The last six types are
the qualities seven-note scales give besides the first sixteen (chords in key, below).

**Chords in key.** A program may offer the key's own chords (`chords.diatonic_chord(scale, root, seventh)`; APC64
Control: the chord types `key` and `key 7`, the key being the layout's scale). A seven-note scale's thirds are
stacked from the root pressed: degrees 1-3-5 of the scale counted from it (a triad), or 1-3-5-7 (a seventh). The
chord is named by its intervals: the type of the table that has them (C major: C maj, D min, B dim; sevenths Cmaj7,
Dm7, G7, Bm7b5; A harmonic minor: AmM7, Bm7b5, Cmaj7#5, Dm7, E7, Fmaj7, G♯dim7), else a type named by its degrees
above the root, a major third and a perfect fifth left out (`(2,b5)`). Strict: a root outside the scale has no chord
(it plays nothing), nor does a scale of another size (a pentatonic has no thirds to stack). The voicing is then
built as for any type.
