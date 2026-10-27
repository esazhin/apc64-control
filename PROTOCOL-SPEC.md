# Akai APC64 control protocol: spec for a Linux DAW-mode host (contract 1) and editor (contract 2)

Tags: **[LIVE]** = observed on a real unit (firmware 1.2.1.6) on 2026-10-22, with the capture in
`fixtures/` (serial numbers masked); **[CODE]** = read from Bitwig's MIT-licensed APC64 extension
(`bitwig-extensions`, `.../akai/apc64/` and `.../akai/apc/common/`) or from the
disassembly of Akai's *APC64 Project Editor* for Windows; **[TBD]** = unknown, must stay bounded.
Scope tags: **[HOST]** = used by contract 1; **[EDITOR]** = contract 2 only; contract 1 must never send
an [EDITOR] write message (§8).

## 1 · Transport [LIVE]
- USB class-compliant MIDI, USB ID `09e8:0053`. Four ALSA ports on one card; the card/client
  number moves, so always **resolve by name**:
  | Port name (ALSA) | cable | Use |
  |---|---|---|
  | `APC64 DAW (APC64)` | 0 | **all SysEx** (identity, DAW mode, OLED, projects, global) and every DAW-mode surface message. Windows calls this port just "APC64". |
  | `APC64 Notes (APC64)` | 1 | not used by any message seen so far |
  | `APC64 MIDI (APC64)` | 2 | not used by any message seen so far |
  | `APC64 Custom (APC64)` | 3 | Custom-mode pad/strip output (outside DAW mode) |
- ALSA *sequencer* access is shared: several clients can subscribe to the same port at once, so a
  second host (e.g. Bitwig) could talk to the unit at the same time without anyone noticing. ALSA
  *rawmidi* (`hw:<card>,0,0`) is exclusive and returns `EBUSY` while another program (including the
  kernel's sequencer bridge for a subscribed client) holds it. The host's port-ownership policy
  (ask first, never fight for a busy port) depends on this. [CODE: ALSA semantics; EBUSY behaviour with Bitwig running: TBD]

## 2 · Framing and packing [LIVE]
- Akai SysEx: `F0 47 00 53 <cmd> <len_hi> <len_lo> <data…> F7`, length = `(len_hi << 7) | len_lo`
  = number of data bytes. `47` = Akai, `53` = APC64.
- **7-bit packing** (projects and global settings only): groups of 8 bytes, the first holds bit 7 of
  the next 7 bytes (bit *i* ↔ byte *i*); the last group may be short. Verified round-trip exact on
  every dump. Reference implementation: `tools/apc64_project.py` (`pack7` / `unpack7`).

## 3 · Identity [LIVE] [HOST]
Host → `F0 7E 7F 06 01 F7`; unit → `F0 7E 00 06 02 47 53 00 19 <fw0 fw1 fw2 fw3> 00 00 00 00 00
<serial ASCII, NUL-terminated> F7`. On the unit captured here the firmware bytes are `01 02 01 06` = **1.2.1.6**
(newest release) and the serial is 15 ASCII characters (masked as `000000000000000` in `fixtures/`). The host must refuse to enter
DAW mode unless product `53` is seen; it should warn (not refuse) on an unknown firmware version.

## 4 · DAW-mode session [LIVE] [HOST]
1. Host sends `F0 47 00 53 1B 00 01 00 F7`, `F0 47 00 53 19 00 01 00 F7`, `F0 7E 7F 06 01 F7`
   [CODE: Bitwig `start()`]. `1B … 00/01` is a drum-mode flag in Bitwig [CODE]; `19 … <m>` from the
   host requests pad mode *m* [CODE].
2. On the identity reply, host sends **DAW mode on** `F0 47 00 53 1C 00 01 01 F7`. [LIVE]
3. **DAW mode off** `F0 47 00 53 1C 00 01 00 F7`. [LIVE] **If the host exits without sending it,
   the unit stays in DAW mode** (observed after a killed probe) and keeps sending DAW-mode messages
   that nobody reads. The host must send "off" on every exit path (normal stop, SIGTERM, release).
4. No on-device "Ableton" setting is needed: the handshake works with Global Menu *Device Mode* set
   to either value. [LIVE: worked with Device Mode = 1 (Standalone) and = 0]
5. Pad-mode reports, unit → host: `F0 47 00 53 19 00 01 <m> F7`, m = 0 Session, 1 Overview [CODE],
   2 Note, 3 Chord, 5 Drum [CODE], 6 Step Seq, 8 Project, 9 Custom. [LIVE for 0,2,3,6,8,9]
6. **Session view (m=0) is host-drawn**: the unit clears it on every mode change, so the host must
   redraw all host-owned LEDs when it receives a mode-0 report. [LIVE] In Note/Chord/Step/Project/
   Custom the **pad grid** (and its LEDs) is the unit's; its played notes go out on the Notes port
   (Note/Chord/Step) or the Custom port (Custom), with velocity and aftertouch, and a host may read
   them there. In Note view the side buttons and strips still report to the host on the DAW port;
   in Custom view they do not. [LIVE 2026-10-23, see §5]
7. Keep-alive: none observed; the unit stayed in DAW mode for minutes with no traffic. [LIVE]
   Behaviour on USB unplug/replug: [TBD] (assume DAW mode is lost; host re-runs §4 on reconnect).

## 5 · Surface input, unit → host, DAW port, DAW mode only [LIVE] [HOST]
Notes are note-on with velocity > 0 on press and note-off (or note-on velocity 0) on release.
Channels below are 1-based.

| Control | Message | Notes |
|---|---|---|
| Grid pads 0–63 | note-on 0–63, **ch 7**, velocity = strike | pad 0 = bottom-left [LIVE in Custom mode; DAW-mode index→position: TBD, assume same] |
| Track-control row (8) | notes 64–71 (0x40+i), ch 1 | |
| Tempo, Clear, Duplicate, Quantize, Fixed, Undo | notes 72–77 (0x48–0x4D) | |
| Strip touch 1–8 | note-on/off 82–89 (0x52+i), ch 1 | [LIVE press; release = note-off: CODE] |
| Play, Rec, Stop | notes 91, 92, 93 | |
| Nav down, up, left, right | notes 94, 95, 96, 97 | |
| Track buttons (8) | notes 100–107 (0x64+i) | |
| Mode Rec Arm, Mute, Solo, Stop | notes 108–111 | |
| Scene buttons (8) | notes 112–119 (0x70+i) | |
| Shift | note 120 (0x78) | the unit does **not** apply Shift: shifted buttons arrive with their normal IDs [LIVE] |
| Strip mode Device, Volume, Pan, Sends, Channel, Off | notes 121–126 | |
| Strip 1–8 position | **pitch bend, channel = strip (ch 1–8)**, 14-bit 0–16383 | [LIVE] |
| Encoder turn | CC 0x5A value 1 = clockwise, 127 = counter-clockwise | [CODE] |
| Encoder press | note 0x5A | [CODE] |
| Pad velocity / aftertouch | Session view: **fixed 127, no aftertouch** [LIVE 2026-10-23]. Expressive playing comes from the unit's own views: Note/Chord → **Notes port** with real velocity and **poly aftertouch** `A0`; Step → Notes port, velocity, no AT; Custom → **Custom port**, velocity, AT per project pad flag [LIVE 2026-10-23, NOTES-daw-mode.md] | |
| Side buttons/strips per view | Note view: all buttons and strips still reach the host on the DAW port [LIVE]. Custom view: Shift (120), Tempo (72), Play (91), Stop (93) and the encoder turn (CC 90, 01 = right / 7F = left, also with Shift) reach the host; arrows (also with Shift), track and scene buttons are silent; strips send project CCs on the Custom port [LIVE 2026-10-24, NOTES-daw-mode.md]. Chord/Step: [TBD], expected as Note | |

Device-local, never reaching the host [LIVE]: the pad-mode buttons (Session/Note/Chord/Step/
Project/Custom; Shift + them opens their config pages) and the Project menu (save / save as).
Shift + grid pads, track buttons, track-control row, scenes 5–8: not yet captured [TBD].
**Outside DAW mode the buttons are silent** on every port; only pads and strips send [LIVE].

## 6 · Surface output, host → unit, DAW port [HOST]
| Element | Message | Status |
|---|---|---|
| Grid pad LED | note-on **ch = behaviour (0–15)**, note = pad, velocity = palette index (0–127) | [LIVE: ch 6 = full brightness, indices 5/9/13/21/37/45/49/53 lit] |
| Behaviour codes | 0 10%, 1 25%, 2 50%, 3 60%, 4 75%, 5 90%, 6 full, 7–10 pulse 1/16, 1/8, 1/4, 1/2, 11–15 blink 1/24, 1/16, 1/8, 1/4, 1/2 | [CODE: `LedBehavior`] |
| Track buttons, track-control row | RGB like pads, note = control ID, ch 0 used by Bitwig | [CODE] |
| Single-LED buttons (scenes, modes, transport, nav, function, strip modes, shift, encoder press) | note-on, note = control ID, **ch = state−1, velocity 1** for states 1–16 (10%…full, pulse, blink); off = note-on ch 0 velocity 0 | [CODE: `VarSingleLedState`] |
| Strip LED colour | CC 0x70+i (112–119), value = palette index | [CODE] |
| Strip LED mode | CC 0x68+i (104–111): 0 off, 1 bar white, 2 bar red, 3 bipolar white, 4 bipolar red | [CODE] |
| Strip position display | pitch bend on ch = strip, 14-bit | [CODE: `FaderResponse`] |
| OLED text | `F0 47 00 53 10 00 <n+2> <row> <n ASCII bytes> 00 F7`, Bitwig pads to 3–14 chars | [LIVE rows 0 and 1; number of rows and max length: TBD, ≤14 safe] |
| OLED backlight | CC 0x59, value = palette index | [CODE] |

**Palette:** velocity/CC colour values index Ableton's 128-colour clip palette [CODE]. The exact RGB
of each index on the APC64 is [TBD]; the UI may use the standard Ableton/Launchpad table as an
approximation and must mark it as such. Bitwig's RGB→index mapping: `ColorLookup.toColor` [CODE].

## 7 · Strip and pad behaviour outside DAW mode (Custom mode) [LIVE]
Pads send note-on/off (and poly aftertouch when enabled) per the project's pad records; strips send
CC (7-bit) or CC MSB+LSB (14-bit) per the strip records (§8.2). The host does not need this, but the
UI replica should show which mode the unit is in.

## 8 · Device configuration [EDITOR] — contract 1 must never send 0x14 or 0x18
### 8.1 Projects [LIVE]
- Read: `F0 47 00 53 13 00 01 <slot> F7` → `F0 47 00 53 14 07 6F <slot> <1006 packed bytes> F7`
  (1015 bytes; 1006 → 880 raw). Write = send that `0x14` message. Slots 0–24 answer; 25+ do not.
- **Slot 0 = the live edit buffer**: equals the loaded project; writing it changes the pads
  **immediately** and marks the project "unsaved" on the unit. Slots 1–24 = saved projects 1–24;
  a write there takes effect when that project is next loaded.
- Raw layout: 64 pad records × 12, then 8 strip records × 14.
  - Pad (pad 1 = bottom-left; factory note = 24 + index): b0 note-in-octave (0–11), b1 poly
    aftertouch (0/1), b2 MIDI channel (1-based), b3 octave, b4–6 rest RGB, b7–9 pressed RGB,
    b10 output bitmask (07 = all; 00 = silent), b11 unknown (preserve).
  - Strip: b0 resolution (1 = 7-bit CC, 2 = 14-bit MSB+LSB), b1 CC (MSB), b2 LSB CC, b3 unknown
    (preserve), b4 MIDI channel (1-based), b5 unknown (preserve), b6–8 bar RGB, b9–11 indicator RGB,
    b12 output bitmask, b13 bipolar display (0/1).
### 8.2 Global settings [LIVE]
Read `F0 47 00 53 17 00 00 F7` → `F0 47 00 53 18 00 40 <64 packed> F7` (56 raw). Write = send the
`0x18` message (verified: change, read-back, restore). Raw: b0–19 unknown u32 values (preserve);
b20 Device Mode (0 Ableton Live, 1 Standalone); b21 Standalone Sync (0 Int, 1 USB, 2 DIN); b22 Sync
Out bitmask (bit0 USB, bit1 MIDI); b23–30 CV1–8 Source (manual §5.6 order); b31–38 CV1–8 Channel
(1-based); b39–54 Drum1–16 note; b55 LED level (0–3 = 25/50/75/100 %).
### 8.3 Not reachable
Note/Chord configuration (root, scale, layout, chord, octave) and the Step Sequencer configuration
are not in any readable block [LIVE: changing root changed nothing]; Akai's editor only knows
0x13/0x14/0x17/0x18 [CODE].
### 8.4 Akai Project Editor files (`.APC64`) [LIVE]
The editor's preset files hold one project. Checked against a real file (`fixtures/Boss RC-600.APC64`,
20 284 bytes); all words little-endian u32:
- file header `2, 0, 0`, then 592 items in index order, the sizes adding up to exactly the end of the file;
- item: `u32 size` (of the whole item), `u32 0`, `u32 index`, then one value node;
- value node: `u32 size` (of the node), `u32 1`, `u32 kind`, payload. Kind 3 = one byte (a 13-byte node);
  kind `0x10` = RGB, a list of three kind-3 nodes (51 bytes).
- Indices 0–511 = 64 pads × 8 fields (note-in-octave, aftertouch, channel, octave, rest RGB, pressed RGB,
  outputs, unknown — one-to-one with pad record bytes 0–11, §8.1); 512–591 = 8 strips × 10 fields
  (resolution, CC, LSB, unknown, channel, unknown, bar RGB, indicator RGB, outputs, bipolar — strip record
  bytes 0–13). An earlier reading had the items flat (kind, 0, index + value); the value is nested in its own
  node, as above.

## 9 · Acceptance scenarios for the host (the user) [HOST]
1. Plug in the APC64 while the service runs: nothing is grabbed; a desktop notification and a UI
   banner ask "Take control of APC64?". Declining leaves the port free; Bitwig keeps working.
2. Accept: the unit enters DAW mode, the OLED shows the host's text, Session-view LEDs show the
   active mapping; the browser shows a replica of the whole unit with the same LED state.
3. Every physical control press, touch, slide, Shift combination and encoder turn appears live in
   the replica and triggers its mapped action; clicking/dragging a control in the replica does the
   same as touching the hardware.
4. Switching the unit to Note/Chord/Step and back to Session restores the host's LEDs within 100 ms.
5. "Release" (button in UI, service stop, SIGTERM, or unplug) always leaves the unit out of DAW
   mode and frees the port, so Bitwig can take it.
6. If the port is busy (another program holds it), the host shows "Busy" and never fights for it.
7. The host never sends a project or global-settings write.

## 10 · Testing
- Hermetic: a simulated APC64 replays `fixtures/` captures (identity reply, DAW-mode surface
  presses incl. strips and Shift, mode reports) and records what the host sends.
- Live (`APC64_LIVE=1 pytest -m live`): may enter DAW mode, draw LEDs/OLED and must leave DAW mode
  at the end; must not send 0x14/0x18.
- Captures: `fixtures/daw-mode-surface-capture-2026-10-22.log`,
  `fixtures/daw-mode-shift-and-strips-2026-10-22.log`, `fixtures/apc64-snapshot-2026-10-22.hex`
  (identity + all 25 project slots), `fixtures/apc64-global-settings-2026-10-22.syx`,
  `fixtures/aseqdump-*.log` (Custom-mode pad/strip experiments).
