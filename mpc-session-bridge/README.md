# MPC Session Bridge — APC64 → MPC Clip Matrix, standalone

A drop-in **MPC controller script** that turns an **Akai APC64** into a full Ableton-style **Session View**
for the **MPC's Clip Matrix**, running *on the MPC itself* — no computer, on **stock MPC OS 3.10.1**.

Launch clips and scenes from the 8×8 grid with true-colour LED feedback, select tracks, mute/solo/record-arm,
stop clips, stop-all, and scroll the clip window with the arrows — the clip matrix aperture is driven directly
from the pad surface.

> **Relation to the rest of this project.** The [APC64 Control](../README.md) *Host* hosts the APC64 from a
> Linux box and routes it anywhere. **This is the opposite architecture**: the APC64 stays in its own DAW
> ("Ableton") mode and talks straight to the MPC as a native Akai controller script — **no host, no computer,
> no cables beyond USB**. Same unit, same DAW-mode protocol (learned from Bitwig's MIT extension and this
> project's [`PROTOCOL-SPEC.md`](../PROTOCOL-SPEC.md)), different target.

---

## Status

| Feature | State |
|---|---|
| Clip launch (8×8 grid) | ✅ |
| Scene launch (right column) | ✅ |
| Stop clip (track-control row, Stop mode) | ✅ |
| Stop-all (Shift + Stop, or Shift + bottom scene) | ✅ |
| Track select (with colour LEDs) | ✅ |
| Mute / Solo | ✅ (track methods `Mute()` / `Solo()`) |
| Record-arm | ✅ (track member `RecArm`) |
| Grid navigation (both axes) | ✅ (aperture scroll) |
| True clip/track colours | ✅ (full 128-colour palette + per-colour overrides) |
| Stray-sound suppression | ✅ (all ch-0 notes consumed) |
| **Channel strip / 8 faders** | ❌ **impossible on stock** — see [Limitations](#limitations-the-faders) |
| MPC-view-follows-APC (bidirectional sync) | ⏳ parked (one-way today: APC drives) |

Everything here is **runtime-only and reboot-reversible** — it lives in a RAM overlay, the MPC's read-only
rootfs is never written, and a reboot clears it.

---

## How it works

```
   APC64 (DAW "Ableton" mode)                 MPC Live III (stock, standalone)
   ┌─────────────────────────┐   USB MIDI     ┌───────────────────────────────────┐
   │ 8×8 grid, scenes, track  │  notes / CC /  │  apc64Session.lua  (controller    │
   │ buttons, transport, nav  │ ─────sysex────▶│  script, Lua 5.4 / sol2)          │
   │                          │                │    │                              │
   │ LEDs (RGB + single)      │ ◀───notes/CC───│    ├─ mpc.clipMatrixAperture  ────┼─▶ Clip Matrix
   │                          │                │    ├─ mpc.tracks.normalTracks  ───┼─▶ mixer (mute/solo/arm)
   │ 8 faders → PITCH BEND ───┼──✗ dropped ✗──▶│    └─ mpc.sequencer  ─────────────┼─▶ transport
   └─────────────────────────┘                └───────────────────────────────────┘
```

- The script registers for the APC64's DAW-mode notes/CCs and translates them into the **MPC Lua controller
  API**: `mpc.clipMatrixAperture` (`SelectClip` / `TriggerClip` / `TriggerRow` / `StopClipsOnTrack` /
  `SelectTrack` / `MoveTo` …), `mpc.tracks.normalTracks[i]` (`.Mute()`, `.Solo()`, `.RecArm`, `.Volume`,
  `.Colour`), and `mpc.sequencer` (`TogglePlayStart` / `Stop` / `Record`).
- On load it detaches the aperture from the MPC touchscreen (`SetFollowsTUIActiveMatrix(false)` +
  `SetFollowsTUI(false)`) so the **APC arrows** scroll the clip window independently, then `MoveTo(col,row)`
  pans it.
- **LEDs** use the APC64's DAW-mode encodings: single-LED buttons `SendMIDINoteOn(0, note, code)`; RGB pads
  `SendMIDINoteOn(behaviourChannel, note, colourIndex)`.

### Colours

The APC64's LED palette is the standard **Launchpad / Ableton "Live" 128-colour palette** (velocity = palette
index) — verified on the device by tapping a calibration swatch (index 1 = grey, 3 = white, 17 = lime,
32 = cyan, 53 = magenta all matched the published table). The full 128-entry RGB table is embedded as `PAL`,
and `colorIndex()` maps a clip's packed-`0xRRGGBB` colour to the **nearest** palette velocity, so any MPC clip
colour renders truthfully.

A small `OVERRIDE` table pins specific MPC colours to hand-picked velocities where perceptual nearest-match
disagrees with taste (e.g. the violet/grape region, which RGB distance collapses toward magenta). To tune a
colour: press **Quantize** to show the swatch, tap the pad you want, read `velocity = N` off the OLED, and add
`[0xRRGGBB] = N` to `OVERRIDE`.

---

## Deploy

### Prerequisites (once per boot, on the MPC)

1. **Developer-mode SSH:** Preferences → Info → tap *version* ×3, *serial* ×2, *firmware* ×1. Root login, no
   password.
2. The APC64 connected by USB and manually switched into its **DAW / MPC (Session)** mode.
3. In the MPC: Preferences → MIDI, enable **Control** for the APC64 DAW port. (This persists across restarts.)

### Sign + push

```sh
./deploy.sh                      # sign, deploy, restart the MPC app
./deploy.sh --no-restart         # sign + deploy only
./deploy.sh --ip 192.168.x.y     # target a different unit (default is in the script)
```

`deploy.sh`:

1. **Signs** the `.lua` (see below) and writes the checksum into `apc64Session.ini`.
2. Pushes the `.ini` + `.lua` into a RAM staging dir on the device (`/tmp/devices-akai`).
3. **Bind-mounts** that dir over `/usr/share/Akai/SME0/Devices/Akai` (re-creating it if a reboot cleared it),
   so the stock read-only rootfs is never modified.
4. Restarts the MPC app (`systemctl restart acvs`) so it re-scans scripts — **this drops the open project,
   so save first**. After the restart, re-enter DAW mode on the APC.

### The signature

The MPC validates each controller script against a checksum in its `.ini`. The algorithm (recovered from the
MPC binary, verified against Akai's own `mpkMini*` scripts):

```
checksum = SHA-256( <raw .lua bytes>  +  "a36d63a8-9cba-6246-9ef1-d573331c5419" )
```

The salt is a fixed string embedded in `/usr/bin/MPC`. `deploy.sh` computes and inserts it automatically; you
only need it if you sign by hand.

---

## Controls

| Control | APC64 note(s) | Action |
|---|---|---|
| Clip grid | `0x00–0x3F` | select + launch clip; **Shift+tap** = probe (OLED shows raw colour/state) |
| Scenes | `0x70–0x77` | launch row; **Shift + `0x77`** = stop all |
| Track select | `0x64–0x6B` | select track (lit in track colour; white = selected) |
| Track-control row | `0x40–0x47` | Stop-clip / Mute / Solo / Rec-arm per the active mode |
| Mode buttons | Stop `0x6F`, Mute `0x6D`, Solo `0x6E`, Rec `0x6C` | set what the track-control row does |
| Nav arrows | `0x5E–0x61` | scroll the clip window (both axes) |
| Transport | Play `0x5B`, Rec `0x5C`, Stop `0x5D` | play/record/stop; **Shift+Stop** = stop all clips |
| Shift | `0x78` | modifier |
| Quantize | `0x4B` | toggle the colour-calibration swatch |

---

## Limitations: the faders

The 8 touch-faders **cannot** drive the MPC on a stock unit, and this is now proven on both ends:

- The faders transmit **14-bit pitch-bend on channels 1–8** (captured off the device with `amidi`; Bitwig
  binds them the same way via `createAbsolutePitchBendValueMatcher`). This is the Ableton DAW-control
  convention for faders.
- The MPC can't receive pitch-bend **two independent ways**: the Lua controller API exposes only
  `HandleMIDINoteOn/NoteOff/CC/Sysex/Timer` (no pitch-bend handler, and the mapping registrar routes only
  notes + CCs), **and** the native MIDI-Learn source types are only Toggle/Momentary/Fixed-button, Note,
  Abs-CC and Rel-CC — no pitch-bend.
- Akai's own `mpkMini*` scripts confirm the pattern: pitch-bend is routed to the **sound engine** (to bend a
  note's pitch), never to a controller script. CC goes to scripts; pitch-bend does not.

The faders only emit **CC** in the APC64's **Custom** mode — but Custom mode silences the scene/track/transport
buttons, so it can't coexist with the DAW-mode grid this script relies on.

**Possible future paths** (both beyond a stock controller script):

- A **PB→CC proxy daemon** on the MPC's Linux that sits in front of the APC64 port, rewrites the fader
  pitch-bend to CC, and presents the MPC a virtual port. Runtime-only/reversible, but it's custom software,
  not a controller script.
- The **APC64 Control Host** (this project's other half) hosting the unit from a computer, where pitch-bend is
  trivially received and re-routed.

A partial, fully-stock alternative that *does* work: the APC64's **encoder** (CC 90) reaches the script, so it
can drive the **selected** track's Volume/Pan/Send with the strip-mode buttons switching the target. Not
implemented yet.

---

## Files

| File | What |
|---|---|
| `apc64Session.lua` | the controller script (~530 lines) |
| `apc64Session.ini` | device/port manifest + checksum (rewritten by `deploy.sh` at sign time) |
| `deploy.sh` | sign + push + bind-mount + restart |

Tested on an MPC Live III (Gen2, aarch64) running stock MPC OS 3.10.1 with an APC64 over USB.
