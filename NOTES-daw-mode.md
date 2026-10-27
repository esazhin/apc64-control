# DAW-mode (host emulation) — verified 2026-10-22, firmware 1.2.1.6

The unit enters DAW mode from the SysEx handshake alone — no on-device "Ableton" setting needed:
`F0 47 00 53 1B 00 01 00 F7`, `F0 47 00 53 19 00 01 00 F7`, `F0 7E 7F 06 01 F7`, then
`F0 47 00 53 1C 00 01 01 F7` (on) / `… 1C 00 01 00 F7` (off). If the host dies without sending
"off", the unit stays in DAW mode. Everything below is on the `APC64 DAW` port.
Source of message formats: Bitwig's MIT APC64 extension; every row below seen live
(`fixtures/daw-mode-surface-capture-2026-10-22.log`).

| Control | Device → host |
|---|---|
| 64 grid pads | note-on 0–63, ch 7 |
| Track-control row (8) | notes 64–71, ch 1 |
| Tempo/Clear/Duplicate/Quantize/Fixed/Undo | notes 72–77 |
| Play/Rec/Stop | notes 91–93 |
| Nav down/up/left/right | notes 94–97 |
| Track buttons (8) | notes 100–107 |
| Rec Arm/Mute/Solo/Stop mode | notes 108–111 |
| Scene buttons (8) | notes 112–119 |
| Shift | note 120 |
| Strip mode Device/Vol/Pan/Sends/Channel/Off | notes 121–126 |
| Pad-mode change | `F0 47 00 53 19 00 01 <m> F7`: 0 Session, 2 Note, 3 Chord, 6 Step, 8 Project, 9 Custom |
| Pad-mode request (host → unit) | the same frame sent to the unit: **obeyed, not echoed** (2026-10-27, below) |

Host → device: OLED text `F0 47 00 53 10 00 <len> <row> <ascii…> 00 F7` (verified: rows 0/1);
pad LED = note-on `0x90|behaviour`, note = pad, velocity = Ableton-palette colour (ch 6 = full,
verified). Strip LEDs: CC 0x70+i colour, CC 0x68+i mode (from Bitwig, not yet verified).
Session-view pads are host-drawn: leaving and re-entering Session clears them, so a host must redraw
on the mode-0 report. Note/Chord/Step stay local to the unit and only report the switch.
Strips in DAW mode (verified, `fixtures/daw-mode-shift-and-strips-2026-10-22.log`):
- touch = note-on 82–89 (0x52 + strip index), ch 1
- position = **14-bit pitch bend, channel = strip** (E0 … E7 for strips 1–8), 0–16383
  (Custom mode instead sends 7-bit CC, or MSB+LSB CC when the strip's b0 = 2).

Shift (verified): Shift is note 120 and is NOT applied by the device — shifted arrows, Rec Arm/
Mute/Solo/Stop, Tempo…Undo, strip modes, transport and scenes 1–4 all arrive with their normal IDs,
so a host can give each a second function. Device-local, never reaching the host: the pad-mode
buttons (Shift opens their config pages) and the project menu (save / save as); during the pass the
unit switched itself to Project mode (`19 00 01 08`) right after Shift + scene 4. Not covered:
shifted grid pads, track buttons, track-control row and scenes 5–8.

**Pad-mode request (verified 2026-10-27).** The unit obeys the host's `F0 47 00 53 19 00 01 <m> F7`: with the
unit in Session view the host sent m = 9 and the unit switched to Custom view. It does **not** report the change
back (no `19 00 01 <m>` follows); it still reports every press of its own view buttons. So the host takes a
request it sent as the new view at once, and a later report from the unit overrides it. Verified for 9 (Custom);
0, 2, 3, 6 are the same frame, used by the replica's view buttons, to be confirmed one by one; 1 Overview and
5 Drum are only [CODE] and not requested. After a requested Session view no report comes to repaint on, so the
host repaints the Session grid itself (at once and again ~150 ms later).

## Global settings (separate from projects) — the Global Menu (manual v1.1 §5.6)
Read: `F0 47 00 53 17 00 00 F7` → `F0 47 00 53 18 00 40 <64 packed bytes> F7` (56 raw bytes).
**Write = send the same `0x18` message: verified 2026-10-22** (LED level changed and restored,
read-back exact). Backup of the pre-write block: `fixtures/apc64-global-backup-before-write.bin`.

| Raw bytes | Value (2026-10-22) | Meaning | Status |
|---|---|---|---|
| 0–19 | u32 LE: 5, 35, 150000, 52500, 60000 | not in the Global Menu (internal/calibration?) | unknown — preserve |
| 20 | 00 | Device Mode: 0 = Ableton Live, 1 = Standalone | **verified live** |
| 21 | 00 | Standalone Sync: 0 Internal, 1 USB, 2 MIDI-DIN | **verified live** |
| 22 | 00 | Sync Out bitmask: bit0 = USB, bit1 = MIDI | **verified live** |
| 23–30 | 00 03 00 03 00 03 00 03 | CV1–8 Source, index into manual §5.6 list (0 Pitch-Last, 1 Pitch-Low, …, 3 Gate-Last …) | **verified live** (CV1 0→1) |
| 31–38 | 01 01 02 02 03 03 04 04 | CV1–8 Channel, 1-based | **verified live** (CV1 1→2) |
| 39–54 | 24…33 | Drum1–16 Note (36–51) | inferred (values = manual defaults) |
| 55 | 03 | LED Level 0–3 = 25/50/75/100 % | **verified live** (menu and write) |

Not exposed over SysEx at all (verified: changing the Note/Chord root on the unit changed neither
the global block nor the live project): **Note/Chord configuration**, and very likely the Step
Sequencer configuration. Akai's editor only knows 0x13/0x14 (project) and 0x17/0x18 (global), so
those settings stay device-only.

## Pad velocity/aftertouch and buttons per view, in DAW mode (verified 2026-10-23)
Fixtures: `daw-mode-session-velocity-2026-10-23.log`, `daw-mode-views-velocity-aftertouch-2026-10-23.log`,
`daw-mode-buttons-in-note-and-custom-view-2026-10-23.log`. DAW mode on throughout; views switched
with the unit's own view buttons (they only produce the `19 00 01 <m>` report).

| View (m) | Pads arrive on | Velocity | Aftertouch | Side buttons + strips |
|---|---|---|---|---|
| Session (0) | DAW port, notes 0–63 ch 7 | **fixed 127** (soft/hard presses all 7F) | none (10 s squeeze sent nothing) | all reach the host (DAW port) |
| Note (2) | **Notes port**, ch 1 | **real** (0x0B–0x7F seen) | **poly AT** `A0 nn vv`, continuous | **all reach the host**: track-ctl 64–71, track 100–107, arrows, 108–111, Shift, 72–77, strip modes 121–126, scenes 112–119, strip touch 82–89 + 14-bit pitch bend |
| Chord (3) | Notes port, 3 notes per pad | real, shared by the chord's notes | poly AT per chord note | (not re-checked; expected as Note) |
| Step (6) | Notes port | real (0x12–0x6E) | none seen | (not checked) |
| Custom (9) | **Custom port**, project's note/channel | real (0x0B–0x7F) | none (pad's project AT flag off in this project) | **buttons silent** except Shift (120) and note 72; **strips send CC on the Custom port** (project CCs), not pitch bend |

Mode report 6 is Step (confirmed at the unit: "it was the sequencer mode"). Drum (5 [CODE]) not tested.
Consequence: expressive playing exists in DAW mode, but the unit generates it in Note/Chord/Step/
Custom views on the Notes/Custom ports; Session-view pads are fixed-velocity triggers. In Note/Chord
(and probably Step) view every side button and strip still belongs to the host.

## Custom mode buttons (verified 2026-10-22)
Outside DAW mode the ~50 buttons around the grid (track, scene, track-control, Tempo…Undo, arrows,
transport) send **nothing** on any port; only pads and strips send MIDI. DAW mode is the only way
to use them.

## Custom view under DAW mode: what reaches the host (verified 2026-10-24, amidi on all four ports)
Two probes (DAW handshake, unit switched to Custom view, mode report `19 00 01 09`); the project loaded was
the unit's current one.
- **Reach the host (DAW port):** Shift (120), Tempo (72, `90 48`), Play (`90 5B`), Stop (`90 5D`), and the
  **encoder turn**: `B0 5A 01` per detent right, `B0 5A 7F` per detent left, also while Shift is held.
- **Silent:** all four arrows (plain and with Shift held), track button 1, scene button 1, encoder press
  (one press, nothing seen; recheck before relying on it).
- **Custom port:** strip 1 = `B0 10 00..7F` (project CC 16, 7-bit); pad = `90 18 vv` with real velocity
  (`26`, `3B`). Shift + pad: Shift arrives on the DAW port, and the pad note still arrives on the Custom
  port, so a host that reads the Custom port can treat Shift + pad as a command and not forward the note.
- **Rechecked 2026-10-27 (amidi on all four ports, every button):** in Session view all 8 track buttons
  (100–107), all 8 track-control buttons (64–71) and all 8 scene buttons (112–119) reach the host; after the
  unit reported Custom view (`19 00 01 09`) the same 24 presses sent nothing on any port, and only Shift (120)
  still arrived. In Custom view those buttons cannot carry commands; Shift + pad can.
- Corrects the 2026-10-23 table, which listed only Shift and 72 (Play and Stop were not pressed then).

## Slot-0 writes under DAW mode in Custom view (verified 2026-10-25, contract 2 a1–a4)
Spike `tools/spikes/slot0_spike.py` (the unit's raw `/dev/snd/midiC<card>D0`, codec from `tools/apc64_project.py`), log in
`fixtures/slot0-under-daw-mode-spike-2026-10-25.log`. DAW handshake, the user switched to Custom view (mode 9),
slot 0 backed up, then:
- **a1 — accepted.** A 0x14 slot-0 write under DAW mode changed the pads at once: pad 1 turned magenta and
  pad 2 took `01 7F 80` (seen as cyan). Read-back 0.5 s later: **0 bytes differ** from the intended record.
- **a3 — read-back is byte-exact**, odd RGB values included (no normalisation).
- **a2 — 10 back-to-back writes** (queued in 9 ms, no read-back between) were all accepted. The pad ended on
  the last colour (cyan), and the read-back equalled the last record. No flicker was reported.
- **a4 — no override.** A DAW-port LED note-on (`96 00 05`, pad 0 red) sent in Custom view did **not** change the
  pad (it stayed cyan).
- Restore: read-back equals the backup byte for byte, the pad went back to white, and DAW mode was switched off.
Still open: a6 (whether the edit buffer survives a power cycle / flash wear) and a16 (per-pad aftertouch flag).
