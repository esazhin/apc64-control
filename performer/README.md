# performer

Strumming and fingerpicking patterns played over what is held: a pure, deterministic core with no MIDI port, no
thread and no clock of its own, in the Python standard library only. It knows nothing of the APC64; APC64 Control
drives it (its lab's performer), and other programs may too.

The pattern format, the engine's rules and the canonical data are specified in
[`docs/performer-format.md`](../docs/performer-format.md), with the schema
[`docs/performer.schema.json`](../docs/performer.schema.json).

## Use

```python
from performer import Performer, parse_pattern

pattern = parse_pattern({"name": "Arp", "step": "1/8",
                         "lanes": {1: ". . . x", 2: ". x . .", 3: "x . x ."}, "manual": [4, 5, 6]})
player = Performer(pattern, bpm=96, opens={6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64})

player.press(lane=3, note=55, velocity=100, t=0.0)    # the pattern starts here, at step 1
player.press(lane=5, note=45, velocity=90, t=0.0)     # a manual lane: through at once
for event in player.advance_to(0.0):                   # Event(time, kind, lane, note, value, source)
    ...
when = player.next_time()                               # sleep until then, then advance_to(when)
```

- `parse_pattern(data)` takes JSON-compatible data (a YAML or JSON file the caller read) and gives a `Pattern`, or
  raises `PatternError` whose `issues` each carry a `path` into the data (`("lanes", "2")`), the problem and the
  fix; `issue.text(file, line)` renders `travis.yaml line 6, lane 2: 7 steps; length is 8; …`. `check_pattern`
  answers `(pattern or None, issues)` instead. `to_data(pattern)` gives the canonical data back.
- `Performer(pattern, addressing="strings" | "voices", opens=…, bpm=…, latch=…, play=None | "all" | "pressed",
  catch=0.03, seed=0, chord_root=None)` (`play`: the pattern's own mode unless given); inputs `press`, `release`,
  `aftertouch`, `press_chord` (several presses at one time, held before the first hit), `set_tempo`,
  `set_pattern`, `set_play`, `set_latch`, `set_muted`, `stop`, `end_held`, `silence`,
  each with its time `t` in
  seconds; output `advance_to(t)` and `next_time()`; `state(t)` gives the running flag, the step playing, the latch
  and what is held. Times never go back.
- `ClockFollower` measures the tempo of a MIDI clock (24 ticks a quarter) from the ticks' arrival times: the slope of
  the last four beats of ticks, held until it moves more than 0.2 BPM, a real change followed within about a beat.
- **Chord-aware lanes** (spec section 10): a pattern may write lanes `R` (the chord's root string) and `A` (its
  alternate bass) beside 1…N, and in `play: all` an unpressed string below the root string stays silent. The root
  comes from `chord_root` (notes → pitch class or None): `Performer(…, chord_root=my_recognition)`, by default
  `performer.chord_root`. `set_muted(strings, t)` marks strings that never ring open (a voicing's x);
  `state(t).root` is the root string.
- **Voicings** (spec section 11): `build_voicing(opens, root, string, "m7")` → a `Voicing` (one note per string or
  muted, `shape()` 'x02010'); `CHORD_TYPES` (`maj`, `min`, `7`, `maj7`, `m7`, `sus2`, `sus4`, `dim` and more),
  `DEFAULT_TYPES`, `chord_type(name)`.

```python
from performer import Performer, build_voicing

voicing = build_voicing({6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}, root=45, string=5, chord="m7")   # x02010
player.set_muted(voicing.muted, t=1.0)
for string, note in voicing.sounding.items():          # held as if fretted, one press per string
    player.press(string, note, velocity=100, t=1.0)
```

## Layout

| file | what |
|---|---|
| `pattern.py` | the format: `Pattern`, `parse_pattern`, `Issue`, `to_data`, the grid notation |
| `engine.py` | the engine: `Performer`, `Event`, `PerformerState` |
| `clock.py` | `ClockFollower` |
| `chords.py` | `CHORD_TYPES`, `DEFAULT_TYPES`, `chord_type`, `chord_root` |
| `voicing.py` | `build_voicing`, `Voicing` |
| `test_*.py` | every rule with exact times; `test_isolation.py` keeps the package standard-library only |

Tests: `python -m pytest performer` (the project's gate runs them).
