# Intent Delivery Contract

> | meta | |
> |---|---|
> | run | `contract 1` |
> | id | `apc64-host` |
> | created | `2026-10-23` (stamp at fill time) |
> | status | draft \| **locked** \| delivered \| verified |
> | supersedes | `<prior run(s), if any>` |

> **Published as a design record.** This is the delivery contract the first version of the APC64 Host (contract
> 1) was built against (locked 2026-10-23): the agreed behaviour, acceptance criteria and binding design. It is
> kept as written apart from removing machine-specific details (the owner's name, host name, paths, card numbers
> and private notes it cited, which are named here as "the stakeholder's brief" or "the build log (not
> published)"). The project has moved on since:
>
> - Settings live in `config.local` (KEY=VALUE, overridden by the environment; see `config.local.example`); the
>   page and API default to port 5058 and every key is an `APC64_*` name.
> - After delivery the replica became the unit's top panel (scaled to fit, unit-owned views, a folding nav bar, a
>   hideable card column with the overview beside the surface by default), and the sequencer adapter connects to
>   a target before sending and notices ports that appear after start-up.
> - Contract 2, the layout lab ([delivery-contract-lab.md](delivery-contract-lab.md)), added module seams to this
>   core, all additive: module hooks and ports, an issuer-scoped outbound gate for the lab's guarded writes,
>   module actions on the encoder and Tempo, module-owned layout sections, WebSocket topics, a module-panel
>   registry on the page and module subcommands of `apc64`. The rule that the host never writes the unit's memory
>   now reads: only the lab's guarded path does.
> - The live-session follow-ups added help overlays (the small **?** buttons), a Play/Inspect hint line under the
>   toolbar, and an OLED that fits its box at every size.
> - **Amendment 2026-10-27, the pad-mode request** (p6, p7, d43): the unit obeys the host's pad-mode request
>   `19 00 01 <m>` but never reports the change back (verified live). The host therefore takes a request it sent
>   while holding the unit as the unit's view at once (as if reported; the unit's own reports still override it)
>   and repaints a requested Session view itself. The replica's Session, Note, Chord, Step and Custom buttons
>   now switch the unit through it (`POST /api/control/view <x>/press`; 409 while not held); Project stays the
>   unit's own.
> - **Amendment 2026-10-28, the performer** (contract 2 §2.10), additive seams: a module may take what is played on
>   the Notes or Custom port instead of the router (`take_played`; the held note's play event is still published)
>   and play notes back through the layout's routing rule (`NotePlayer.perform`, events from a `PERFORMER` play
>   source that is not harmony input); the sequencer can listen to a port's MIDI clock with arrival times. Without
>   such a module, routing is unchanged.
>
> [README.md](../README.md), [docs/api.md](api.md) and [PROTOCOL-SPEC.md](../PROTOCOL-SPEC.md) describe the
> current state.

---

## 0 · Sections guide — how to read this document

This contract is the agreed scope of one delivery: what will be built, how it will be judged, and the
design the build follows. **§1–§5 state the agreement** — the problem, the solution direction and the
properties it guarantees, the working context, the plan with its acceptance criteria, and the runbook.
**§6–§7 are the derived build plan and binding design**; **§8 is appended when the delivery completes.**

A build that WALKS this contract reads five forms out of it, and reads nothing else about its
structure. They are prose within the frozen headings and table columns below; a contract missing one
is returned to review naming the row rather than half-planned.

1. Section role. Directly under a heading, one line `Role: binding — <why>` or
   `Role: informational — <why>`. Binding sections are carried to the builder IN FULL; informational
   ones are carried by pointer only. A contract stating no roles gets the default binding set
   (§2.5, §3.5, §4.2, §6.1, §7, §7.2) and a loud note that the default was used.
2. Task-row ownership. In §6.1's `design_refs` column: `OWNS: <paths>; TOUCHES: <paths>;
   BINDS: <seam>:<from|to>, …; DISCHARGES: <acceptance ids>; WIRES: <seam ids>` — semicolon-separated,
   any clause omitted when empty. This is where a seam SIDE is attached to the task that owns it;
   free-prose name matching across the §7.2 from/to columns is not a substitute. `WIRES` names the
   seams a task composes (both of their sides this design's): its piece proves each is wired.
3. Acceptance-row identity. In §4.2's first column: `<row id> · <sub-outcome id>` — the row's OWN
   stamped id first, then the sub-outcome it realizes. Several rows share a sub-outcome; only the
   row id can be discharged by exactly one task.
4. Artifact line. In §7's `layout`, one line per module: `` - `path` — responsibility — layer: <layer> ``
   where layer is one of contract / domain / application / infrastructure / wiring / presentation / edge / document.
   The layer is what orders the build inward-first.
5. Size bound. In §7, one line `Size bound: <n> artifacts per unit.` — a task row naming more splits
   mechanically, each split keeping its own seam sides and acceptance rows.

Reviewing: **§4.2 (Acceptance) and §7.2 (Seams) are the heart** — every §4.2 row is an observable
behaviour the delivery must demonstrate, and every §7.2 row is an internal connection a test must
actually execute. Place corrections at the specific row or clause they concern — the section structure
itself is fixed.

| Section | Purpose | How to read |
|---|---|---|
| §1 Intent | the problem & why | confirm the right thing is being solved |
| §2 Solution | the resolution *(direction, not mechanism)* | §2.1 = the established knowledge it stands on, with its verification (may be none) · §2.4 = the properties that must hold · §2.5 = the stated hows and the exclusions |
| §3 Context | code · layout · environment | where the work happens |
| §4 Plan | sub-outcomes + acceptance | **§4.2 = how the delivery is judged** |
| §5 Execution notes | the runbook | how the build proceeds |
| §6 Implementation Plan | ordered task breakdown | the work, in order |
| §7 Final Design Guide | the binding design | what will be built · **§7.2 = every connection to prove** · §7.3 = each connection's clauses · §7.4 = how each acceptance row recomposes from the connections |
| §8 Downstream | delivery self-report | appended at completion |

---

## 1 · Intent
Role: informational — the problem and its why; the builder is aware of it and never acts on it.
- **outcome:** The user wants their Akai APC64 controller to be fully usable from their Linux machine without Ableton Live: a service that, only when the user allows it, puts the APC64 into its DAW ('Ableton') mode and acts as its host. Every pad, button, touch strip (14-bit) and the encoder can be mapped by data to MIDI messages on any MIDI port, with maximum flexibility: named layouts, each with up to 8 pages of pad and button bindings selected by the scene buttons, up to 6 banks of strip bindings selected by the strip-mode buttons, a Shift layer on every bindable control, momentary and latching-toggle bindings, and layouts switchable from the hardware (Shift + encoder, names on the OLED). The pad/button/strip LEDs and the OLED show state, including state fed back by incoming MIDI. The user will not program layouts by hand: they build them at a high level by asking an AI agent (for a particular project, or for theory and harmony work), so layouts must be easy for an agent to write correctly and to apply: a short, readable, validated layout format (devices named once, range forms, human names, a schema and a worked-example guide), precise validation errors, hot reload with automatic rollback copies, and a documented local command-line tool and API through which an agent can list ports and layouts, validate, load and switch layouts/pages/banks, read state and watch what the user plays. The pads must stay expressive: Session-view pads are fixed-velocity triggers, but in the unit's own Note, Chord and Step views it sends real velocity and polyphonic aftertouch on its Notes port (and velocity on its Custom port in Custom view) while, in Note view, every button and strip still reports to the host; so the host reads those ports while it holds the unit and routes what the user plays per layout (target device and channel, velocity untouched, aftertouch passed, converted or dropped, optional transpose or note remap), and shows it in the replica, the activity list and the agent's play stream. A browser page reachable on their home network (no login; it is just a MIDI device) shows a live, clickable replica of the whole physical unit that mirrors every press and LED and makes all that flexibility discoverable: every control labelled with what it does right now; the current layout/page/bank/Shift always visible and navigable; Shift previews; a per-control detail card; an overview of every page and bank; a live list of the actions sent; validation errors shown plainly; learn-by-touching a control; and quick single-control tweaks saved back to the layout. It must never fight another program (e.g. Bitwig) for the unit: it asks before taking it, backs off if the port is busy, and always leaves DAW mode and frees the port when released, stopped or unplugged. It must never write the unit's own project or global-settings memory (that is a later, separate layout lab built on this same core, so the core must be extensible without rewrite).
- **riskiest assumptions — validate first:** –

## 2 · Solution
Role: informational — the resolution's direction and the reasoning behind it.
### 2.1 Priors
| id | claim | verified | how to verify |
|---|---|---|---|
| p1 | The APC64 exposes four ALSA MIDI ports on one card: DAW, Notes, MIDI and Custom. The card/client number moves, so ports must be resolved by name. All SysEx and DAW-mode surface traffic use 'APC64 DAW (APC64)'. (source: PROTOCOL-SPEC.md §1; run environment) | yes — In this run `amidi -l` listed hw:<card>,0,0 'APC64 DAW (APC64)', hw:<card>,0,1 'APC64 Notes (APC64)', hw:<card>,0,2 'APC64 MIDI (APC64)' and hw:<card>,0,3 'APC64 Custom (APC64)', all on one card ('APC64'). PROTOCOL-SPEC.md:12 says 'resolve by name' because the card number moves, and the §1 table routes all SysEx and DAW-mode traffic to 'APC64 DAW (APC64)'. | Run `amidi -l` and `cat /proc/asound/card*/id`; read PROTOCOL-SPEC.md:10-21. |
| p2 | The unit runs firmware 1.2.1.6. The identity reply carries product byte 0x53 and the firmware and serial bytes. (source: PROTOCOL-SPEC.md §3) | yes — Every DAW-mode fixture starts with identity reply 'F0 7E 00 06 02 47 53 00 19 01 02 01 06 …': product 0x53, firmware bytes 01 02 01 06. PROTOCOL-SPEC.md:34 decodes these as 1.2.1.6, and §3 says refuse unless 53 and warn on unknown firmware. | `grep -m1 'F0 7E 00 06 02 47 53' fixtures/daw-mode-views-velocity-aftertouch-2026-10-23.log`; read PROTOCOL-SPEC.md:32-36. |
| p3 | DAW mode is entered by a SysEx handshake (1B, 19, identity request, then 1C 01) and left with 1C 00. No on-device setting is needed. If the host dies without sending 'off', the unit stays in DAW mode. (source: PROTOCOL-SPEC.md §4) | yes — PROTOCOL-SPEC.md:39 gives the handshake 1B / 19 / identity request, :42 'DAW mode on … 1C 00 01 01', and :43 'DAW mode off … 1C 00 01 00 … If the host exits without sending it, the unit stays in DAW mode'. tools/daw_probe.py:10 turns SIGTERM into exit, and :65 sends 1C 00 in the finally-block. | Read PROTOCOL-SPEC.md:39-46 and tools/daw_probe.py:9-10, 52-66. |
| p4 | In DAW mode every surface control reports on the DAW port with known IDs: pads are notes 0–63 on ch 7, buttons are notes 64–126, strips send touch notes 82–89 and 14-bit pitch bend with channel = strip, and the encoder is CC 0x5A plus note 0x5A. The encoder IDs are [CODE] only. (source: PROTOCOL-SPEC.md §5) | yes — PROTOCOL-SPEC.md:65 lists pads as note-on 0–63 ch 7, :74 Shift as note 120, :76 strips as 14-bit pitch bend with channel = strip, and :77-78 the encoder as CC 0x5A / note 0x5A, both tagged [CODE]. fixtures/daw-mode-session-velocity-2026-10-23.log shows pads as '96 00 7F' (ch 7, note 0). | Read the PROTOCOL-SPEC.md §5 table (:59-80) and grep fixtures/daw-mode-surface-capture-2026-10-22.log for '9[0-6] ' and 'E[0-7] '. |
| p5 | The unit does not apply Shift. Shift is just note 120, and shifted controls arrive with their normal IDs. Shift + scene 4 was followed by the unit switching itself to Project mode. (source: NOTES-daw-mode.md) | yes — NOTES-daw-mode.md:34 reads 'Shift is note 120 and is NOT applied by the device', and the same paragraph records that the unit switched itself to Project mode (19 00 01 08) right after Shift + scene 4. PROTOCOL-SPEC.md:74 agrees. | Read NOTES-daw-mode.md:34-40 and PROTOCOL-SPEC.md:74. |
| p6 | Session-view pads are host-drawn and are wiped on every pad-mode change, so the host must redraw on the mode-0 report. Pad-mode reports are SysEx 19 00 01 <m>. (Amended 2026-10-27: a Session view the host requested is never reported, so the host redraws on its own request.) (source: PROTOCOL-SPEC.md §4.5–4.6) | yes — PROTOCOL-SPEC.md:50 reads 'Session view (m=0) is host-drawn: the unit clears it on every mode change, so the host must redraw … on a mode-0 report'. The surface capture holds 'F0 47 00 53 19 00 01 00 F7' reports at 108.741 s and 111.586 s. | Read PROTOCOL-SPEC.md:48-53; `grep '19 00 01 00' fixtures/daw-mode-surface-capture-2026-10-22.log`. |
| p7 | Session-view pads send a fixed velocity of 127 with no aftertouch. Note and Chord views send real velocity and poly aftertouch on the Notes port, Step view sends velocity only, and Custom view sends velocity on the Custom port. In Note view all buttons and strips still reach the host. In Custom view the buttons are silent and the strips send CC. Chord/Step button behaviour is [TBD]. (source: NOTES-daw-mode.md (2026-10-23); fixtures/daw-mode-*-2026-10-23.log) (Amended 2026-10-27: the host can also switch the view itself with the pad-mode request, which the unit obeys without reporting it.) | yes — NOTES-daw-mode.md:69 shows Session as fixed 127 with no aftertouch, :70 Note as Notes port with real velocity and poly AT, and :73 Custom as Custom port with velocity, buttons silent and strips sending CC. Chord/Step buttons are marked 'not re-checked'/'not checked' (:71-72). The session fixture shows only '96 00 7F' presses. The views fixture shows 'Notes 90 35 38', 'Notes A0 35 0A' and velocities 0x0B–0x7F. | Read the NOTES-daw-mode.md table (:66-74); `grep -c ' 7F$' fixtures/daw-mode-session-velocity-2026-10-23.log`; head fixtures/daw-mode-views-velocity-aftertouch-2026-10-23.log. |
| p8 | LED output formats: pad and RGB-button colour is note-on with channel = behaviour and velocity = palette index. Single-LED buttons use channel = state−1. Strip colour and mode use CC 0x70+i and 0x68+i, strip position uses pitch bend, OLED text uses SysEx 0x10 and the backlight CC 0x59. Several of these are [CODE]-only, the palette RGB is [TBD], and the OLED rows/length are [TBD] (≤14 chars is safe). (source: PROTOCOL-SPEC.md §6) | yes — PROTOCOL-SPEC.md:90 reads 'pad LED note-on ch = behaviour, velocity = palette index' [LIVE ch 6]. :93 covers single-LED ch = state−1 [CODE], :94 strip colour CC 0x70+i [CODE], and :97 OLED text SysEx 0x10 [LIVE rows 0 and 1; rows and length TBD]. The palette RGB is [TBD] (§6 Palette). tools/daw_probe.py sends '0x96, pad, colour' and the OLED frame. | Read the PROTOCOL-SPEC.md §6 table (:88-100); tools/daw_probe.py:55-59. |
| p9 | Note/Chord/Step configuration cannot be read over SysEx, so pad positions in Note view cannot be read from the device. (source: PROTOCOL-SPEC.md §8.3) | yes — PROTOCOL-SPEC.md:130 says Note/Chord configuration and the Step Sequencer configuration 'are not in any readable block [LIVE: changing root changed nothing]'. NOTES-daw-mode.md:57 records the same live verification. | Read PROTOCOL-SPEC.md:129-132 and NOTES-daw-mode.md:57-60. |
| p10 | 0x14 (project write) and 0x18 (global write) change device memory. Writing slot 0 takes effect immediately. (source: PROTOCOL-SPEC.md §8) | yes — PROTOCOL-SPEC.md:109 reads 'contract 1 must never send 0x14 or 0x18'. :112 says a write sends 0x14, and :113 says slot 0 is the live edit buffer that changes the pads immediately. :124 says a global write sends 0x18 (verified change and restore). | Read PROTOCOL-SPEC.md:109-126. |
| p11 | ALSA sequencer access is shared, so several clients can drive the unit at once. ALSA rawmidi is exclusive and returns EBUSY. EBUSY behaviour while Bitwig is running is [TBD]. Behaviour on unplug/replug is [TBD]. (source: PROTOCOL-SPEC.md §1, §4.7) | yes — In this run aconnect showed Chrome (128:0 / 129:2-5) subscribed to all four APC64 ports through the sequencer, so the sharing is observed. `amidi -p hw:<card>,0,0` (and 0,1 / 0,3) returned 'Device or resource busy', so the rawmidi exclusivity is observed. Bitwig-specific busy behaviour and unplug behaviour remain [TBD] as the prior states (PROTOCOL-SPEC.md:23, :57). | `aconnect -l \| grep -A4 APC64` then `amidi -p hw:<card>,0,0 -d -t 0.5`; read PROTOCOL-SPEC.md:19-23 and :57. |
| p12 | Proven building blocks already exist in the repo: the pack7 codec and the Device class (python-rtmidi), a minimal DAW host probe that always leaves DAW mode, and real captures from this unit that can drive a simulator. (source: tools/apc64_project.py; tools/daw_probe.py; fixtures/) | yes — tools/apc64_project.py:18 unpack7, :27 pack7, and :64 'class Device' (python-rtmidi, ALSA). tools/daw_probe.py:10 has the SIGTERM handler and :65 sends DAW mode off in its finally-block. fixtures/ holds 13 captures from this unit, including the three 2026-10-23 DAW-mode logs. | `grep -n 'def unpack7\|def pack7\|class Device' tools/apc64_project.py`; read tools/daw_probe.py:9-10, :62-66; `ls fixtures/`. |
| p13 | An earlier project of the author's (a MOTU 828 web mixer, github.com/esazhin/motu-828-mixer) is an existing service with hexagonal layers, simulator-backed hermetic tests, a systemd user unit and launcher, and config.local overrides. (source: the MOTU mixer project) | yes — _motu_mixer/ has the layers domain/, protocol/, application/, infrastructure/ (with simulated_828.py and alsa_rawmidi.py) and presentation/ (api.py, ws_hub.py, static/). deploy/ has motu-mixer.service (ExecStart … -m _motu_mixer) and motu-mixer.desktop. config.local.example is present, and pyproject requires-python >=3.14. | list the MOTU mixer project's `_motu_mixer/` and `deploy/`; read its `deploy/motu-mixer.service:11`. |
| p14 | The APC64 is attached to the host machine (Garuda Linux). Bitwig Studio is installed and may want the unit. Ports 5056 and 5057 are already taken. (source: run environment) | yes — lsusb shows 'ID 09e8:0053 AKAI Professional M.I. Corp. APC64' and amidi lists its card. Chrome's crash annotation reads 'lsb-release=Garuda Linux'. flatpak lists 'Bitwig Studio com.bitwig.BitwigStudio 5.3.13' (installed as a flatpak, not on PATH). The stakeholder's brief says ports 5056 and 5057 are taken; `ss -ltn` showed nothing listening on 5056–5058 at this moment, so they are reserved rather than currently bound. | `lsusb \| grep 09e8`; `flatpak list \| grep -i bitwig`. |
| p15 | A Tonnetz prototype (Web MIDI) already exists. It is the working reference for contract 2's harmony views. (source: prototypes/tonnetz-view/index.html) | yes — prototypes/tonnetz-view/index.html exists (18353 bytes, 2026-10-22) and calls requestMIDIAccess (2 matches). The stakeholder's brief names it as contract 2's working reference. | `ls -la prototypes/tonnetz-view/index.html`; `grep -c requestMIDIAccess prototypes/tonnetz-view/index.html`. |

### 2.2 Summary
- **summary:**
  Every pad, button, strip and the encoder does what the current layout says, and the page always shows what each one does right now.
  Pads stay expressive: in the unit's own Note, Chord, Step and Custom views, velocity and aftertouch arrive at the target device as played.
  A layout the agent writes is live within a second, or it is rejected with a precise error and the previous layout keeps working.
  The host takes the APC64 only when the user says yes, never fights Bitwig, and always hands the unit back out of DAW mode.
  The unit's own projects and global settings are never written.

### 2.3 Ideality — what it optimizes for / deliberately trades
- **Optimizes for:**
  An agent writes one short YAML layout file under layouts/, and it is live on the unit and in the replica within 1 s, or rejected with file:line, control, problem and fix while the previous layout keeps playing.
  Every surface of the browser page shows the same current meaning of every control, because they all read the one resolver: labels, Shift preview, detail card, overview, nav bar and OLED.
  Velocity and aftertouch from the unit's Note/Chord/Step/Custom views reach the target MIDI port exactly as played (or as the layout's aftertouch rule says).
  Bitwig is never disturbed: the APC64 port is held only after the user says yes, Busy is reported instead of shared, and every exit leaves the unit out of DAW mode with the port freed.
  The project and global-settings writes (0x14/0x18) are blocked at the single outbound gate on the device port, not by discipline, yet contract 2 can enable them by adding a module.
  Quick tweaks from the page keep the agent's file readable: ranges, device names and comments stay untouched.
- **Deliberately trades away:**
  Host control of the pad grid and its LEDs in Note/Chord/Step/Custom view: there the unit owns pads and pad LEDs, so the host can only route and display what is played.
  Exact pad positions in the replica outside Session view: they rely on a calibrated map marked as an assumption, because the unit's Note-mode settings cannot be read.
  Sharing the unit with another program at the same time: the exclusive hold means Bitwig and the host never drive it together.
  Taking the unit automatically on plug-in: it waits for the user's yes unless they turn on auto-accept in config.local.
  Protection against anyone already on the home network: there is no login, only the loopback/private-range restriction and the Origin/Host check.
  Page tweaks normalising the file: an overridden range stays in the file with a single-control override beneath it, instead of being rewritten.

### 2.4 Invariants
| id | property | gated_by |
|---|---|---|
| inv1 | For any state (layout, page, bank, Shift held or not), the replica labels, Shift preview, detail card, overview, nav bar and OLED all state the same meaning for each control. That meaning equals what the control sends when pressed in that state. | p5 |
| inv2 | A control with no binding in the current state shows as visibly empty on the page and sends nothing when pressed. | - |
| inv3 | Pressing a scene button selects that page, and pressing a strip-mode button selects that bank. Neither ever sends a bound MIDI action, and the scene and strip-mode LEDs always show the current, defined and empty pages and banks. | p4 |
| inv4 | The host accepts any number of layouts. Each holds up to 8 pages and up to 6 banks, and no other limit applies. | - |
| inv5 | Every layout, page or bank change shows its name on the OLED. Holding Shift and turning the encoder browses layout names on the OLED, pressing the encoder loads the shown layout, and releasing Shift first leaves the current layout unchanged. | p4 |
| inv6 | Every note played in Note/Chord/Step/Custom view while the host holds the unit reaches the layout's target device and channel with the same velocity it was played with. Its aftertouch is passed, converted to channel pressure or dropped exactly as the layout says, and transpose or remap are applied only when the layout asks for them. | p7 |
| inv7 | Each played note appears in the replica, the activity list and the play stream in the order played. | p7 |
| inv8 | After the unit reports a return to Session view, every host-owned LED again shows the current layout's state within 100 ms. | p6, p8 |
| inv9 | Any pad position the replica shows for a note played in Note/Chord/Step view is labelled as calibrated or as an assumption, never as fact. | p9 |
| inv10 | The same incoming messages, layout and reported view always produce the same outgoing messages and the same replica state. | - |
| inv11 | Nothing is ever written to the APC64's Notes, MIDI or Custom ports. | p1 |
| inv12 | The unit is in DAW mode under this host only after a yes for this appearance — from the user on the page or in the desktop notification, or from an agent they instructed through the command-line tool or API — or with auto-accept switched on in config, and only after the unit has identified itself as an APC64 (product 0x53). (corrected by the consistency check: d21 and A22 treat an agent's take request as consent, so the invariant must name it.) | p2, p3 |
| inv13 | While another program holds the APC64 DAW port, the host shows Busy, sends nothing to the unit and keeps the page and API serving. If only the Notes or Custom port is held elsewhere, the host may hold the unit but routes nothing from the busy port. (corrected by the consistency check: 'The APC64 port' was ambiguous, and d26 / A15 define the Notes/Custom-busy case.) | p11 |
| inv14 | After release, service stop, SIGTERM, unplug or any internal failure, the unit's LEDs and OLED are cleared (when it is still connected), the unit is out of DAW mode, and the port is free for another program. | p3, p12 |
| inv15 | No project (0x14) or global-settings (0x18) message ever reaches the unit, and every attempt is refused and logged. | p10 |
| inv16 | When the unit is replugged or the port frees up, the host asks again instead of taking the unit. | p14 |
| inv17 | The APC64 is found by its port name wherever the card number lands. | p1 |
| inv18 | A valid layout file written to layouts/ is live on the unit and in the replica within 1 s of the write. | - |
| inv19 | An invalid or half-written layout file never changes what the unit does. Its errors are shown on the page and returned by the CLI/API, each naming the file, line, control, problem and fix. | - |
| inv20 | Every layout version that went live can be restored, and restoring it makes the unit behave exactly as it did with that version. | - |
| inv21 | A single-control tweak saved from the page changes only that control's meaning. Every other control's meaning, and every untouched line, range and comment in the layout file, stays as it was. | - |
| inv22 | Everything the page can do, an agent can also do through the documented CLI and API, with the same results: list ports and layouts, validate, load, switch layout/page/bank, read state, watch play. | - |
| inv23 | The page, CLI and API work from loopback and the home network with no login, while clients outside the configured private ranges and requests from foreign web origins are refused. | - |

### 2.5 Constraints
Role: binding — the hows the stakeholder stated (Must …) and what this delivery may not do (No …).
- **inherits:** –

| constraint | why |
|---|---|
| Must enter DAW mode and act as host only after the user consents ('ask on detect' via a desktop notification and a UI banner). Auto-accept is a config option, off by default. | stated by the stakeholder in the ask |
| Must back off and report Busy when the port is held by another program. Never fight for the unit. | stated by the stakeholder in the ask |
| Must clear LEDs/OLED, send DAW-mode off and free the port on release, service stop, SIGTERM and unplug. | stated by the stakeholder in the ask |
| Never send project (0x14) or global (0x18) writes, and never write the unit's own memory. | stated by the stakeholder in the ask |
| Never write to the Notes/MIDI/Custom ports and never change the unit's Note-mode settings. | stated by the stakeholder in the run environment |
| Must map every pad, button, 14-bit strip and the encoder by declarative data to MIDI messages on any named MIDI output port, with LED/strip feedback from any named input port. Incoming MIDI drives LEDs and strip bars, not OLED text. | stated by the stakeholder in the ask |
| Must support named layouts, each with up to 8 pages selected by the scene buttons (pads plus bindable buttons, base and Shift layers) and up to 6 strip banks selected by the strip-mode buttons. Banks are independent of pages. Scene and strip-mode buttons are navigation only. A minimal layout is one page and one bank. | stated by the stakeholder in the ask |
| Must offer a Shift layer on every bindable control, and momentary and latching-toggle bindings. | stated by the stakeholder in the ask |
| Must switch layouts from the hardware with Shift + encoder turn to browse names on the OLED, encoder press to load and Shift release to cancel. Never use Shift + scene. Must show the layout, page or bank name on the OLED for about 2 s on every change. | stated by the stakeholder in the ask |
| Must store layouts as YAML in the repo under layouts/, tracked in git. The format declares devices once by name and supports range forms, human names, a machine-readable schema and an authoring guide with worked examples. Automatic version copies are git-ignored. | stated by the stakeholder in the ask |
| Must validate precisely (file, line, control, what is wrong, how to fix) and never apply an invalid layout. | stated by the stakeholder in the ask |
| Must hot-reload a written layout onto the unit and the replica within about 1 s, keeping automatic rollback copies. | stated by the stakeholder in the ask |
| Must provide a documented local CLI and the same HTTP API the page uses: list ports and layouts, validate, load/activate, switch page and bank, read state, and stream play/press events. | stated by the stakeholder in the ask |
| Must read the Notes and Custom ports while holding the unit and route played notes per layout: target device and channel, velocity untouched, aftertouch passed, converted to channel pressure or dropped, and optional transpose or note remap. These notes must also feed the replica, the activity list and the play stream. | stated by the stakeholder in the ask |
| Must treat any Note-view pad-position remap as a bounded assumption with a live calibration check. | stated by the stakeholder in the run environment |
| Must serve a browser page with a live, clickable replica of the whole unit that mirrors every press and LED. The page must provide: current labels on every control, a nav bar for layout, page, bank and Shift, Shift previews, a detail card per control, an overview of all pages and banks, a live activity list, plainly shown validation errors, learn by touch plus MIDI-learn, and single-control tweaks saved back to the layout file. | stated by the stakeholder in the ask |
| No login. The only network guard is a configurable restriction to loopback and private ranges. | stated by the stakeholder in the ask |
| Must keep the core extensible so contract 2 (layout lab and harmony views, mounted as a panel on the same page and driven through the host's play stream) adds modules without a rewrite. | stated by the stakeholder in the ask |
| Must follow the MOTU mixer project's template: a Python ≥3.14 service, FastAPI + WebSocket, one static page with no build step, hexagonal layers, simulator-backed hermetic tests, a systemd user unit enabled at login, a launcher and config.local KEY=VALUE overridable by env. | stated by the stakeholder in the run environment |
| Must serve on LAN port 5058. | stated by the stakeholder in the run environment |
| Must resolve the APC64 DAW port by name, never by card number. | stated by the stakeholder in the run environment |
| Must refuse DAW mode unless product 0x53 is identified. Warn, don't refuse, on unknown firmware. | stated by the stakeholder in the run environment |
| Must leave protocol [TBD] items explicitly bounded, never assumed. | stated by the stakeholder in the run environment |
| Must gate on hermetic pytest + node --test on the static JS, plus live checks on the attached unit (APC64_LIVE=1 pytest -m live) that leave DAW mode at the end. | stated by the stakeholder in the run environment |
| Do not include tinyBox or Raspberry Pi support. | stated by the stakeholder in the run environment |
| Must deliver into the existing repo on trunk. | stated by the stakeholder in the run environment |
| Never open the APC64's ports through the ALSA sequencer (python-rtmidi or aconnect subscriptions). Use only the exclusive rawmidi open. | Sequencer access is shared and cannot tell that Bitwig or a Web MIDI page holds the unit. The busy signal from the exclusive open is the only basis for never fighting another program. |
| Never stop, kill or reconfigure another program (Bitwig, Chrome, PipeWire/WirePlumber) to free the APC64 port, in the service or in any test. | Co-existence is one-way: the host backs off, and freeing the port is the user's decision. |
| Do not run tools/apc64_project.py read/write paths or tools/settings_watch.py from the service, its tests or the live gate. | They send project/global reads (0x13/0x17) and writes (0x14/0x18). Contract 1 talks to the unit with identity, DAW-mode, LED and OLED messages only. |
| No layout generators, Tonnetz/harmony views, circle-of-fifths views, slot-0 window shifting, project push or backups of the unit's memory in this delivery. | Those are contract 2's layout lab (docs/delivery-contract-lab.md). Contract 1 only leaves the seams (allowlist module, panel mount, play stream) for them. |
| Do not modify prototypes/tonnetz-view/index.html. | It is contract 2's working reference, not part of the host. |
| Do not modify anything in the MOTU mixer project. | It is a separate running product used here only as an architecture template. |
| Never present the Ableton/Launchpad palette RGB in the replica as the unit's exact colours; label it an approximation. | The APC64's palette RGB is [TBD] (PROTOCOL-SPEC.md §6), and the delivery must keep unknowns bounded rather than assumed. |
| Do not add runtime dependencies beyond FastAPI, uvicorn, websockets and one comment-preserving YAML library (ruamel.yaml), and no frontend package or bundler. | Keeps the install as simple as the MOTU template and keeps the static page build-free and testable under node --test. |
| Never let a hermetic test touch a real ALSA device. Hermetic tests use the simulated APC64 and in-memory ports only. | The hermetic gate must pass without the unit and must never put a real APC64 into DAW mode by accident. |
| No git push, rebase or history rewrite. | Delivery is local commits on trunk. Publishing is the user's call. |

### 2.6 Assumptions
Scales: **importance** = impact if the assumption is false (0 = none → 10 = the delivery is impossible as contracted) · **uncertainty** = what is actually known (0 = a known fact or proven → 10 = no clue, and the truth may be the complete opposite). A sum ≥ 17 is either **resolved** (settled before this contract shipped — the evidence is in `resolution`) or **escalated** (only the stakeholder can settle it: it is NOT a fact, it is listed under §1 to validate first, and its last column gives the easiest way to validate it and what changes if it is false). Rows `q…` are the answers this design assumes to points the stakeholder can decide; one the stakeholder answered is resolved by that answer. Rows `d…` sweep the terms of the ask: one row per class a term admits, its `kind` the lens it was found through (`quality` for a quality word's measure); a forced class is resolved by the reasoning in `resolution`, followed by what settles it outside this design (`source:` a definition, common knowledge, a repository path, the run environment, a prior, or the ask's own words quoted), a chosen one states the treatment this design picks and is graded like any other row.

| id | statement | kind | importance | uncertainty | status | resolution | fastest way to validate |
|---|---|---|---|---|---|---|---|
| a1 | Target and feedback devices (sequencer-only ports such as Bitwig's virtual ports, and the MPC via 'USB MIDI Interface MIDI 1') can be driven from Python 3.14 in this repo's venv. python-rtmidi, which tools/ used under Python 3.13, has no 3.14 wheel. | reused component | 7 | 1 | noted | Verified in this run: python-rtmidi has no cp314 wheel ('No matching distribution'), while alsa-midi 1.0.4 has a cp314 manylinux wheel (with cffi 2.1.1). Pinned: the sequencer side uses alsa-midi. The APC64 side keeps ctypes libasound rawmidi as in the MOTU mixer project's `_motu_mixer/infrastructure/alsa_rawmidi.py`. This amends the S8 dependency limit: runtime dependencies are fastapi, uvicorn, websockets, ruamel.yaml and alsa-midi. | pip download --only-binary=:all: python-rtmidi / alsa-midi for cp314 |
| a2 | While the user wants the host to take the unit, Chrome does not hold the APC64 ports. Contrary signal: right now (aconnect -l) Chrome's clients 128/129 are subscribed to all four APC64 ports, and amidi gets 'busy' on hw:<card>,0,0, 0,1 and 0,3. | actor behaviour | 7 | 7 | bounded | Bounded. Isolation point: the Busy banner names the holder ('Chrome') and the host re-asks when the port frees. The live gate starts with a precondition check that fails clearly if any APC64 subdevice is busy. Escalate to the user if Chrome keeps the subscription for the whole browser session after any Web MIDI page: then the exclusive-open decision needs a documented 'restart Chrome' step, or harmony views must leave Web MIDI earlier (already planned for contract 2). | Ask the user to close any Web MIDI tab (e.g. prototypes/tonnetz-view), then re-run 'aconnect -l \| grep -A4 APC64' and 'amidi -p hw:<card>,0,0 -d -t 0.5'. If the subscription persists with no such tab open, restart Chrome and check again. |
| a3 | When Bitwig drives the APC64 it opens the APC64 ports through the ALSA sequencer, so the host's exclusive rawmidi open fails with 'busy'. Bitwig is never silently overridden. | external system | 8 | 4 | bounded | Bounded. The same mechanism was verified with Chrome in this run (sequencer subscription → busy). Isolation point: the rawmidi adapter maps any open failure to Busy/No permission and sends nothing. A live check with Bitwig is part of the attended gate. Escalate if Bitwig uses rawmidi directly and opens after the host (it would then get busy, which is acceptable). | Start Bitwig with the APC64 controller enabled, then run 'amidi -p hw:<card>,0,0 -d -t 0.5' and 'aconnect -l'. |
| a4 | One process can hold exclusive rawmidi opens on hw:<card>,0,0 (read/write) and hw:<card>,0,1 and 0,3 (read-only) at the same time. Notes-port and Custom-port input (velocity, poly aftertouch) arrives over rawmidi exactly as the 2026-10-23 sequencer captures show. | external system | 7 | 3 | bounded | Bounded. Isolation point: one subdevice per adapter instance, so a failure on Notes/Custom only disables expressive routing ('<port> busy'). First live check in the build order. | With the unit free, open all three subdevices with ctypes, put the unit in DAW mode, play in Note view, and compare the bytes with fixtures/daw-mode-views-velocity-aftertouch-2026-10-23.log. |
| a5 | The rawmidi reader threads (DAW, Notes, Custom) and the alsa-midi input thread hand every message to the asyncio engine in arrival order, without loss, at strip and aftertouch rates (8 strips moving plus ~50 aftertouch values/s per note). | internal connection | 8 | 3 | bounded | Bounded. It reuses the MOTU device_pump pattern (call_soon_threadsafe, 1 MiB rawmidi input buffer), which was proven on this machine. Isolation point: a per-port sequence counter, with gaps logged to the activity list. Escalate if counts diverge live. | Hermetic: drive the simulated APC64 with 10 000 interleaved messages from two threads and assert order and count. Live: move all strips fast and count received values. |
| a6 | Every message to the APC64 passes through the one outbound gate with the SysEx allowlist, so no other code path can reach the rawmidi write. | internal connection | 9 | 2 | bounded | Bounded. Isolation point: the adapter constructor takes the gate, and its raw write is private. The device-log endpoint shows every sent and refused frame, so the live gate asserts zero 0x13/0x14/0x17/0x18. | Hermetic test that the rawmidi adapter's write accepts only gate-issued frames, plus a grep test that nothing else imports the raw writer. Injected 0x14/0x18/0x13/0x17 frames must be refused and logged. |
| a7 | A service stop (systemd SIGTERM) reaches the host's release routine: uvicorn turns SIGTERM into lifespan shutdown, and that shutdown runs clear-LEDs → DAW-off → close before the process exits. | internal connection | 9 | 2 | bounded | Bounded. This is the MOTU pattern (test___main__), and daw_probe.py proved the finally-path. Isolation point: an atexit hook and a holding marker file, so a missed release shows as 'may still be in DAW mode' at the next start. TimeoutStopSec stays above the release time. | Live: take the unit, run 'systemctl --user stop apc64-host', and check the unit left DAW mode (pads return to Custom behaviour). Hermetic: run the service with the simulator, send SIGTERM, and assert the recorded frames end with clear + 1C 00. |
| a8 | Unplugging the APC64 while held makes the rawmidi read or write fail (ENODEV/EIO) quickly, and the session ends without hanging the engine. | external system | 6 | 4 | bounded | Bounded. MOTU maps the same errors to PortGone. Isolation point: device presence is also polled every 1 s (amidi -l by name), and either signal ends the holding. Escalate only if the read blocks forever after unplug. | Live attended: take the unit, pull USB, and watch the page within 2 s. |
| a9 | A single-control tweak can be saved by splicing one line of text into or out of the agent's YAML, never by re-dumping the document. ruamel.yaml's round-trip line information is enough to find the right page, layer and position. | reused component | 8 | 5 | bounded | Bounded. Re-dumping is ruled out: ruamel can change indentation and quoting, which would break inv21's byte-identity. Isolation point: the tweak writer validates the spliced text with the full pipeline before writing, and a round-trip byte test covers each tweak kind. Escalate if a layout form needs whole-document rewriting; the format would then restrict overrides to a per-page 'overrides' block. | Spike: load docs examples with ruamel.yaml 0.19.1, insert an override after the page's last entry by text splice, re-parse, and diff the bytes. |
| a10 | The layouts directory on the repository's drive (an ntfs-3g fuseblk mount) delivers inotify events for local writes and renames, so hot reload fires within 1 s. | runtime / environment | 7 | 1 | noted | Verified in this run: inotify on the fuseblk mount reported events (192 bytes) for create, write and rename. Pinned. Fallback kept cheap: the pipeline also stat-polls every 2 s. | ctypes inotify on the repo directory, then write and rename a temp file. |
| a11 | Desktop notifications with a Take action work from the systemd user service under the user's Wayland session. | tool / capability | 4 | 3 | noted | Verified that the systemd user environment carries DBUS_SESSION_BUS_ADDRESS, DISPLAY and WAYLAND_DISPLAY, and notify-send 0.8.8 supports -A. Noted: the page banner is the primary path, and the notification is additive. | From a user unit run 'notify-send -A take=Take "Take control of APC64?"' and click it. |
| a12 | Port 5058 is free on the host machine. | runtime / environment | 2 | 0 | noted | Verified in this run: nothing listens on 5056–5058 right now. A clash would show as a clear startup error. | ss -ltn \| grep 5058 |
| a13 | FastAPI, uvicorn and websockets run on Python 3.14.7. | reused component | 5 | 1 | noted | The MOTU mixer project runs on this interpreter with the same stack. | Use the MOTU mixer project's .venv as reference |
| a14 | The alsa-midi sequencer client never subscribes to any APC64 port; it filters APC64 ports out of targets and feedback inputs. Otherwise it would make the host's own exclusive open busy. | internal connection | 7 | 3 | bounded | Bounded. Isolation point: validation already refuses APC64 ports as targets, and the sequencer adapter applies the same exclusion at connect time. | Hermetic test that port resolution excludes client names matching the APC64. Live: after start, 'aconnect -l' shows no host connection to client 'APC64'. |
| a15 | The simulated APC64 can be built from the formats in fixtures/*.log and PROTOCOL-SPEC.md. The encoder turn/press and shifted grid/track/scene 5–8 messages are not in any capture, so those simulator rows rest on [CODE] encodings. | data / state | 5 | 3 | noted | - | Grep the fixtures for B0 5A and 90 5A, and for presses between note 120 on/off. |
| a16 | After the host enters DAW mode over rawmidi, the unit answers identity and DAW-mode on/off exactly as over the sequencer. | external system | 7 | 2 | noted | - | First live check: identity request over rawmidi, then compare the reply with fixtures/apc64-snapshot-2026-10-22.hex. |
| a17 | A full redraw (64 pads, about 50 button LEDs, 16 strip CCs, 8 positions, OLED) fits within 100 ms over USB MIDI. | external system | 5 | 3 | noted | - | Live: time from the mode-0 report to the last frame of the redraw. |
| a18 | All writes to the APC64 come from one writer task, so concurrent redraws, OLED text and feedback LEDs never interleave bytes inside a SysEx frame. | internal connection | 6 | 2 | noted | - | Hermetic: concurrent redraw + OLED + feedback, then assert every recorded frame parses. |
| a19 | A click or drag in the page reaches the same engine entry point as a hardware press, so replica input runs the same binding and toggle code. | internal connection | 5 | 2 | noted | - | Hermetic API test: POST a press, then assert the same activity entry and sent message as a simulated hardware press. |
| a20 | The unit's report that it is back in Session view triggers the host's full redraw. | internal connection | 7 | 2 | noted | - | Hermetic: simulator emits mode 2 then mode 0, assert a redraw follows. Live: switch views. |
| a21 | The page and the CLI see the same state because both go through the one HTTP/WebSocket API; there is no second state path. | internal connection | 5 | 2 | noted | - | Hermetic: CLI and WebSocket client observe the same page switch. |
| a22 | The host's own tweak write triggers the normal reload pipeline exactly once, with no reload loop. | internal connection | 4 | 2 | noted | - | Hermetic: tweak, then count pipeline runs. |
| a23 | The user's agent (Claude Code) runs on the host machine as the same desktop user and can write layouts/ directly. An agent elsewhere could only validate, switch and tweak through the API. | claim about actors | 5 | 3 | noted | - | Ask the user whether they ever drive layouts from another machine. |
| a24 | The user's home devices use RFC 1918 or IPv6 ULA/link-local addresses. A phone on Tailscale (100.64.0.0/10) would be refused unless that range is added in config. | runtime / environment | 3 | 5 | noted | - | ip addr on the host machine, plus ask the user how their phone reaches the LAN. |
| a25 | Control names for layouts and the API: 'pad r1c1'–'pad r8c8' with row 1 at the bottom, 'track 1–8', 'trackctl 1–8', 'scene 1–8', 'strip 1–8', named buttons ('play', 'rec', 'stop', 'up', 'shift', …) and 'encoder'. This vocabulary is natural to the user and to agents. | unrequested product choice | 5 | 3 | noted | - | Show the user the control-name diagram from the guide and ask whether row 1 at the bottom feels right. |
| a26 | Colours in layouts are written as names (red, green, …) or palette indexes 0–127, and names map to fixed Ableton-palette indexes. | unrequested product choice | 3 | 3 | noted | - | Live: light the named colours and let the user look. |
| a27 | Version copies and the state file live in ~/.local/state/apc64-host/ (outside the repo), overridable in config. | unrequested product choice | 2 | 1 | noted | - | - |
| a28 | The service listens dual-stack on [::]:5058, accepting both IPv4 (as IPv4-mapped) and IPv6 clients. The private-range and Origin/Host middleware is the only network guard. (corrected by the consistency check: Binding 0.0.0.0 would refuse the IPv6 home clients that d158 and A146 require.) | unrequested product choice | 3 | 1 | noted | - | - |
| a29 | The implementer can build the full replica (grid, strips, encoder, OLED, nav bar, cards, overview, activity, learn, tweak) as vanilla ES modules with logic testable under node --test. | implementer capability | 6 | 3 | noted | - | Port the MOTU static page structure first and get one node --test green. |
| a30 | The implementer can port MOTU's ctypes rawmidi adapter to the APC64's four subdevices (one read/write, two read-only). | implementer capability | 4 | 2 | noted | - | - |
| a31 | Only one host instance runs at a time. A second instance fails clearly (port 5058 in use, unit Busy) and does no harm. | runtime / environment | 4 | 2 | noted | - | Start the service twice. |
| a32 | The live gate can run unattended for take/draw/release and wire checks once Chrome and Bitwig are not holding the unit. The attended checks need the user present: Bitwig busy, unplug, encoder, shifted pads, pad position, OLED limits, calibration, LED looks, Drum view. | actor behaviour | 4 | 3 | noted | - | Ask the user for a 20-minute attended slot. |
| a33 | The MPC and other targets accept messages from a sequencer client while other programs also use them. A target held exclusively elsewhere makes the send fail visibly ('not sent'). | external system | 4 | 3 | noted | - | Live: send note 36 to 'USB MIDI Interface MIDI 1' while Bitwig is also connected. |
| a34 | Before the user logs in, the rawmidi open fails with EACCES (logind seat ACL), shown as 'No permission', not Busy. | runtime / environment | 3 | 2 | noted | - | ls -l /dev/snd/midiC<card>D0 and getfacl on it. |
| a35 | The repository's drive (ntfs-3g, nofail in fstab) is mounted before the user unit starts. If it is not, the service starts with no layouts and says so instead of crashing. | runtime / environment | 4 | 3 | noted | - | systemctl --user show apc64-host after a reboot, plus findmnt on the repository's mount point. |
| a36 | The Ableton/Launchpad palette table (and Bitwig's ColorLookup in its MIT-licensed APC64 extension) is a usable approximation for replica colours. | data / state | 2 | 2 | noted | - | - |
| a37 | The user understands that while the host holds the unit, Bitwig cannot use it, and that they must Release before using the APC64 in Bitwig. | claim about actors | 3 | 2 | noted | - | State it in the README and the Busy/Held banner text. |
| q1 | Layout files accept notes as numbers (0–127) or names. Names use the Ableton/Akai convention C3 = 60, so 'C1' = 36. — open question for the stakeholder: When a layout says a note name like 'C1', should middle C (60) be C3 (Ableton/Akai/MPC) or C4 (scientific pitch)? | reading of the ask | 4 | 6 | bounded | Bounded. The convention lives in one value-object parser, documented in the guide with a table. Every label in the replica shows the number next to the name ('C1 (36)'), so a wrong guess is visible at once and a one-line change fixes it. | Ask the user which octave their MPC shows for note 60, and match it. |
| q2 | An unshifted encoder turn binding keeps an absolute value (0–127, starting at 64, clamped). Each detent moves it by one, and it is sent as the bound CC. The OLED shows the label and value for about 2 s. — open question for the stakeholder: Should the encoder send an absolute CC value the host keeps, or relative increments (e.g. 1 / 127) for software that understands relative encoders? | unrequested product choice | 3 | 4 | noted | - | Ask the user what they would bind the encoder to (MPC Q-link, a Bitwig parameter). |
| q3 | A binding may give each target device a default channel, and individual bindings may override it. Channels are written 1–16. — open question for the stakeholder: Is it fine that channels are written 1–16 and that a device line can carry a default channel the bindings inherit? | unrequested product choice | 3 | 2 | noted | - | Show the user the worked example in the guide. |
| q4 | A Session-view pad trigger sends velocity 127 (what the unit reports) unless its binding sets a fixed velocity. — open question for the stakeholder: For Session-view pads, which can only report 127, is a per-binding fixed velocity (e.g. 100) useful, with 127 as the default? | unrequested product choice | 2 | 3 | noted | - | Ask the user. |
| q5 | Shift is momentary: the Shift layer applies only while Shift is held, with no Shift-lock. — open question for the stakeholder: Should Shift ever latch (double-tap to lock the Shift layer), or only work while held? | reading of the ask | 3 | 3 | noted | - | Ask the user. |
| q6 | When the unit is taken, the service restores the last-used layout, page and bank, and toggle states from the running service. Loading a layout from the hardware, page or API opens its page 1 and bank 1. — open question for the stakeholder: After taking the unit, or switching layouts, should the host come back where you left off, or start at page 1 / bank 1? | unrequested product choice | 3 | 3 | noted | - | Ask the user. |
| q7 | The activity list shows one entry per routed note, holding its latest aftertouch value, instead of one row per aftertouch message. The play stream still carries every aftertouch value. — open question for the stakeholder: In the activity list, should continuous aftertouch appear as every message, or folded into its note's entry? | unrequested product choice | 3 | 3 | noted | - | Show the user a 10-second Note-view capture rendered both ways. |
| q8 | The host sends no MIDI clock and follows none. Play, Rec and Stop are ordinary bindable buttons. — open question for the stakeholder: Should the host take part in tempo/clock (send or follow MIDI clock, e.g. for the MPC), or are transport buttons just bindable messages? | reading of the ask | 3 | 3 | noted | - | Ask the user whether they expect the APC64's Play to start the MPC with clock. |
| q9 | A bound pad or RGB button shows its colour at 25% when off and full brightness while pressed or toggled on. An unbound control is unlit. — open question for the stakeholder: How should bound-but-idle controls look on the unit: dim colour, full colour, or off until pressed? | unrequested product choice | 2 | 3 | noted | - | Live: show the user a page drawn this way. |
| q10 | Each strip in a bank may set its bar style (bar or bipolar) and colour. The default is a white bar. — open question for the stakeholder: Should strips default to a plain white bar, or to something else (e.g. bipolar for pan)? | unrequested product choice | 1 | 3 | noted | - | Ask the user. |
| q11 | A layout's display name is its 'name' field, falling back to the file name when absent. The file name stays the layout's identity for the API and CLI. — open question for the stakeholder: Should layouts be addressed by their display name or by their file name? | unrequested product choice | 2 | 2 | noted | - | - |
| q12 | The command-line tool is installed as the console command 'apc64' (also runnable as 'python -m _apc64_host'). It talks to the running service on localhost:5058 and validates offline. — open question for the stakeholder: Is 'apc64' a good command name for the agent and for you? | unrequested product choice | 1 | 2 | noted | - | - |
| d1 | APC64 unit — identified APC64: forced | kind | - | - | resolved | DAW mode is entered only after an identity reply carrying product byte 0x53. (source: PROTOCOL-SPEC.md §3) | - |
| d2 | APC64 unit — non-APC64 or silent device: forced | kind | - | - | resolved | A wrong product byte, or no identity reply, means DAW mode is never entered and the page says why. (source: PROTOCOL-SPEC.md §3) | - |
| d3 | APC64 unit — unknown firmware: forced | kind | - | - | resolved | A firmware version other than 1.2.1.6 brings a warning, not a refusal. (source: PROTOCOL-SPEC.md §3) | - |
| d4 | APC64 unit — no unit attached: Page and API keep serving and the page shows 'APC64 not connected'. Layouts load and switch, and replica clicks still send their bound actions. | amount | 3 | 2 | noted | - | - |
| d5 | APC64 unit — two units attached: Only the first unit in port-name order is offered. The page reports the second as ignored. | amount | 2 | 3 | noted | - | - |
| d6 | APC64 unit — unit left in DAW mode: On start the host sends nothing. The banner says 'APC64 may still be in DAW mode: Take to reset, or replug it'. | form | 4 | 3 | noted | - | - |
| d7 | APC64 unit — card number moved: forced | sameness | - | - | resolved | The card number changes between plug-ins, so it is the same unit whenever its port name matches. (source: p1) | - |
| d8 | APC64 unit — unit appears while running: forced | time | - | - | resolved | When the unit appears, the host asks; it never takes the unit unprompted. (source: the stakeholder's brief) | - |
| d9 | APC64 unit — unplugged while held: Ownership ends, the page shows 'APC64 unplugged', and on return DAW mode is treated as lost. Bounded by a live unplug check, because unplug behaviour is [TBD]. | time | 6 | 5 | bounded | - | - |
| d10 | APC64 unit — replugged: forced | time | - | - | resolved | A replug is a new appearance, so the host asks again. (source: the stakeholder's brief) | - |
| d11 | APC64 unit — suspend and resume: Handled as an unplug followed by a replug. | time | 3 | 5 | noted | - | - |
| d12 | consent — yes from banner: forced | kind | - | - | resolved | The page banner asks 'Take control of APC64?' and a yes takes the unit. (source: the stakeholder's brief) | - |
| d13 | consent — yes from desktop notification: forced | kind | - | - | resolved | The desktop notification carries a Take action that works the same as the banner. (source: the stakeholder's brief) | - |
| d14 | consent — decline: forced | kind | - | - | resolved | After a no, the port stays free. (source: the ask: "only when the user allows it") | - |
| d15 | consent — auto-accept: forced | kind | - | - | resolved | An opt-in setting, off by default, takes the unit without asking. (source: the stakeholder's brief) | - |
| d16 | consent — no answer: The question stays open in the banner indefinitely and nothing is taken. | amount | 2 | 2 | noted | - | - |
| d17 | consent — double yes: The first yes takes the unit. A second yes from another place is answered 'already held' and does not repeat the handshake. | sameness | 2 | 2 | noted | - | - |
| d18 | consent — consent per appearance: A yes covers one holding only. After release, unplug or restart, the host asks again. | time | 4 | 2 | noted | - | - |
| d19 | consent — yes while busy: forced | time | - | - | resolved | If the port is held by another program, the host shows Busy and takes nothing. (source: the ask: "backs off if the port is busy") | - |
| d20 | consent — yes from another LAN browser: A yes from any allowed home-network browser counts, because there is no login. | source | 4 | 3 | noted | - | - |
| d21 | consent — take from the agent CLI: An agent's take request through the command-line tool or API counts as the user's yes, since the agent acts on their instruction. The page shows who took the unit. | source | 5 | 4 | noted | - | - |
| d22 | another program using the unit — Bitwig holds the port: The host shows Busy naming the holder, sends nothing to the unit, and a live check with Bitwig running confirms it. Whether Bitwig's hold makes the port report busy is [TBD]. | kind | 8 | 4 | bounded | - | - |
| d23 | another program using the unit — Web MIDI page subscribed: forced | kind | - | - | resolved | A browser page with Web MIDI access makes the APC64 DAW port busy, so the host shows Busy. This was verified on this machine in an earlier run: amidi got 'busy' while Chrome was subscribed. (source: an earlier draft of this contract) | - |
| d24 | another program using the unit — replica page never subscribes: The replica page never asks the browser for MIDI access, so opening it never takes the unit from anyone. | kind | 9 | 0 | noted | - | - |
| d25 | another program using the unit — no permission: A refused open for lack of permission (no logged-in seat) shows 'No permission to open APC64', not Busy. | kind | 3 | 2 | noted | - | - |
| d26 | another program using the unit — only Notes or Custom port busy: The host still holds the unit through its DAW port. Expressive routing for the busy port is off, and the page shows '<port> busy: expressive pads not routed'. | kind | 4 | 5 | noted | - | - |
| d27 | another program using the unit — port frees while Busy: The host notices within 5 s and asks again. It does not take the unit. | time | 3 | 3 | noted | - | - |
| d28 | another program using the unit — other program tries while held: forced | time | - | - | resolved | While the host holds the unit exclusively, another program's open of the port fails. (source: p11) | - |
| d29 | release — Release from page: forced | kind | - | - | resolved | Releasing from the page leaves DAW mode and frees the port. (source: the ask: "released") | - |
| d30 | release — service stop or SIGTERM: forced | kind | - | - | resolved | Stopping the service, including on system shutdown, leaves DAW mode and frees the port. (source: the ask: "stopped") | - |
| d31 | release — unplug release: forced | kind | - | - | resolved | With the unit gone nothing can be sent. The port is closed and the page says so. (source: the ask: "unplugged") | - |
| d32 | release — internal failure: Any fault that stops the host's engine runs the same release as the Release button. | kind | 6 | 3 | noted | - | - |
| d33 | release — SIGKILL or power loss: forced | kind | - | - | resolved | A process killed with SIGKILL cannot run any code, so nothing is sent. The next start handles the aftermath (see 'unit left in DAW mode'). (source: common knowledge: SIGKILL cannot be caught) | - |
| d34 | release — release when not held: Answered 'APC64 is not held', and nothing is sent. | amount | 1 | 1 | noted | - | - |
| d35 | release — clear before DAW-off: forced | time | - | - | resolved | LEDs and OLED are cleared before DAW mode is switched off. (source: the stakeholder's brief) | - |
| d36 | release — release by agent: An agent may release the unit through the command-line tool or API. | source | 2 | 2 | noted | - | - |
| d37 | control — Session-view pad: forced | kind | - | - | resolved | In Session view a pad is a trigger with fixed velocity 127 and no aftertouch. (source: p7) | - |
| d38 | control — bindable button: forced | kind | - | - | resolved | Every button that reports to the host is bindable on base and Shift layers, except the navigation buttons. (source: p4) | - |
| d39 | control — scene and strip-mode buttons are navigation: forced | kind | - | - | resolved | Scene buttons select pages and strip-mode buttons select banks. Neither is bindable. (source: the stakeholder's brief) | - |
| d40 | control — strip touch and 14-bit position: forced | kind | - | - | resolved | Strip touch arrives as notes 82–89, and position as 14-bit pitch bend with channel = strip. (source: p4) | - |
| d41 | control — encoder turn and press: Turn = CC 0x5A (1 = clockwise, 127 = counter-clockwise) and press = note 0x5A. The unshifted turn and press are bindable. These encodings are [CODE] only, so a live check confirms them. | kind | 5 | 5 | bounded | - | - |
| d42 | control — Shift key: forced | kind | - | - | resolved | Shift is note 120 and the unit does not apply it. The host applies the Shift layer, and Shift itself is not bindable. (source: p5) | - |
| d43 | control — device-local buttons: forced | kind | - | - | resolved | The pad-mode buttons and the project menu never reach the host. The replica shows them as the unit's, not as bindable. (Amended 2026-10-27: still never bindable, but the replica's Session/Note/Chord/Step/Custom buttons switch the unit by the pad-mode request while it is held; Project stays the unit's own.) (source: PROTOCOL-SPEC.md §5) | - |
| d44 | control — strip-mode button names: Notes 121–126 select banks 1–6 in panel order. Their labels follow the names printed on the unit, checked live, because PROTOCOL-SPEC.md §5 (… Sends, Channel, Off) and the stakeholder's brief (… Send A, Send B, Channel Strip) disagree. | kind | 3 | 6 | noted | - | - |
| d45 | control — shifted control not yet captured: A Shift layer is offered on every bindable control. A live check records whether Shift + grid pads, track buttons and the track-control row reach the host; any that do not are marked 'not reachable on this unit' in the detail card. | amount | 5 | 5 | bounded | - | - |
| d46 | control — simultaneous presses: Each press is handled on its own, in arrival order. | amount | 2 | 1 | noted | - | - |
| d47 | control — pad position in DAW mode: Pad note 0 is the bottom-left pad and numbering runs left to right, then upwards, as in Custom mode. Bounded by a live check, because this is [TBD] in DAW mode. | form | 6 | 4 | bounded | - | - |
| d48 | control — encoder multi-step value: Values 1–63 are that many clockwise steps. Values 65–127 are (128 − value) counter-clockwise steps. | form | 2 | 5 | noted | - | - |
| d49 | control — replica click equals press: forced | sameness | - | - | resolved | Clicking or dragging a control in the replica does the same as touching it on the unit. (source: PROTOCOL-SPEC.md §9 scenario 3) | - |
| d50 | control — release after the meaning changed: A release goes to the binding that received the press, even if the page, Shift state or layout changed in between. | time | 4 | 2 | noted | - | - |
| d51 | MIDI action — message kinds: A binding can send note on/off, CC (7-bit, or 14-bit MSB+LSB for strips), program change and pitch bend. It cannot send raw SysEx. | kind | 5 | 3 | noted | - | - |
| d52 | MIDI action — several messages per action: A binding may list several messages, sent in the written order. | amount | 3 | 2 | noted | - | - |
| d53 | MIDI action — unbound control: An unbound control sends nothing, shows as empty, and appears in the activity list as 'unbound'. | amount | 2 | 1 | noted | - | - |
| d54 | MIDI action — strip resolution to target: A strip bound to pitch bend sends the full 14-bit value. Bound to a 7-bit CC it sends position ÷ 128. Bound to a CC pair it sends MSB, then LSB. | form | 4 | 2 | noted | - | - |
| d55 | MIDI action — repeated strip value: A strip value equal to the last one sent is not sent again. | sameness | 1 | 1 | noted | - | - |
| d56 | MIDI port (device) — any ALSA port by name: forced | kind | - | - | resolved | A layout declares each device once, as a name for an ALSA MIDI port (hardware or software). The device can be used for output, for feedback input, or both. (source: the stakeholder's brief) | - |
| d57 | MIDI port (device) — APC64 port as target: A device that names one of the APC64's own ports is refused by validation. | kind | 6 | 2 | noted | - | - |
| d58 | MIDI port (device) — declared device missing: The layout still loads. Its bindings are labelled '(missing)', and their sends are listed as 'not sent: <device> missing'. | amount | 5 | 2 | noted | - | - |
| d59 | MIDI port (device) — ambiguous port name: A device matches by exact port name or by a unique part of it. A part matching two ports is a validation error that lists both. | form | 4 | 3 | noted | - | - |
| d60 | MIDI port (device) — two names one port: Allowed: both names reach the same port. | sameness | 1 | 1 | noted | - | - |
| d61 | MIDI port (device) — port appears or vanishes while live: The device reconnects by name with no reload, and labels switch between '(missing)' and normal. | time | 4 | 3 | noted | - | - |
| d62 | layout — minimal layout: forced | kind | - | - | resolved | One page and one bank is a complete layout. (source: the stakeholder's brief) | - |
| d63 | layout — script-generated layout: forced | kind | - | - | resolved | A layout file emitted by a script is treated like any other. (source: the stakeholder's brief) | - |
| d64 | layout — devices named once: forced | kind | - | - | resolved | Each device is declared once by name, and bindings refer to it by that name. (source: the ask: "devices named once") | - |
| d65 | layout — many layouts: There is no limit on the number of layouts. | amount | 3 | 2 | noted | - | - |
| d66 | layout — ninth page or seventh bank: forced | amount | - | - | resolved | Refused by validation: there are 8 scene buttons and 6 strip-mode buttons. (source: p4) | - |
| d67 | layout — no layouts: The unit is held with a dark surface and the OLED shows 'No layout'. | amount | 2 | 1 | noted | - | - |
| d68 | layout — YAML: forced | form | - | - | resolved | Layout files are YAML. (source: the stakeholder's brief) | - |
| d69 | layout — syntax error: forced | form | - | - | resolved | Refused with file, line, problem and fix. (source: the ask: "precise validation errors") | - |
| d70 | layout — unknown control or device: forced | form | - | - | resolved | Refused with file, line, the name that is wrong and the valid names. (source: the ask: "precise validation errors") | - |
| d71 | layout — half-written file: The host waits until writes settle, then validates. A file that is still incomplete is shown as invalid, and the previous layout stays live. | form | 5 | 3 | noted | - | - |
| d72 | layout — range form: forced | form | - | - | resolved | A single line can bind a run of controls, such as pads r1c1–r2c8 = notes 36 upwards. (source: the ask: "range forms") | - |
| d73 | layout — single entry inside a range: A single-control entry overrides the range covering it on the same page and layer. | form | 6 | 2 | noted | - | - |
| d74 | layout — two ranges on one control: Two ranges, or two single entries, binding the same control on the same page and layer are refused, and the error names both lines. | form | 4 | 2 | noted | - | - |
| d75 | layout — duplicate layout name: Two files with the same layout name are refused, and the error names both files. The one already loaded stays. | sameness | 3 | 2 | noted | - | - |
| d76 | layout — unchanged rewrite: Rewriting a file with identical content causes no reload and no new version. | sameness | 1 | 1 | noted | - | - |
| d77 | layout — edited while active: forced | time | - | - | resolved | An edit to the active layout's file goes live without any further action. (source: the ask: "hot reload") | - |
| d78 | layout — active file deleted: The layout stays live from memory, and the page shows 'file deleted, still active'. | time | 3 | 2 | noted | - | - |
| d79 | layout — agent and page write at once: A page tweak is refused with 'layout changed, reload' if the file changed after the page last read it. | time | 4 | 3 | noted | - | - |
| d80 | page — unnamed page: Shown as 'Page N'. | kind | 1 | 1 | noted | - | - |
| d81 | page — scene LED states: forced | kind | - | - | resolved | Scene LEDs show full = current page, dim = defined, off = empty. (source: the stakeholder's brief) | - |
| d82 | page — empty page slot: Pressing an empty page's scene button keeps the current page, and the OLED shows 'Page 5 empty'. | amount | 2 | 2 | noted | - | - |
| d83 | page — toggle state per page: Each toggle keeps its state per page and layer while the layout stays loaded. | time | 3 | 2 | noted | - | - |
| d84 | strip bank — banks independent of pages: forced | kind | - | - | resolved | Switching bank does not change the page, and switching page does not change the bank. (source: the stakeholder's brief) | - |
| d85 | strip bank — empty bank slot: Pressing an empty bank's strip-mode button keeps the current bank, and the OLED shows 'Bank 4 empty'. | amount | 2 | 2 | noted | - | - |
| d86 | strip bank — bank switch redraw: forced | time | - | - | resolved | On a bank switch, each bar is redrawn at its feedback value if a feedback rule exists, otherwise at its last touch. (source: the stakeholder's brief) | - |
| d87 | Shift layer — Shift + encoder reserved: forced | kind | - | - | resolved | Shift + encoder turn and press browse and load layouts and cannot be bound. (source: the stakeholder's brief) | - |
| d88 | Shift layer — Shift + scene unused: forced | kind | - | - | resolved | Shift + scene does nothing: the unit switched itself to Project mode after Shift + scene 4. (source: NOTES-daw-mode.md) | - |
| d89 | Shift layer — no Shift binding: Shift + a control with no Shift binding sends nothing (no fallback to the base layer), and the Shift preview shows it as empty. | amount | 4 | 4 | noted | - | - |
| d90 | Shift layer — Shift held on page or unit: Shift counts as held while it is held on the unit or in the page. | sameness | 2 | 2 | noted | - | - |
| d91 | binding mode — momentary: forced | kind | - | - | resolved | The on message is sent on press and the off message on release. (source: definition: a momentary control is active only while held) | - |
| d92 | binding mode — latching toggle: forced | kind | - | - | resolved | Each press flips between on and off. Release does nothing. (source: definition: a latching toggle changes state on each press and holds it) | - |
| d93 | binding mode — toggle on a strip: Refused by validation: a strip position cannot be a toggle. | kind | 2 | 2 | noted | - | - |
| d94 | binding mode — toggle values: A toggle sends 127 when switched on and 0 when switched off, unless the layout gives other values. | form | 2 | 1 | noted | - | - |
| d95 | binding mode — toggle LED vs feedback: forced | sameness | - | - | resolved | The LED follows the toggle state unless a feedback rule drives it. (source: the stakeholder's brief) | - |
| d96 | binding mode — toggle across hot reload: Toggle state is kept for controls whose binding did not change, and reset to off otherwise. | time | 3 | 3 | noted | - | - |
| d97 | incoming MIDI feedback — note and CC feedback: Note on/off and CC messages on a device's input port can drive a control's LED or strip bar. | kind | 5 | 3 | noted | - | - |
| d98 | incoming MIDI feedback — no OLED text from feedback: forced | kind | - | - | resolved | Feedback drives LEDs and strip bars only, never OLED text. (source: the stakeholder's brief) | - |
| d99 | incoming MIDI feedback — any named input port: forced | kind | - | - | resolved | Feedback can come from any named input port. (source: the stakeholder's brief) | - |
| d100 | incoming MIDI feedback — unmatched feedback: A message that no feedback rule mentions is ignored. | amount | 1 | 1 | noted | - | - |
| d101 | incoming MIDI feedback — feedback burst: Messages are applied in order, so the last one wins. | amount | 3 | 2 | noted | - | - |
| d102 | incoming MIDI feedback — value to colour: Value 0 shows the binding's off colour and any other value its on colour, unless the rule lists colours per value. A strip bar shows the value scaled to its length. | form | 4 | 3 | noted | - | - |
| d103 | incoming MIDI feedback — feedback sets toggle: For a toggle with a feedback rule, an incoming value also sets the toggle state, so the next press sends the opposite. | sameness | 4 | 3 | noted | - | - |
| d104 | incoming MIDI feedback — feedback while hidden or not held: Feedback for a page not shown, or arriving while the unit is not held, is kept and drawn when that page is shown or the unit is taken. | time | 4 | 2 | noted | - | - |
| d105 | layout switch from the hardware — encoder press loads: forced | kind | - | - | resolved | While Shift is held, pressing the encoder loads the layout whose name is shown. (source: the stakeholder's brief) | - |
| d106 | layout switch from the hardware — browse order: Layouts are browsed in alphabetical order of name and wrap around at the ends. | amount | 1 | 1 | noted | - | - |
| d107 | layout switch from the hardware — Shift released cancels: forced | time | - | - | resolved | Letting go of Shift before pressing the encoder cancels the browse, and the current layout stays. (source: the stakeholder's brief) | - |
| d108 | OLED — idle OLED: At rest, row 0 shows the layout name and row 1 shows 'P<n> <page> \| B<n> <bank>' (cut to 14 characters). | kind | 1 | 2 | noted | - | - |
| d109 | OLED — name over 14 chars: Shown on the OLED cut to 14 characters (the safe length while rows and length are [TBD]). The full name appears in the page, and validation warns. | amount | 2 | 4 | noted | - | - |
| d110 | OLED — non-ASCII name: Non-ASCII characters show as '?' on the OLED. The page shows the name as written. | form | 1 | 3 | noted | - | - |
| d111 | OLED — name for 2 s: forced | time | - | - | resolved | A layout, page or bank change shows its name for about 2 s. (source: the stakeholder's brief) | - |
| d112 | validation error — error names file line control problem fix: forced | kind | - | - | resolved | Every error gives the file, the line, the control, what is wrong and how to fix it. (source: the stakeholder's brief) | - |
| d113 | validation error — several errors: All errors in a file are reported at once, in line order. | amount | 2 | 1 | noted | - | - |
| d114 | validation error — warning does not block: Warnings, such as a name too long for the OLED, are shown but never stop a layout from going live. | form | 2 | 2 | noted | - | - |
| d115 | validation error — same error everywhere: The page, the command-line tool and the API show identical error text. | sameness | 2 | 1 | noted | - | - |
| d116 | validation error — errors until fixed: Errors stay shown until a valid version of that file is written. | time | 2 | 1 | noted | - | - |
| d117 | layout version — copy per live version: A copy is kept each time a version of a layout goes live. | kind | 4 | 2 | noted | - | - |
| d118 | layout version — copies git-ignored: forced | kind | - | - | resolved | Version copies are kept outside git tracking. The layouts themselves are tracked. (source: the stakeholder's brief) | - |
| d119 | layout version — all versions kept: Every version is kept, with no pruning. | amount | 1 | 1 | noted | - | - |
| d120 | layout version — restore: Restoring writes that version back as the layout file, and it goes live like any other write. | form | 4 | 2 | noted | - | - |
| d121 | layout version — invalid never a version: Content that failed validation never becomes a version. | time | 3 | 1 | noted | - | - |
| d122 | agent command-line tool and API — the listed operations: forced | kind | - | - | resolved | An agent can list ports and layouts, validate, load, switch layout/page/bank, read state and watch play. (source: the ask: "list ports and layouts, validate, load and switch layouts/pages/banks, read state and watch what the user plays") | - |
| d123 | agent command-line tool and API — schema and guide: forced | kind | - | - | resolved | A machine-readable schema and an authoring guide with worked examples ship with the tool. (source: the ask: "a schema and a worked-example guide") | - |
| d124 | agent command-line tool and API — validate any path: Validation accepts any file path and never applies the file. | kind | 3 | 2 | noted | - | - |
| d125 | agent command-line tool and API — service not running: Validation still works. Other commands say 'service not running on port 5058'. | amount | 3 | 2 | noted | - | - |
| d126 | agent command-line tool and API — malformed request: Refused with a message naming the allowed values, and nothing changes. | form | 2 | 1 | noted | - | - |
| d127 | agent command-line tool and API — concurrent switching: The last switch wins, and every client sees the same resulting state. | time | 2 | 2 | noted | - | - |
| d128 | played note — Note view with poly aftertouch: forced | kind | - | - | resolved | In Note view, notes arrive on the Notes port with real velocity and poly aftertouch. (source: p7) | - |
| d129 | played note — Chord view three notes: forced | kind | - | - | resolved | In Chord view one pad sends three notes sharing one velocity, each with its own poly aftertouch. (source: p7) | - |
| d130 | played note — Step view velocity only: forced | kind | - | - | resolved | In Step view, notes arrive on the Notes port with velocity and no aftertouch. (source: p7) | - |
| d131 | played note — Custom view on Custom port: forced | kind | - | - | resolved | In Custom view, notes arrive on the Custom port with velocity. (source: p7) | - |
| d132 | played note — Custom-view strip CCs: Strip CCs arriving on the Custom port are passed unchanged to the Custom-port routing target. | kind | 3 | 4 | noted | - | - |
| d133 | played note — Drum view: Drum view (report 5, [CODE], untested) is treated like Note view and confirmed by a live check. | kind | 3 | 6 | noted | - | - |
| d134 | played note — aftertouch flood: Every aftertouch value is forwarded in order, never thinned. | amount | 4 | 3 | noted | - | - |
| d135 | played note — velocity-0 note-on: forced | form | - | - | resolved | A note-on with velocity 0 is a note-off and is forwarded as such. (source: definition: MIDI note-on with velocity 0 means note-off) | - |
| d136 | played note — same note twice: Repeated or overlapping note-ons for the same note are forwarded as received, with no de-duplication. | sameness | 3 | 4 | noted | - | - |
| d137 | played note — notes held across a change: A note-off gets the same target and transform as its note-on, even if the view or routing changed in between. | time | 5 | 3 | noted | - | - |
| d138 | played note — played while not held: forced | time | - | - | resolved | Notes played while the host does not hold the unit are not read or routed. (source: the ask: "reads those ports while it holds the unit") | - |
| d139 | routing rule — velocity untouched: forced | kind | - | - | resolved | Velocity reaches the target exactly as played. (source: the ask: "velocity untouched") | - |
| d140 | routing rule — aftertouch passed: forced | kind | - | - | resolved | Poly aftertouch is forwarded per note. (source: the ask: "aftertouch passed") | - |
| d141 | routing rule — aftertouch to channel pressure: Converted to channel pressure equal to the highest current poly aftertouch among held notes. | kind | 4 | 3 | noted | - | - |
| d142 | routing rule — aftertouch dropped: forced | kind | - | - | resolved | No aftertouch is forwarded. (source: the ask: "dropped") | - |
| d143 | routing rule — no routing rule: Played notes are not routed. They still show in the replica and play stream, and the page says 'expressive pads not routed in this layout'. | amount | 5 | 3 | noted | - | - |
| d144 | routing rule — transpose out of range: A note pushed outside 0–127 is dropped and listed in the activity list. | form | 2 | 1 | noted | - | - |
| d145 | routing rule — partial remap: Notes not in the remap table pass through with the transpose only. | form | 3 | 2 | noted | - | - |
| d146 | routing rule — one rule per port per layout: A layout has one routing rule for the Notes port and one for the Custom port. Page and bank changes do not change them. | sameness | 4 | 3 | noted | - | - |
| d147 | replica pad position of a played note — calibrated position: After a live calibration (press the bottom-left and top-right pads in Note view), the replica lights played notes on pads, labelled 'calibrated <time>'. | kind | 4 | 5 | noted | - | - |
| d148 | replica pad position of a played note — uncalibrated: Without a calibration, played notes appear in a played-notes row with 'pad position unknown', not on the pads. | kind | 3 | 3 | noted | - | - |
| d149 | replica pad position of a played note — stale calibration: The host cannot detect that the Note-view settings changed on the unit. The label always shows the calibration time and 'assumed'. | time | 3 | 6 | noted | - | - |
| d150 | play stream — event kinds: The stream carries presses, releases, strip moves, played notes with aftertouch, and layout/page/bank/Shift changes. | kind | 3 | 2 | noted | - | - |
| d151 | play stream — slow watcher: A watcher that falls more than 5 s behind is disconnected with a notice. The unit and other watchers are unaffected. | amount | 4 | 3 | noted | - | - |
| d152 | play stream — many watchers: All watchers receive the same events in the same order. | amount | 2 | 2 | noted | - | - |
| d153 | play stream — event content: Each event carries its time, source (unit view or replica), control or note, value, and the message sent (or why none was sent). | form | 3 | 2 | noted | - | - |
| d154 | play stream — joining mid-stream: A new watcher gets events from now on. Current state is read separately. | time | 2 | 2 | noted | - | - |
| d155 | home network client — loopback and private range: forced | kind | - | - | resolved | Clients on loopback and in private address ranges are served with no login. (source: the stakeholder's brief) | - |
| d156 | home network client — public address: forced | kind | - | - | resolved | Clients outside the configured ranges are refused. (source: the stakeholder's brief) | - |
| d157 | home network client — foreign web origin: Requests that a web page from another site makes through the user's browser are refused. | kind | 5 | 3 | noted | - | - |
| d158 | home network client — IPv6 local: IPv6 loopback, link-local and unique-local addresses count as private. | kind | 2 | 3 | noted | - | - |
| d159 | home network client — several browsers: Every open page shows the same live state. | amount | 3 | 2 | noted | - | - |
| d160 | home network client — browser reconnects: A page that reconnects shows the full current state at once. | time | 3 | 2 | noted | - | - |
| d161 | home network client — guest on LAN: Anyone on the home network is trusted to play, switch and tweak. | source | 3 | 2 | noted | - | - |
| d162 | activity list — sent, not sent, refused: Each entry shows control → message → port, marked as sent, not sent (with the reason), or refused. | kind | 3 | 2 | noted | - | - |
| d163 | activity list — list length: The page shows the latest 200 entries. | amount | 1 | 1 | noted | - | - |
| d164 | learn — touch-select: forced | kind | - | - | resolved | Touching a control on the unit selects it in the page. (source: the stakeholder's brief) | - |
| d165 | learn — MIDI-learn: forced | kind | - | - | resolved | With a control selected, the next message arriving on a chosen input port becomes its binding. (source: the stakeholder's brief) | - |
| d166 | learn — learn with no message: Leaving MIDI-learn before a message arrives changes nothing. | amount | 1 | 1 | noted | - | - |
| d167 | learn — what MIDI-learn captures: The first note, CC, program change or pitch bend message is captured. Its type, number and channel, sent to the device that owns that port, become the binding on the current page and layer. | form | 4 | 3 | noted | - | - |
| d168 | learn — touch in learn runs nothing: While learn is on, a touch only selects and sends no action. | time | 3 | 2 | noted | - | - |
| d169 | single-control tweak — tweak kinds: forced | kind | - | - | resolved | A tweak changes a control's assignment, label, colour, or momentary/toggle mode. (source: the stakeholder's brief) | - |
| d170 | single-control tweak — tweak scope: A tweak changes one control on the current page (or bank) and layer only. | amount | 3 | 2 | noted | - | - |
| d171 | single-control tweak — tweak inside a range: Tweaking a control covered by a range adds one single-control entry and leaves the range line as written. | form | 6 | 3 | noted | - | - |
| d172 | single-control tweak — invalid tweak: A tweak that would make the layout invalid is refused before saving, with the error shown, and the file is untouched. | form | 4 | 1 | noted | - | - |
| d173 | single-control tweak — tweak back to range value: A tweak that makes the control equal to its range's value removes the override entry. | sameness | 2 | 3 | noted | - | - |
| d174 | device memory write — project and global writes: forced | kind | - | - | resolved | 0x14 and 0x18 writes are never sent. (source: p10) | - |
| d175 | device memory write — project and global reads: forced | kind | - | - | resolved | Contract 1 reads identity only, so 0x13 and 0x17 are not sent either. (source: the stakeholder's brief) | - |
| d176 | device memory write — attempted write: An attempt from any part of the host is refused before reaching the unit and logged as a hazard. | source | 9 | 1 | bounded | - | - |
| d177 | live — press to replica: 100 ms p95 on the home network. (measure: time from a press on the unit to the replica showing it (p95); threshold: <= 100 ms) | quality | 3 | 3 | noted | - | - |
| d178 | live — LED parity: Every LED matches after any sequence of actions. (measure: share of controls whose replica LED matches the unit's LED state; threshold: == 1) | quality | 4 | 2 | noted | - | - |
| d179 | live — Session redraw: forced (measure: time from the return-to-Session report to all host LEDs restored; threshold: <= 100 ms) | quality | - | - | resolved | Acceptance scenario 4. (source: PROTOCOL-SPEC.md §9 scenario 4) | - |
| d180 | hot (reload) — write to live: forced (measure: time from layout file write to unit and replica showing it (p95); threshold: <= 1000 ms) | quality | - | - | resolved | Stated as 'within a second'. (source: the stakeholder's brief) | - |
| d181 | precise — complete error rows: forced (measure: share of error kinds whose message names file, line, control, problem and fix; threshold: == 1) | quality | - | - | resolved | All five parts are named. (source: the stakeholder's brief) | - |
| d182 | short, readable — minimal layout length: Range forms make a minimal working layout about 8 lines long. (measure: lines for a layout with one device, one 16-pad note page and one 8-strip CC bank; threshold: <= 8) | quality | 3 | 3 | noted | - | - |
| d183 | short, readable — guide examples validate: Every worked example in the guide validates. (measure: share of the guide's worked examples that validate as shipped; threshold: == 1) | quality | 3 | 1 | noted | - | - |
| d184 | expressive — velocity and aftertouch exact: forced (measure: share of played velocity and aftertouch values arriving at the target as played (or as the rule says); threshold: == 1) | quality | - | - | resolved | 'velocity untouched' admits no loss. (source: the ask: "velocity untouched") | - |
| d185 | discoverable — steps to a control's meaning: At most two clicks: select the control, or pick the page or bank. (measure: clicks to see what any control does on any page, bank or Shift layer; threshold: <= 2) | quality | 5 | 4 | noted | - | - |
| d186 | easy for an agent to write correctly — first-try valid layout: 9 out of 10 first tries pass validation. (measure: share of cold-agent attempts, given only the schema and guide, that validate on the first try; threshold: >= 0.9) | quality | 6 | 5 | bounded | - | - |
| d187 | maximum flexibility — unrequired caps: forced (measure: limits not imposed by the hardware; threshold: == 0) | quality | - | - | resolved | Maximum flexibility admits no cap beyond 8 scene buttons and 6 strip-mode buttons. (source: the ask: "maximum flexibility") | - |

## 3 · Context — execution-ready
Role: informational — orientation, except §3.5 below.
- **3.1 Code map:** Work in the APC64 Control repo root. Create package `_apc64_host/`, mirroring the layers of the MOTU mixer project's `_motu_mixer/`. `domain/`: controls, layout model, resolver, toggle/feedback state, routing rules, and the outbound SysEx allowlist values; no I/O. `protocol/`: APC64 SysEx/LED/OLED encode and decode, ported from `tools/daw_probe.py` and `tools/apc64_project.py` (pack7/unpack7, framing). `application/`: device session (consent → hold → release), layout pipeline (debounce → validate → compile → version → swap), router, play stream, abstract ports. `infrastructure/`: ALSA rawmidi adapter in the style of MOTU's `alsa_rawmidi.py` (ctypes libasound, port found by name via `amidi -l`), ALSA sequencer adapter for target/feedback ports, file watcher, version store, desktop notifier, and a simulated APC64 that replays the formats in `fixtures/*.log`. `presentation/`: FastAPI app, WebSocket hub, view model, and `static/` (one HTML page plus ES modules, `node --test` specs). Also add: `__main__.py` (service and CLI entry), `config.py` (config.local KEY=VALUE overridable by env), `layouts/` (tracked; example layouts), `docs/layout-guide.md` and `docs/layout.schema.json`, `deploy/apc64-host.service` and `deploy/apc64-host.desktop`, `pyproject.toml` (requires-python >=3.14, pytest marker `live`), and README.md. Tests sit next to modules as `test_*.py`, as in MOTU.
- **3.2 System layout:** One service process on the host machine, listening on port 5058 (LAN). It owns: the APC64 through exclusive ALSA rawmidi on its DAW subdevice (in/out) and Notes/Custom subdevices (read only), only while held; target and feedback devices as ALSA sequencer ports by name (e.g. 'USB MIDI Interface' card → MPC, Bitwig virtual ports); browsers on loopback/private ranges over HTTP and WebSocket; the agent CLI over the same HTTP API; desktop notifications via notify-send/D-Bus. Files: `layouts/*.yaml` in the repo (tracked); version copies and a state file (holding marker, calibration, remembered strip values) in a git-ignored state directory, default `~/.local/state/apc64-host/`. Managed by a systemd user unit enabled at login.
- **3.3 Repository constraint:** Deliver on the current trunk branch `master` of the APC64 Control repo, with no feature branches and small rollback-safe commits. The working tree already holds uncommitted edits (NOTES-daw-mode.md, PROTOCOL-SPEC.md and private working notes) and untracked fixtures; keep them and never revert or rewrite them. Before editing, read what you touch: the stakeholder's brief, PROTOCOL-SPEC.md §3–§10, NOTES-daw-mode.md and the fixture you replay. PROTOCOL-SPEC.md may change only to turn a [TBD] into [LIVE] with a capture added under fixtures/. tools/ and fixtures/ are evidence: read and port from them, never modify them. The MOTU mixer project is a read-only template.
- **3.4 Execution environment:** The host machine, Garuda Linux (rolling). Python 3.14.7 system interpreter, with a per-project .venv as in MOTU (python-rtmidi is not installed and not needed). Node v26.10.0 for `node --test`. amidi, aconnect, notify-send and gdbus are present. The APC64 is attached (its card number moves; always resolve it by name), and so is a 'USB MIDI Interface'. Bitwig Studio is installed. Hermetic gate: `pytest` (live tests deselected by default) plus `node --test` on the static JS. Live gate: `APC64_LIVE=1 pytest -m live` with the unit attached; each run must end with the unit out of DAW mode. Attended live checks (Bitwig busy, unplug, encoder, shifted pads, pad position, OLED limits, calibration, LED looks) need the user at the machine.
- **3.5 Tools/endpoints:**
  HTTP JSON on :5058, used identically by the page and by the CLI `python -m _apc64_host <cmd>` (take, release, ports, layouts, validate PATH, load NAME, page N, bank N, state, watch, versions NAME, restore NAME VERSION).
  - `GET /api/state` → {unit:{status: absent|asking|busy|no_permission|held|unplugged|maybe_stuck, holder, taken_by, firmware, warnings, view}, layout, page:{n,name}, bank:{n,name}, shift, controls:{id:{label_base,label_shift,empty,missing,toggle,led:{colour,behaviour},bar}}, oled:[row0,row1], errors:[{file,line,control,problem,fix}], warnings, routing:{notes,custom,status}, calibration:{at}|null}
  - `POST /api/unit/take|decline|release` → {status}
  - `GET /api/ports` → [{name,direction,present}]
  - `GET /api/layouts` → [{name,file,valid,pages,banks}]
  - `POST /api/validate` {path|text} → {valid,errors,warnings,counts:{pages,banks,pads,strips,…}}
  - `POST /api/layout` {name}, `POST /api/page` {n}, `POST /api/bank` {n}, `POST /api/shift` {held} → state or error {problem,allowed}
  - `POST /api/control/{id}/press|release|move` {value} (replica input, same path as the unit)
  - `GET /api/controls/{id}` → detail card {base,shift,mode,feedback,port_status,elsewhere:[{page,bank,layer,binding}],reachable}
  - `GET /api/overview` → every page and bank, compact
  - `GET /api/layouts/{name}/versions` → [{id,at}]; `POST /api/layouts/{name}/restore` {id}
  - `POST /api/tweak` {layout,page|bank,layer,control,field,value,base_hash} → {ok}|{error}
  - `POST /api/learn` {mode: touch|midi|off, port?}
  - `POST /api/calibrate` {step}
  - `GET /api/activity?limit=200` → [{at,control,message,port,result: sent|not_sent|refused|unbound|dropped,reason}]
  - `GET /api/device-log` → messages sent to the APC64, with refused attempts flagged as hazards
  - WebSocket `/ws` (page: state diffs + activity) and `/ws/play` (agents: ordered events {at,source,view,control|note,value,velocity,aftertouch,sent,reason}; slow consumers closed with a notice).
  All endpoints refuse non-private clients and foreign Origin/Host headers.
Role of §3.5: binding — the observable surface the acceptance criteria are read against.

## 4 · Plan

### 4.1 Sub-outcomes
| id | sub-outcome (behavioral) | realizes |
|---|---|---|
| pi1 | The host finds the APC64 by port name, asks the user before taking it (desktop notification and page banner), and enters DAW mode only after their yes and a confirmed APC64 identity. It shows Busy and stays hands-off while another program holds the port, and asks again on replug or when the port frees. | inv12, inv13, inv16, inv17 |
| pi2 | Release from the page, service stop, SIGTERM, unplug and any internal failure all hand the unit back: LEDs and OLED cleared (if still connected), DAW mode off, port free for Bitwig. | inv14 |
| pi3 | Nothing the host does can write the unit's memory or its Notes/MIDI/Custom ports. Every attempted project (0x14) or global (0x18) write is refused before reaching the unit and logged. | inv15, inv11 |
| pi4 | An agent writes a short YAML layout (devices named once, range forms, human names) and validates it from the CLI/API against the published schema. It gets either acceptance or errors naming the file, line, control, problem and fix. Layout count is uncapped, and each layout holds up to 8 pages and 6 banks. | inv4, inv19 |
| pi5 | A valid layout written to layouts/ is live on the unit and in the replica within 1 s. An invalid or half-written one leaves the live layout untouched and shows its errors. Every version that went live can be restored exactly. | inv18, inv19, inv20 |
| pi6 | Pressing, touching, sliding or turning any bindable control on the unit or in the replica sends exactly the MIDI action bound for the current layout, page, bank and Shift state. That covers momentary and latching toggles and 14-bit strips. Unbound controls send nothing. LEDs and strip bars follow toggle state or the feedback MIDI received on the named input ports. | inv1, inv2, inv10 |
| pi7 | The scene buttons switch pages and the strip-mode buttons switch banks, with their LEDs showing current, defined and empty. Shift + encoder browses and loads layouts by name on the OLED, and releasing Shift cancels. Every layout, page or bank change shows its name on the OLED. | inv3, inv5 |
| pi8 | Switching the unit from Note/Chord/Step/Project/Custom back to Session view restores every host-owned LED within 100 ms. | inv8 |
| pi9 | While the host holds the unit, notes played in Note/Chord/Step/Custom view are routed to the layout's target device and channel with velocity untouched. Aftertouch is passed, converted to channel pressure or dropped, and transpose or remap is applied only when the layout asks, the same way every time. | inv6, inv10, inv11 |
| pi10 | Every press and played note appears, in order, in the replica, the activity list (control → message → port) and the agent's play stream. Pad positions for Note/Chord/Step-view notes are marked as calibrated or as an assumption. | inv7, inv9 |
| pi11 | The browser replica labels every control with its current meaning and shows unbound controls as empty. It provides an always-visible, clickable nav bar for layout, page, bank and Shift, a live Shift preview, a per-control detail card covering both layers and where else the control is bound, and an overview of every page and bank. | inv1, inv2, inv3 |
| pi12 | On the page, the user selects a control by touching it on the unit, or binds it by MIDI-learn from a chosen input port. The user then saves a single-control tweak (assignment, label, colour, momentary/toggle) that changes only that control and leaves the rest of the file as written. | inv21 |
| pi13 | A documented CLI and HTTP/WebSocket API let an agent do everything the page does, with the same results: list ports and layouts, validate, load, switch layout/page/bank, read state, watch play. | inv22 |
| pi14 | The page, CLI and API work without login from loopback and the configured private ranges. Clients outside those ranges and requests from foreign web origins are refused. | inv23 |

### 4.2 Acceptance
Role: binding — the inspection criteria. Each row's first cell is `<row id> · <sub-outcome id>`.
| ↦ sub-outcome | Given | When | Then |
|---|---|---|---|
| A1 · pi1 | The service is running, Bitwig is not running, and the APC64 was last seen as ALSA card 4. | The user plugs the APC64 in and it appears as card 5. | Within 5 s a desktop notification and a page banner ask 'Take control of APC64?'. The unit is not in DAW mode and its LEDs are untouched. |
| A2 · pi1 | The banner is asking, and the active layout 'Jam' binds pad r1c1 to note 36 in red. | The user clicks Yes in the banner. | The unit identifies as an APC64 with firmware 1.2.1.6 and enters DAW mode. The OLED shows 'Jam', pad r1c1 lights red, and the page shows 'Held'. |
| A3 · pi1 | The desktop notification 'Take control of APC64?' is showing. | The user clicks its Take action. | The unit enters DAW mode and the page shows 'Held'. |
| A4 · pi1 | The banner is asking. | The user clicks No, then starts Bitwig with the APC64 enabled. | Bitwig opens the APC64 and drives its LEDs. The host's page shows 'Not held'. |
| A5 · pi1 | Auto-accept is switched on in the service's settings. | The user plugs the APC64 in. | The unit enters DAW mode without a question, and the page shows 'Held (taken automatically)'. |
| A6 · pi1 | The banner has been asking for 10 minutes without an answer. | The user looks at the unit and the page. | The unit is not in DAW mode and the banner still asks. |
| A7 · pi1 | The banner and the notification are both asking. | The user clicks Yes in the banner, and 2 s later clicks Take in the notification. | The unit is taken once: the OLED does not flicker or re-run, and the second click is answered 'already held'. |
| A8 · pi1 | The unit was held after the user's yes, and then released it. | Ten minutes pass with the unit still plugged in. | The unit stays out of DAW mode and the banner asks 'Take control of APC64?' again. |
| A9 · pi1 | Bitwig is running with the APC64 enabled and lighting its pads. | The user clicks Yes in the banner. | The page shows 'Busy: held by Bitwig Studio'. Bitwig's pad colours stay unchanged and the host sends nothing to the unit. |
| A10 · pi1 | The Tonnetz prototype page with MIDI access is open in Chrome. | The user clicks Yes in the banner. | The page shows 'Busy: held by Chrome' and the unit is untouched. |
| A11 · pi1 | The replica page is open in Chrome on the host machine, and the host does not hold the unit. | The user starts Bitwig with the APC64 enabled. | Bitwig opens and drives the APC64, because the replica page holds no MIDI access to it. |
| A12 · pi1 | The service is running, but its user currently has no permission to open the APC64 (nobody has an active desktop session at the host machine). (corrected by the consistency check: A systemd user unit enabled at login does not run 'from boot', so the precondition is restated in terms of the permission it tests.) | The user clicks Yes from their phone. | The page shows 'No permission to open APC64', not 'Busy'. |
| A13 · pi1 | The page shows 'Busy: held by Bitwig Studio'. | The user quits Bitwig. | Within 5 s the banner asks 'Take control of APC64?', and the unit stays out of DAW mode. |
| A14 · pi1 | The host holds the unit. | The user starts Bitwig with the APC64 enabled. | Bitwig reports the APC64 as unavailable. The unit keeps showing the host's layout. |
| A15 · pi1 | Another program holds only 'APC64 Notes (APC64)', and layout 'Jam' routes Notes-port notes to device 'mpc' channel 2. | The user clicks Yes. | The unit is held and its buttons work. The page shows 'APC64 Notes busy: expressive pads not routed', and notes played in Note view reach nothing. |
| A16 · pi1 | No APC64 is attached, and 'Jam' binds pad r1c1 to note 36 on device 'mpc' channel 10. | The user clicks pad r1c1 in the replica. | The page shows 'APC64 not connected', and the MPC receives note-on 36 on channel 10. |
| A17 · pi1 | Two APC64 units are plugged in. | The service starts. | The banner offers one APC64 and the page shows 'second APC64 ignored'. |
| A18 · pi1 | A device on a port named 'APC64 DAW (APC64)' does not answer the identity request. | The user clicks Yes. | After 2 s the page shows 'No APC64 identity reply'. No DAW-mode message is sent. |
| A19 · pi1 | The unit's identity reply reports firmware 1.2.2.0. | The user clicks Yes. | The unit is held, and the page shows the warning 'untested firmware 1.2.2.0'. |
| A20 · pi1 | The host was killed abruptly while holding the unit, so the unit is still in DAW mode. | The service starts again. | The banner says 'APC64 may still be in DAW mode: Take to reset, or replug it', and nothing is sent to the unit until the user says yes. |
| A21 · pi1 | The banner is asking, and the user's phone at 192.168.1.23 has the page open. | The user taps Yes on the phone. | The unit enters DAW mode, and both the phone and the desktop page show 'Held'. |
| A22 · pi1 | The banner is asking. | An agent asks the host, from the command-line tool, to take the APC64. | The unit enters DAW mode, and the page shows 'Held (taken by command-line tool)'. |
| A23 · pi1 | The unit was held, and the user then unplugged it. | The user plugs it back in. | The banner asks 'Take control of APC64?', and the unit is not in DAW mode. |
| A24 · pi1 | The unit is held. | The host machine suspends and later resumes. | After resume the banner asks again, and the host does not drive the unit until the user says yes. |
| A25 · pi2 | The unit is held with 'Jam' drawn. | The user clicks Release on the page. | All pad, button and strip LEDs go dark and the OLED goes blank, then the unit leaves DAW mode. Bitwig can open the APC64 right away. |
| A26 · pi2 | The unit is held. | The service is told to stop (a system shutdown). | The unit's LEDs and OLED go blank, it leaves DAW mode, and its port is free. |
| A27 · pi2 | The unit is held. | The user pulls its USB cable. | The page shows 'APC64 unplugged: released', and the page and API keep working. |
| A28 · pi2 | The unit is held. | A fault inside the host stops it from handling presses. | The unit's LEDs and OLED go blank, it leaves DAW mode, and the page shows 'Released after an internal error'. |
| A29 · pi2 | The unit is not held. | The user clicks Release. | The page says 'APC64 is not held', and nothing reaches the unit. |
| A30 · pi2 | The unit is held. | An agent asks the host, from the command-line tool, to release the APC64. | The unit goes dark, leaves DAW mode, and the page shows 'Not held'. |
| A31 · pi3 | The unit is held. | Some part of the host tries to send a project write for slot 0. | The unit's pads keep their project colours, the activity list shows 'refused: project write (0x14)', and a hazard is logged. |
| A32 · pi3 | The user runs a full session: take, play every control, switch layouts, release. | Everything the host sent to the unit is reviewed. | It holds only the identity request, the DAW-mode handshake on/off, LED messages and OLED text. There are no project or global reads or writes. |
| A33 · pi3 | An agent writes a layout declaring device 'apc' as port 'APC64 Notes (APC64)'. | The agent validates it. | Validation fails: 'apc.yaml line 3: device apc targets an APC64 port; the host never sends to the APC64's own ports, choose another port'. |
| A34 · pi4 | An agent writes an 8-line layout 'Jam': device mpc = 'MPC Live III MIDI 1'; page 1 'Drums': pads r1c1–r2c8 = notes from 36 on mpc channel 10; bank 1 'Mix': strips 1–8 = CC 20–27 on mpc channel 1. | The agent validates it. | The answer is 'valid: 1 page, 1 bank, 16 pads, 8 strips bound'. |
| A35 · pi4 | layouts/ holds 50 layouts, each with 8 fully bound pages on both layers and 6 banks. | The user lists layouts and loads the 50th. | All 50 are listed and validate. The 50th loads, and its page 8 Shift layer is labelled in the replica. |
| A36 · pi4 | A layout defines 'page 9'. | It is validated. | Error: 'jam.yaml line 40: page 9: the APC64 has 8 scene buttons, so pages are 1–8'. |
| A37 · pi4 | layouts/ is empty. | The user takes the unit. | The unit is held with all LEDs dark, and the OLED shows 'No layout'. |
| A38 · pi4 | jam.yaml line 12 reads 'pads r1c1-r1c8 notes 36' (colon missing). | It is validated. | Error: 'jam.yaml line 12, pads r1c1-r1c8: expected ':' after the control name; write "pads r1c1-r1c8: notes 36"'. |
| A39 · pi4 | jam.yaml binds 'pad r9c1' on line 8 and uses device 'mcp' on line 14. | It is validated. | Two errors in line order: 'line 8, pad r9c1: no such pad, pads are r1c1–r8c8' and 'line 14: unknown device mcp, declared devices: mpc'. |
| A40 · pi4 | Page 1 base layer binds 'pads r1c1-r1c8' on line 10 and 'pads r1c5-r2c4' on line 11. | It is validated. | Error: 'lines 10 and 11 both bind pads r1c5–r1c8 on page 1 base layer; keep one'. |
| A41 · pi4 | Page 1 has 'pads r1c1-r1c8: notes from 36' and 'pad r1c3: cc 64'. | The layout is live and the user presses pad r1c3, then pad r1c4. | Pad r1c3 sends CC 64 and pad r1c4 sends note 39. |
| A42 · pi4 | jam.yaml and jam2.yaml both say 'name: Jam'. | Both are in layouts/. | Error naming both files. The already-loaded 'Jam' (jam.yaml) stays active. |
| A43 · pi4 | Page 2 is named 'Drums and Percussion Kit'. | The layout is validated and the user switches to page 2. | It is valid, with the warning 'page name longer than 14 characters, OLED shows "Drums and Perc"'. The OLED shows 'Drums and Perc', and the page shows the full name. |
| A44 · pi4 | A Python script writes 'tonnetz.yaml' with 64 single-pad entries. | The file lands in layouts/. | It is validated and listed like any other layout, and loading it lights the pads as written. |
| A45 · pi4 | An agent has a draft at /tmp/draft.yaml. | It validates that path from the command-line tool. | It gets the validation result, and the live layout on the unit is unchanged. |
| A46 · pi4 | The service is stopped. | An agent validates jam.yaml and then asks to load it. | Validation returns 'valid'. The load says 'service not running on port 5058'. |
| A47 · pi4 | The shipped schema and authoring guide. | Each worked example in the guide is validated. | Every example is reported valid. |
| A48 · pi4 | A fresh agent with only the schema and guide. | It is asked 10 times for 'a layout with 16 drum pads to MPC channel 10 and 8 strips as CC 20–27'. | At least 9 of the 10 layouts it writes validate on the first try. |
| A49 · pi4 | Bank 1 binds strip 1 as a toggle. | It is validated. | Error: 'line 22, strip 1: a strip position cannot be a toggle; remove "toggle"'. |
| A50 · pi5 | 'Jam' is live, and pad r1c1 is note 36. | The agent changes pad r1c1 to note 38 in jam.yaml. | Within 1 s the replica labels pad r1c1 'Note 38 → mpc', pressing it sends note 38, and a new version of 'Jam' is listed. |
| A51 · pi5 | 'Jam' is live. | An editor writes half of jam.yaml, then the rest 200 ms later. | The unit changes once, to the completed file. The half-written content never shows on the unit or the page. |
| A52 · pi5 | 'Jam' is live, with pad r1c1 = note 36. | The agent saves jam.yaml with an unknown device on line 5, then fixes it a minute later. | Pad r1c1 keeps sending note 36, the error shows on the page and no new version appears. After the fix the error clears and a new version is listed. |
| A53 · pi5 | 'Jam' is live. | jam.yaml is saved again with identical content. | No reload happens and no new version is listed. |
| A54 · pi5 | 'Jam' has 30 listed versions, and the one from 10:42 bound pad r1c1 to note 40. | The user restores the 10:42 version. | All 30 versions remain listed, pad r1c1 sends note 40, and every other control behaves as it did at 10:42. |
| A55 · pi5 | Several versions of 'Jam' exist. | The user checks the repository's git status. | Only layouts/jam.yaml can show as changed. No version copy appears. |
| A56 · pi5 | 'Jam' is live. | jam.yaml is deleted. | The unit keeps playing 'Jam', and the page shows 'file deleted, still active'. |
| A57 · pi5 | jam.yaml has an error on line 7. | The user reads it on the page and the agent reads it from the command-line tool. | Both show the identical text 'jam.yaml line 7, …'. |
| A58 · pi6 | In Session view, pad r1c1 = note 36 on mpc channel 10, momentary. | The user taps pad r1c1 softly. | The MPC receives note-on 36 velocity 127 on channel 10, then note-off 36 when the user lets go. |
| A59 · pi6 | The Play button = CC 118 value 127 on mpc channel 1. | The user presses Play. | The MPC receives CC 118 value 127, and the replica labels Play 'CC118 → mpc'. |
| A60 · pi6 | Device 'bitwig' = port 'Bitwig Studio In'. Strip 3 = pitch bend on bitwig channel 2, and its touch = note 60. | The user touches strip 3 and slides to the middle (14-bit 8192). | Bitwig receives note-on 60, then pitch bend 8192 on channel 2. |
| A61 · pi6 | Strip 4 = 7-bit CC 21 on mpc channel 1. | The user slides strip 4 to the top (16383). | The MPC receives CC 21 value 127. |
| A62 · pi6 | The encoder turn = CC 30 on mpc, currently at value 64. | The user turns the encoder one step clockwise. | The MPC receives CC 30 value 65. |
| A63 · pi6 | The encoder turn = CC 30 on mpc, at value 64. | The unit reports one fast turn as value 3. | The MPC receives CC 30 value 67. |
| A64 · pi6 | Play base = CC 118 and Play Shift = CC 119. | The user holds Shift and presses Play. | The MPC receives CC 119 and not CC 118. |
| A65 · pi6 | The unit is held in Session view. | The user presses the unit's Note view button. | No bound action is sent, and the replica shows 'View: Note'. |
| A66 · pi6 | The layout names bank 5 'FX'. | The user presses the fifth strip-mode button from the left. | Bank 5 'FX' is selected. The replica's strip-mode buttons carry the names printed on the unit, with bank names beneath. |
| A67 · pi6 | Pad r1c1 Shift = note 48 on mpc. | The user holds Shift and presses pad r1c1 on the unit. | The MPC receives note-on 48, and the live check records that shifted pads reach the host. |
| A68 · pi6 | Pad r1c1 = note 36 and pad r1c2 = note 37. | The user presses both at the same moment. | The MPC receives note-on 36 and note-on 37. |
| A69 · pi6 | Pad r1c1 is the bottom-left pad in the layout. | The user presses the physically bottom-left pad. | Replica pad r1c1 lights and pad r1c1's binding is sent. |
| A70 · pi6 | Pad r1c1 = note 36 on mpc. | The user clicks pad r1c1 in the replica. | The MPC receives note-on 36 then note-off 36, exactly as for a hardware press. |
| A71 · pi6 | Page 1 pad r1c1 = note 36 and page 2 pad r1c1 = note 50. | The user holds pad r1c1, presses scene 2, then lets go of the pad. | The MPC receives note-on 36 and later note-off 36. It never receives note 50. |
| A72 · pi6 | Track 1 = CC 20 value 127, then program change 5, on mpc. | The user presses track 1. | The MPC receives CC 20 127 first, then program change 5. |
| A73 · pi6 | Strip 2 = CC 22 and last sent value 64. | Strip 2 reports a position that is again 64 after scaling. | Nothing new is sent to the MPC. |
| A74 · pi6 | Pad r8c8 has no binding on page 1. | The user presses pad r8c8. | Nothing is sent, the replica shows r8c8 as empty, and the activity list shows 'pad r8c8: unbound'. |
| A75 · pi6 | Track 1 = toggle CC 20 on mpc, currently off. | The user presses and releases track 1 twice. | The MPC receives CC 20 127 on the first press and CC 20 0 on the second, and nothing on the releases. Track 1's LED goes on, then off. |
| A76 · pi6 | Track 1's toggle is on. | The agent changes only pad r1c1 in the file, and later changes track 1's binding. | After the first change track 1 is still on. After the second it is off. |
| A77 · pi6 | Track 1 = toggle CC 20 on bitwig, with feedback CC 20 from bitwig, currently on. | Bitwig sends CC 20 value 0, then the user presses track 1. | The LED goes off when the CC arrives, and the press sends CC 20 127. |
| A78 · pi6 | Pad r1c1 has feedback note 36 from 'mpc' input, on colour green, off colour dim white. | The MPC sends note-on 36 velocity 100, then note-off 36. | Pad r1c1 turns green on the unit and in the replica, then dim white. |
| A79 · pi6 | The OLED shows 'Jam', and track 1 has feedback CC 20 from bitwig. | Bitwig sends CC 20 value 99. | Track 1's LED lights and the OLED still shows 'Jam'. |
| A80 · pi6 | No feedback rule mentions CC 99. | The MPC sends CC 99 value 5. | No LED changes. |
| A81 · pi6 | Track 1 has feedback CC 20 from bitwig. | Bitwig sends 50 CC 20 messages alternating 127 and 0, ending with 0. | Track 1's LED ends off on the unit and in the replica. |
| A82 · pi6 | Page 2 pad r1c1 has feedback note 50 from mpc, and page 1 is shown. | The MPC sends note-on 50, then the user presses scene 2. | Page 2's pad r1c1 is lit in its on colour when page 2 appears. |
| A83 · pi6 | Device 'mpc' = 'MPC Live III MIDI 1', which is unplugged, and pad r1c1 = note 36 on mpc. | The user presses pad r1c1. | The replica labels r1c1 'Note 36 → mpc (missing)', and the activity list shows 'pad r1c1 → note 36 → mpc: not sent, mpc missing'. |
| A84 · pi6 | A layout declares device mpc = 'MIDI 1', and ports 'MPC Live III MIDI 1' and 'USB MIDI Interface MIDI 1' both exist. | It is validated. | Error: 'line 2, device mpc: "MIDI 1" matches MPC Live III MIDI 1 and USB MIDI Interface MIDI 1; write the full name'. |
| A85 · pi6 | Devices 'drums' and 'keys' both name 'MPC Live III MIDI 1'. | The user presses a 'drums' pad and a 'keys' pad. | The MPC receives both notes. |
| A86 · pi6 | 'mpc' is missing and its labels read '(missing)'. | The user plugs the MPC in. | Within 5 s the labels drop '(missing)', and pressing pad r1c1 sends note 36 to the MPC. |
| A87 · pi6 | Track 2 has a base binding (CC 21) and no Shift binding. | The user holds Shift and presses track 2. | Nothing is sent, and the Shift preview shows track 2 as empty. |
| A88 · pi6 | Play Shift = CC 119. | The user holds the page's Shift button and presses Play on the unit. | The MPC receives CC 119, and every replica label shows its Shift meaning while the user holds it. |
| A89 · pi7 | 'Jam' has page 1 'Drums' and page 2 'Keys', and pages 3–8 are empty. | The user presses scene 2. | Page 2 is shown and the OLED shows 'Keys' for about 2 s. Scene LED 2 is full, 1 is dim and 3–8 are off. The MPC receives nothing. |
| A90 · pi7 | Page 5 is empty. | The user presses scene 5. | The current page stays, and the OLED shows 'Page 5 empty'. |
| A91 · pi7 | Page 3 has bindings but no name. | The user presses scene 3. | The OLED and nav bar show 'Page 3'. |
| A92 · pi7 | Bank 2 has strip 1 with feedback last at 100 and strip 2 with no feedback, last touched at 4000, while bank 1 is shown. | The user presses the bank 2 strip-mode button. | Strip 1's bar shows 100 (scaled) and strip 2's bar shows 4000 (scaled), on the unit and in the replica. |
| A93 · pi7 | Page 2 and bank 1 are shown. | The user presses the bank 3 strip-mode button. | Bank 3 is shown and page 2 stays. |
| A94 · pi7 | Bank 4 is empty. | The user presses the bank 4 strip-mode button. | The current bank stays, and the OLED shows 'Bank 4 empty'. |
| A95 · pi7 | Layouts 'Ambient', 'Jam' and 'Tonnetz C' exist, and 'Jam' is live. | The user holds Shift, turns the encoder 1 step clockwise, and presses the encoder. | The OLED shows 'Tonnetz C' while browsing. After the press 'Tonnetz C' is live and its name shows for 2 s. |
| A96 · pi7 | 'Jam' is live. | The user holds Shift, turns to 'Tonnetz C', and lets go of Shift without pressing. | 'Jam' stays live and the OLED returns to 'Jam'. |
| A97 · pi7 | Page 1 is shown. | The user holds Shift and presses scene 4. | The page stays 1, and nothing is sent to any device. |
| A98 · pi7 | Track 1's toggle on page 1 is on. | The user presses scene 2, then scene 1. | Track 1's LED on page 1 is on again. |
| A99 · pi7 | A layout is named 'Café'. | It is loaded. | The OLED shows 'Caf?' and the page shows 'Café'. |
| A100 · pi7 | 'Jam' is live on page 1 'Drums' and bank 1 'Mix', and no change happened in the last 2 s. | The user looks at the OLED. | Row 0 reads 'Jam' and row 1 reads 'P1 Drums \| B1' (the 14-character cut of 'P1 Drums \| B1 Mix'). (corrected by the consistency check: OLED rows are cut to 14 characters (d108, d109), and the previous text was 15 characters.) |
| A101 · pi8 | 'Jam' is drawn in Session view. | The user switches the unit to Note view and back to Session view. | Every host-owned LED shows 'Jam' again within 100 ms of the return. |
| A102 · pi9 | Note view. 'Jam' routes the Notes port to mpc channel 2, aftertouch passed. | The user presses a pad playing note 53 at velocity 56, squeezes to aftertouch 10, and lets go. | The MPC receives note-on 53 velocity 56 channel 2, poly aftertouch 53 10, poly aftertouch 53 0, and note-off 53. |
| A103 · pi9 | Note view, aftertouch converted to channel pressure, with notes 53 and 57 held. | Note 53's aftertouch reaches 40 and note 57's reaches 90. | The MPC receives channel pressure 90 on channel 2 and no poly aftertouch. |
| A104 · pi9 | Note view, aftertouch dropped. | The user plays note 53 at velocity 56 with aftertouch. | The MPC receives only note-on 53 velocity 56 and note-off 53. |
| A105 · pi9 | Chord view, routed to mpc channel 2 with aftertouch passed. | The user presses a chord pad at velocity 80, playing notes 60, 64 and 67. | The MPC receives three note-ons at velocity 80 and per-note aftertouch for each. |
| A106 · pi9 | Step view, routed to mpc channel 2. | The unit sends note 41 at velocity 18. | The MPC receives note-on 41 velocity 18 on channel 2. |
| A107 · pi9 | Custom view. 'Jam' routes the Custom port to mpc channel 3. | The user plays a pad sending note 36 at velocity 11 on the Custom port. | The MPC receives note-on 36 velocity 11 on channel 3. |
| A108 · pi9 | Custom view, routed to mpc channel 3. | A strip sends CC 20 value 64 on the Custom port. | The MPC receives CC 20 value 64 on channel 3. |
| A109 · pi9 | The unit reports Drum view, and the Notes port is routed to mpc channel 10. | The user plays note 38 at velocity 90. | The MPC receives note-on 38 velocity 90 on channel 10. |
| A110 · pi9 | Note view, aftertouch passed. | The user holds one pad for 4 s, producing 200 aftertouch values. | The MPC receives all 200 values, in the order played. |
| A111 · pi9 | Note view, routed to mpc channel 2. | The unit ends note 53 with a note-on at velocity 0. | The MPC receives the end of note 53 on channel 2. |
| A112 · pi9 | Chord view, where two held chords both contain note 60. | The second chord is pressed. | The MPC receives a second note-on 60. |
| A113 · pi9 | Note view, transpose +12, with note 53 held (sent to the MPC as 65). | The agent changes transpose to 0, then the user lets go. | The MPC receives note-off 65. |
| A114 · pi9 | The host does not hold the unit, and the unit is in Note view. | The user plays a pad. | The host forwards nothing to the MPC. |
| A115 · pi9 | 'Jam' has no routing rule for the Notes port. | The user plays note 53 in Note view. | Nothing goes to any device. The played-notes row shows 'F3 (53) vel 56', and the page says 'expressive pads not routed in this layout'. |
| A116 · pi9 | Note view, transpose +24. | The user plays note 120. | Nothing is sent, and the activity list shows 'dropped: note 144 out of range'. |
| A117 · pi9 | Note view, remap 36→38 only, transpose 0. | The user plays note 36, then note 40. | The MPC receives note 38, then note 40. |
| A118 · pi9 | Note view, Notes routed to mpc channel 2. | The user presses scene 2 to change page, then plays note 53. | The MPC still receives note 53 on channel 2. |
| A119 · pi9 | The same 2-minute recorded performance (presses, strip moves, Note-view notes with aftertouch, two view switches) and the same layout. | It is played into the host twice. | The two runs send identical messages in identical order, and the replica ends in the same state. |
| A120 · pi10 | Pad r1c1 = note 36 on mpc channel 10, and an agent is watching the play stream. | The user presses pad r1c1. | Within 100 ms the replica lights r1c1 and the activity list shows 'pad r1c1 → note 36 ch 10 → MPC Live III MIDI 1: sent'. The agent receives an event with the time, 'unit', 'pad r1c1', velocity 127 and the message sent. |
| A121 · pi10 | Note view, calibrated at 14:02. | The user plays note 53 at velocity 56 on the pad that played it during calibration. | The replica lights that pad at a brightness matching velocity 56, labelled 'calibrated 14:02 (assumed)'. |
| A122 · pi10 | Note view, never calibrated. | The user plays note 53 at velocity 56. | The played-notes row shows 'F3 (53) vel 56 · pad position unknown', and no replica pad lights. |
| A123 · pi10 | Calibrated at 14:02, after which the user changed the Note-view root on the unit. | The user plays a note. | The replica still labels positions 'calibrated 14:02 (assumed)'. |
| A124 · pi10 | An agent opened the play stream and stopped reading. | The user keeps playing for 60 s. | After about 5 s that agent's stream closes with 'stream closed: too slow'. The unit and other watchers carry on unaffected. |
| A125 · pi10 | Two agents are watching the play stream. | The user presses pad r1c1, then track 1. | Both agents receive 'pad r1c1' then 'track 1', in that order. |
| A126 · pi10 | The user has been playing for 10 minutes. | An agent starts watching. | Its first event is the next thing the user does, not earlier history. |
| A127 · pi10 | The user has made 500 presses. | The user looks at the activity list. | It shows the latest 200 entries, newest first. |
| A128 · pi10 | The unit is held with 'Jam'. | The user makes 100 mixed presses, toggles, feedback events and page switches. | Every control's replica LED matches the unit's LED. |
| A129 · pi11 | Pad r1c1 = note 36 on mpc channel 10 (Shift: note 48), and on page 2 it is note 50. | The user selects pad r1c1 in the replica. | Its card shows 'Base: Note 36 → mpc ch 10, momentary', 'Shift: Note 48 → mpc', 'mpc connected', and 'Page 2: Note 50' — one step. |
| A130 · pi11 | The user has the page open on their phone and on their laptop. | The user taps page 2 on the phone. | The laptop's nav bar and replica show page 2 within 100 ms. |
| A131 · pi11 | The laptop page lost Wi-Fi for 30 s, during which the user switched to bank 3. | The connection returns. | The page shows bank 3 and the current LEDs at once. |
| A132 · pi12 | Learn is on in the page, and track 3 = CC 22. | The user presses track 3 on the unit. | The page selects track 3 and opens its card, and nothing is sent to the MPC. |
| A133 · pi12 | Pad r2c1 is selected, with MIDI-learn listening on the 'mpc' input. | The MPC sends CC 74 value 10 on channel 1. | Pad r2c1 becomes 'CC74 → mpc ch 1', and the layout file gains that binding. |
| A134 · pi12 | Pad r2c1 is selected with MIDI-learn on. | The user leaves MIDI-learn before anything arrives. | Pad r2c1 and the layout file are unchanged. |
| A135 · pi12 | jam.yaml has 'pads r1c1-r1c8: notes from 36  # bass line' and a comment block at the top. | The user sets pad r1c3's colour to red on the page and saves. | Pad r1c3 is red. The file gains one entry for pad r1c3 with colour red. The range line, its comment and every other line are byte-identical. |
| A136 · pi12 | Pad r1c1 is selected. | The user sets its channel to 17 and saves. | The page shows 'channel must be 1–16', and jam.yaml is unchanged. |
| A137 · pi12 | Pad r1c3 has an override entry making it red inside a range that makes it blue. | The user sets pad r1c3 back to blue and saves. | The override entry is removed and jam.yaml is byte-identical to before the first tweak. |
| A138 · pi12 | Page 2 is shown. | The user changes pad r1c1's Shift binding to note 52 and saves. | Page 2 Shift pad r1c1 sends note 52. Page 1's pad r1c1 and page 2's base layer are unchanged. |
| A139 · pi12 | The user opened pad r1c1's card, and the agent then rewrote jam.yaml. | The user saves a colour tweak. | The page shows 'layout changed, reload', and the agent's version stays as written. |
| A140 · pi13 | The service holds the unit with 'Jam'. | An agent, from the command-line tool, lists ports and layouts, loads 'Tonnetz C', selects page 3 and bank 2, then reads the state. | The listings include 'MPC Live III MIDI 1' and 'Tonnetz C'. The state reads layout 'Tonnetz C', page 3, bank 2, and the unit and replica show the same. |
| A141 · pi13 | The service is running. | An agent asks for page 0. | It is told 'page must be 1–8', and the page stays the same. |
| A142 · pi13 | The service is running. | The user taps page 2 and, a moment later, an agent selects page 4. | The unit, every page and the agent's state read all show page 4. |
| A143 · pi14 | The user's phone at 192.168.1.23. | The user opens the page. | The replica appears without any login. |
| A144 · pi14 | A client at public address 203.0.113.5. | It asks to switch layout. | It is refused, and the layout is unchanged. |
| A145 · pi14 | The user's browser is showing a page from example.com that tries to switch their layout to 'Ambient'. | That page sends the request to the host. | It is refused, and 'Jam' stays live. |
| A146 · pi14 | A laptop at IPv6 address fd00::23. | It opens the page. | The replica appears without login. |
| A147 · pi14 | A guest's laptop on the user's home Wi-Fi at 192.168.1.40. | The guest opens the page and switches to page 2. | Page 2 is shown on the unit and in every page. |

## 5 · Execution notes
The build proceeds in this order: verify the §2.1 priors first (especially any linchpin), orient in the
§3 context and the repository's own docs, then realize each §4.1 leaf — tests first, implementation,
its §4.2 acceptance as the gate — checking change impact before edits and reusing what exists rather
than rebuilding it. Work outside the executor's reach is flagged, never silently skipped; the outcome
is self-reported to §8.

**Contract review (2026-10-23, the user's delegate):** no assumption is escalated. The open stakeholder
questions q1–q12 in §2.6 are **closed with their stated defaults**, consistent with the user's earlier
answers (in the stakeholder's brief):
- q1: note names use C3 = 60.
- q2: the encoder keeps an absolute 0–127 value.
- q3: channels are written 1–16, with device default channels.
- q4: Session pads send 127 unless the binding sets a fixed velocity.
- q5: Shift is momentary.
- q6: on take, the last layout/page/bank is restored; loading a layout opens page 1 / bank 1.
- q7: aftertouch is folded into its note's activity entry; the play stream carries all of it.
- q8: no MIDI clock.
- q9: bound controls are 25 % when idle and full when on.
- q10: strips default to a white bar.
- q11: a layout's identity is its file name; its display is the name field.
- q12: the CLI command is `apc64`.

The Python package is `_apc64_host` as laid out in §7 (it supersedes the `_apc64` mentioned in
an earlier draft). The hermetic gate is `pytest` plus `node --test` over the static
JS modules. The build is done directly by an Opus builder agent (not a contract walker), in
phases following §6.1's order.

## 6 · Implementation Plan
### 6.1 Task breakdown
Role: binding — the work packages. `design_refs` carries the OWNS/TOUCHES/BINDS/DISCHARGES/WIRES notation of §0 form 2.
| # | task | behavior | realizes | design_refs |
|---|---|---|---|---|
| T1 | Project scaffold (document/wiring): package manifest with dependencies, pytest config (testpaths, live marker deselected by default), the apc64 console script entry, and the package marker; add ignores to the existing .gitignore. | Given a fresh venv, When `pip install -e .[dev]` and `pytest` run, Then the install succeeds with fastapi, uvicorn, websockets, ruamel.yaml and alsa-midi, pytest collects from _apc64_host with live tests deselected, and the `apc64` command is on PATH. | pi13 | OWNS: pyproject.toml, _apc64_host/__init__.py; TOUCHES: .gitignore |
| T2 | Domain base values (domain): MIDI value objects and note names, the control vocabulary and SURFACE catalog, the palette table, layout issues/errors. | Given the domain package, When the control names 'pad r1c1' and 'pads r1c1-r2c8', the note name 'C1' and Channel(17) are parsed or constructed, Then 'pad r1c1' resolves to the bottom-left grid pad in SURFACE, the range expands to 16 pad controls, 'C1' is Note 36, and Channel(17) raises DomainInvariantError naming the field and fix. | inv1, inv17 | OWNS: _apc64_host/domain/__init__.py, _apc64_host/domain/midi.py, _apc64_host/domain/controls.py, _apc64_host/domain/palette.py, _apc64_host/domain/issues.py; AFTER: T1 |
| T3 | Domain aggregate and display values (domain): the Layout aggregate with invariants, OledText, LED state/frame, Calibration, AllowedNetworks. | Given a strip binding marked toggle, a page 9, a layout named 'Café' and a page named 'Drums and Percussion Kit', When the Layout and OledText are built, Then the strip toggle and page 9 raise DomainInvariantError with fixes, the OLED shows 'Caf?' and 'Drums and Perc', and the idle rows read 'Jam' / 'P1 Drums \| B1'. | inv4, inv5, inv9 | OWNS: _apc64_host/domain/layout.py, _apc64_host/domain/oled.py, _apc64_host/domain/leds.py, _apc64_host/domain/calibration.py, _apc64_host/domain/network.py; DISCHARGES: A43, A49, A99, A100; AFTER: T2 |
| T4 | Domain read model and protocols (domain): resolver (meaning, elsewhere, overview), effects and inputs, UnitStatus state machine, outbound policy. | Given 50 layouts each with 8 fully bound pages × 2 layers and 6 banks, When resolve and elsewhere run for page 8 Shift and for pad r1c1, Then every control gets its label (or empty), and pad r1c1's card lists base Note 36, Shift Note 48 and 'Page 2: Note 50'; CONTRACT1_POLICY refuses 0x14. | inv1, inv2, inv4, inv15 | OWNS: _apc64_host/domain/resolver.py, _apc64_host/domain/effects.py, _apc64_host/domain/unit_status.py, _apc64_host/domain/outbound.py; DISCHARGES: A35, A129; AFTER: T3 |
| T5 | HostSurface aggregate and ExpressiveRouter (domain); this task binds the domain package's seam sides. | Given the 'Jam' layout and a feedback/toggle setup, When pad, button, strip, encoder, Shift, scene, strip-mode and feedback inputs and Note/Chord/Step/Custom/Drum played MIDI arrive, Then HostSurface/ExpressiveRouter return exactly the effects of the acceptance values (e.g. note-on 36 ch 10 for r1c1, CC 119 for Shift+Play, channel pressure 90, note-off 65 after transpose change, page 5 empty notice), deterministically on replay. | inv1, inv2, inv3, inv5, inv6, inv8, inv10 | OWNS: _apc64_host/domain/surface_parts.py, _apc64_host/domain/surface.py, _apc64_host/domain/router.py; BINDS: s40:to, s42:to, s56:to, s68:to, s74:to, s75:to; DISCHARGES: A58, A59, A60, A61, A62, A64, A65, A66, A67, A68, A71, A72, A73, A74, A75, A76, A77, A78, A79, A80, A81, A82, A87, A88, A89, A90, A91, A92, A93, A94, A95, A96, A97, A98, A101, A102, A103, A104, A105, A106, A107, A108, A109, A110, A112, A113, A115, A116, A117, A118, A119, A128; AFTER: T4 |
| T6 | Protocol codecs (domain-pure): SysEx frames and identity, the bidirectional surface wire table, MIDI codec, stream splitter. | Given fixture bytes from fixtures/daw-mode-*.log, When decoded, Then '96 00 7F' becomes Press(pad r1c1, 127), 'B0 5A 03' becomes EncoderTurn(3), note-on velocity 0 becomes NoteOff, and handshake/DAW-on/off/OLED frames are byte-exact to PROTOCOL-SPEC.md §4/§6; command_of classifies 0x14 as a project write. | inv8, inv15, inv17 | OWNS: _apc64_host/protocol/__init__.py, _apc64_host/protocol/sysex.py, _apc64_host/protocol/surface_map.py, _apc64_host/protocol/midi_codec.py, _apc64_host/protocol/stream.py; BINDS: s39:to, s43:to, s55:to, s75:from; DISCHARGES: A63, A69, A111; AFTER: T4 |
| T7 | Notation core (domain-pure): grammar tables, SourceRef-carrying parser, compiler with ranges, precedence, devices, note names and port checks. | Given the 8-line 'Jam' text, a missing colon on line 12, 'pad r9c1' + device 'mcp', overlapping ranges, an APC64 port as device, an ambiguous 'MIDI 1' with a port catalog, and 'pad r1c3: cc 64' inside a range, When compiled, Then the valid one reports 1 page/1 bank/16 pads/8 strips and each invalid one yields the exact file:line, control, problem and fix of its acceptance row, with r1c3 overriding the range. | inv4, inv19, pi4 | OWNS: _apc64_host/notation/__init__.py, _apc64_host/notation/grammar.py, _apc64_host/notation/parser.py, _apc64_host/notation/compiler.py; DISCHARGES: A33, A34, A36, A38, A39, A40, A41, A57, A84, A85; AFTER: T3 |
| T8 | Notation splice, schema and authoring docs (domain-pure + document); this task binds the notation package's seam sides. | Given jam.yaml with a commented range and a tweak request, When plan_splice sets r1c3 red, reverts it to blue, and sets page 2 Shift r1c1 to note 52, Then exactly one entry line is added, removed or replaced and all other bytes are identical; every worked example in docs/layout-guide.md and layouts/jam.yaml compiles, and docs/layout.schema.json is regenerated from the grammar. | inv21, pi4 | OWNS: _apc64_host/notation/splice.py, _apc64_host/notation/schema.py, docs/layout.schema.json, docs/layout-guide.md, layouts/jam.yaml; BINDS: s29:to, s58:to, s63:to, s74:from; DISCHARGES: A47, A48, A135, A137, A138; AFTER: T7 |
| T9 | Configuration (wiring): config.local + environment loader and the documented example file. | Given no config.local, a config.local with APC64_HTTP_PORT=6000, and env APC64_AUTO_ACCEPT=1, When Config loads, Then the defaults are port 5058, auto-accept off, port stem 'APC64' and private networks; the file and then the env override; a bad value raises ConfigError naming its key. | inv23, inv17 | OWNS: _apc64_host/config.py, config.local.example; BINDS: s78:to, s88:from; AFTER: T3 |
| T10 | Application ports and module registry (application): the Protocols and port errors, and the HostModule collector. | Given no modules, then a fake module adding one SysexCommand and one route, When modules are collected, Then the first yields an empty policy addition and no routers, and the second yields exactly that command and route with no core edit. | inv15 | OWNS: _apc64_host/application/__init__.py, _apc64_host/application/ports.py, _apc64_host/application/modules.py; BINDS: s77:to; AFTER: T4 |
| T11 | Clock adapter (infrastructure). | Given a running asyncio loop, When call_later(0.25, cb) is scheduled and one handle is cancelled, Then the live callback fires after the delay, the cancelled one never fires, and monotonic() increases. | inv18 | OWNS: _apc64_host/infrastructure/__init__.py, _apc64_host/infrastructure/clock.py; BINDS: s41:to, s52:to, s62:to, s73:to, s87:from; AFTER: T10 |
| T12 | ALSA rawmidi adapter (infrastructure): exclusive open by role, reader thread, write, errno mapping. | Given a ctypes libasound double and recorded fixture bytes, When subdevices 0 (read/write), 1 and 3 (input-only) are opened and read, Then the open strings are 'hw:4,0,<s>', chunks reach each role's listener in order, EBUSY maps to PortBusy, EACCES to PortNoPermission and EIO to a single on_gone; while held, a second open of the same subdevice fails. | inv13, inv14, inv11 | OWNS: _apc64_host/infrastructure/alsa_rawmidi.py; BINDS: s3:to, s34:to, s46:to, s54:to, s80:from; DISCHARGES: A14; AFTER: T10, T6 |
| T13 | Unit locator (infrastructure): `amidi -l` by name and /dev/snd hotplug watch. | Given recorded `amidi -l` output with the APC64 on card 4, then on card 5, and inotify create/delete events, When find() runs and events arrive, Then UnitPresence names DAW hw:4,0,0 / Notes hw:4,0,1 / Custom hw:4,0,3, then the card-5 addresses, with one notification per change, and None without APC64 lines. | inv17, inv16 | OWNS: _apc64_host/infrastructure/unit_locator.py; BINDS: s5:to, s32:to, s81:from; AFTER: T10 |
| T14 | ALSA sequencer adapter (infrastructure): targets, feedback inputs, port catalog, holder lookup via subscriptions and System Announce. | Given an alsa-midi double with ports 'MPC Live III MIDI 1', 'Bitwig Studio In' and client 'APC64' subscribed by 'Chrome', When ports are listed, sends made, feedback listened and announce events arrive, Then APC64 ports are never listed or connected, a send to a vanished port is MISSING, holder_of(DAW) is 'Chrome' then None after unsubscribe, and 'mpc' reconnects by name when its port appears. | inv13, inv16, inv11, pi6 | OWNS: _apc64_host/infrastructure/alsa_seq.py; BINDS: s4:to, s25:to, s33:to, s45:to, s65:to, s82:from, s89:to; DISCHARGES: A86; AFTER: T10, T2 |
| T15 | Layout file source (infrastructure): list, read with hash, atomic write, inotify watch with poll fallback. | Given a temp layouts dir, When jam.yaml is written, a .tmp is renamed onto it, notes.txt is written and jam.yaml is deleted, Then CHANGED, CHANGED, nothing, DELETED are emitted for LayoutId 'jam', and write() goes through temp + rename. | inv18, inv19 | OWNS: _apc64_host/infrastructure/layout_files.py; BINDS: s6:to, s57:to, s64:to, s83:from; AFTER: T10, T3 |
| T16 | Version and state stores (infrastructure). | Given a temp state dir, When three versions of 'jam' are saved, the holding marker is set and cleared, and a calibration and nav are stored, Then versions list newest first and read back exactly, outside the repository; the marker reports present/absent; calibration and nav round-trip. | inv20, inv14 | OWNS: _apc64_host/infrastructure/version_store.py, _apc64_host/infrastructure/state_store.py; BINDS: s36:to, s53:to, s59:to, s67:to, s84:from, s85:from; DISCHARGES: A55; AFTER: T10, T3 |
| T17 | Desktop notifier (infrastructure). | Given a subprocess double for notify-send, When ask('Take control of APC64?') runs and the double prints 'take', exits silently, or prints after withdraw(), Then the ask resolves TAKE once, DISMISSED, and the late click is ignored; the argv carries -A take=Take -w. | inv12 | OWNS: _apc64_host/infrastructure/notifier.py; BINDS: s35:to, s86:from, s91:to; AFTER: T10 |
| T18 | Simulated APC64 adapter (infrastructure): a UnitPort/UnitLocator fake speaking the fixture formats, with scriptable faults. | Given the simulator scripted with busy, no-permission and unplug faults, When it is opened, sent an identity request and fed presses, Then it answers the fixture identity reply, emits the scripted presses and view reports, records every written frame, and raises the scripted fault. | inv10 | OWNS: _apc64_host/infrastructure/simulated_apc64.py; AFTER: T10, T6 |
| T19 | Outbound gate (application): the only DAW writer, policy check, write queue, silent sink when not held, device log. | Given CONTRACT1_POLICY and an attached connection double, When an LED frame, an OLED frame and a 0x14 project write are sent, and later frames are sent while detached, Then the first two are written in order and logged SENT, the 0x14 is never written and is logged REFUSED as a hazard, and detached frames are DROPPED silently. | inv15, inv11, pi3 | OWNS: _apc64_host/application/outbound_gate.py; BINDS: s24:to, s37:to, s44:to, s54:from, s55:from, s56:from; DISCHARGES: A31, A32; AFTER: T10, T6, T4 |
| T20 | Activity log and play stream (application). | Given 500 appended entries, a Note-view note with 200 aftertouch values, two watchers and one stalled watcher, When entries and events are published, Then recent() returns the newest 200 with aftertouch folded into the note's entry, both watchers get identical ordered events from their join time, and the stalled one is closed with 'too slow' after 5 s without blocking publish. | inv7, pi10 | OWNS: _apc64_host/application/activity.py, _apc64_host/application/play_stream.py; BINDS: s23:to, s27:to, s47:to, s28:to, s48:to, s73:from; DISCHARGES: A124, A125, A126, A127; AFTER: T10, T4, T11 |
| T21 | Layout library (application). | Given compiled 'Jam' from jam.yaml, then jam2.yaml also named 'Jam', When registered, Then the second registration is refused DUPLICATE_NAME naming jam.yaml, jam.yaml stays loaded, and the catalog lists layouts alphabetically. | inv4, pi4 | OWNS: _apc64_host/application/library.py; BINDS: s18:to, s49:to, s60:to, s71:to; DISCHARGES: A42; AFTER: T10, T3 |
| T22 | Tweak service (application). | Given jam.yaml with hash H, When a tweak with base H sets r1c1 channel 17, and another with a stale base sets a colour, Then the first is refused INVALID ('channel must be 1–16') and the second STALE ('layout changed, reload'), and the file is unchanged in both. | inv21 | OWNS: _apc64_host/application/tweaks.py; BINDS: s19:to, s66:to, s63:from, s64:from; DISCHARGES: A136, A139; AFTER: T10, T8, T15 |
| T23 | Learn service (application): touch-select interception and MIDI-learn. | Given learn TOUCH, then MIDI on input 'mpc' with pad r2c1 selected, When track 3 is pressed and then CC 74 value 10 ch 1 arrives, and in a third case learn is left with nothing received, Then track 3 is selected with no action sent, pad r2c1 is saved as 'CC74 → mpc ch 1' via one tweak, and nothing changes in the third case. | pi12 | OWNS: _apc64_host/application/learn.py; BINDS: s20:to, s50:to, s90:to, s65:from, s66:from; DISCHARGES: A132, A133, A134; AFTER: T10, T22, T14 |
| T24 | Calibration service (application). | Given calibration started in Note view, When bottom-left and top-right pads send notes 36 and 99, and later note 53 velocity 56 is looked up, Then a Calibration is stored and position_of(53) returns a pad labelled 'calibrated <time> (assumed)'; without one, current() is None ('pad position unknown'). | inv9 | OWNS: _apc64_host/application/calibration.py; BINDS: s21:to, s51:to, s72:to, s67:from; DISCHARGES: A121, A122, A123; AFTER: T10, T3, T16 |
| T25 | Host engine (application): ordered input queue, domain calls, effect execution, learn/calibration interception, nav persistence. | Given doubles for gate, targets, activity, stream, library, learn, calibration, clock and store, When replica press of r1c1 with no unit held, the 'mpc' port missing, empty layouts on hold, and concurrent page selections (2 then 4) are handled, Then note 36 is sent with the LED sink dropped silently, activity records 'not sent: mpc missing', the unit shows 'No layout', and the last selection (page 4) wins in the snapshot. | inv10, inv22, pi6, pi10 | OWNS: _apc64_host/application/engine.py; BINDS: s16:to, s38:to, s61:to, s69:to, s42:from, s43:from, s44:from, s45:from, s46:from, s47:from, s48:from, s49:from, s50:from, s51:from, s52:from, s53:from; DISCHARGES: A16, A37, A70, A83, A120, A142; AFTER: T4, T5, T6, T19, T20, T21, T23, T24, T11, T16 |
| T26 | Layout pipeline (application): settle, compile with port catalog, dedupe, version, register, swap; validate text, versions, restore. | Given doubles for source, notation, versions, library, engine and clock, When jam.yaml changes (valid; half-written then complete; invalid then fixed; identical; deleted; restored to 10:42), Then each case swaps at most once within the settle window, invalid content never swaps or versions, identical content does nothing, deletion keeps the live layout, and restore writes the version back. | inv18, inv19, inv20 | OWNS: _apc64_host/application/layout_pipeline.py; BINDS: s17:to, s57:from, s58:from, s59:from, s60:from, s61:from, s62:from, s89:from; DISCHARGES: A44, A50, A51, A52, A53, A54, A56; AFTER: T8, T21, T25, T15, T16, T14, T11 |
| T27 | Device session (application): consent, holder watch, exclusive open, identity, handshake, marker, supervision, single release. | Given doubles for locator, holder lookup, unit port, notifier, store, gate, engine and clock, When the scenarios of the consent and release rows run (plug in, yes/no/auto, Busy by Bitwig/Chrome, no permission, Notes busy, silent device, firmware 1.2.2.0, stale marker, agent take, release/stop/unplug/fault, release when not held), Then each ends in the row's UnitStatus, and every release sends clear → DAW off → close exactly once. | inv12, inv13, inv14, inv16, inv17 | OWNS: _apc64_host/application/session.py; BINDS: s15:to, s70:to, s76:to, s32:from, s33:from, s34:from, s35:from, s36:from, s37:from, s38:from, s39:from, s40:from, s41:from; DISCHARGES: A1, A2, A3, A4, A5, A6, A7, A8, A9, A10, A12, A13, A15, A17, A18, A19, A20, A21, A22, A23, A24, A25, A26, A27, A28, A29, A30, A114; AFTER: T4, T5, T6, T10, T19, T25, T11, T16 |
| T28 | State view (application): snapshot, card, overview, surface catalog and change subscriptions. | Given doubles for engine, session, library, calibration and learn, When snapshot, card(pad r1c1) and subscribe are called and the engine changes, Then the views carry nav, labels, LEDs, unit status, issues, learn selection and calibration labels, and subscribers get a snapshot followed by diffs. | inv1, inv2, pi11 | OWNS: _apc64_host/application/state_view.py; BINDS: s22:to, s26:to, s68:from, s69:from, s70:from, s71:from, s72:from, s90:from; AFTER: T4, T25, T27, T21, T24, T23, T5 |
| T29 | Network guard (presentation): allowed networks and same-site Origin/Host middleware. | Given requests from 192.168.1.23, fd00::23, ::ffff:192.168.1.40, 203.0.113.5, and one from 192.168.1.23 with Origin https://example.com, When they pass the guard, Then the first three reach the inner app unchanged and the last two get 403 with their problem text. | inv23 | OWNS: _apc64_host/presentation/network_guard.py; BINDS: s1:to, s11:from; DISCHARGES: A143, A144, A145, A146, A147; AFTER: T3 |
| T30 | View model (presentation): JSON shaping of every view and stream message. | Given a StateView, CardView, ValidationReport, ActivityEntry, PlayEvent and DeviceLogEntry, When shaped, Then each yields a deterministic JSON-safe dict matching docs/api.md. | inv22 | OWNS: _apc64_host/presentation/view_model.py; BINDS: s13:to, s14:to; AFTER: T4, T28, T20, T26, T19 |
| T31 | WebSocket hub (presentation): /ws state + activity, /ws/play. | Given doubles for state view, activity and play stream, When a page connects, drops and reconnects, a second page switches page, and an agent watches /ws/play while lagging, Then each (re)connect receives a snapshot first, both pages receive the same diff, and the agent receives events then {type:'closed', reason:'too slow'}. | inv7, inv22 | OWNS: _apc64_host/presentation/ws_hub.py; BINDS: s12:to, s30:to, s31:to, s14:from, s26:from, s27:from, s28:from; DISCHARGES: A130, A131; AFTER: T30, T28, T20 |
| T32 | HTTP API (presentation): build_app with every route, static serving, WebSocket delegation, answer mapping. | Given service doubles, When the CLI-shaped sequence (ports, layouts, load 'Tonnetz C', page 3, bank 2, state) runs and then page 0 is requested, Then each call reaches its service and returns 200 with the state showing 'Tonnetz C', page 3, bank 2, and page 0 returns 400 {problem:'page must be 1–8'}. | inv22, pi13 | OWNS: _apc64_host/presentation/__init__.py, _apc64_host/presentation/api.py; BINDS: s9:to, s10:to, s11:to, s12:from, s13:from, s15:from, s16:from, s17:from, s18:from, s19:from, s20:from, s21:from, s22:from, s23:from, s24:from, s25:from; DISCHARGES: A140, A141; AFTER: T31, T30, T29, T27, T25, T26, T21, T22, T23, T24, T28, T20, T19, T14 |
| T33 | apc64 CLI (edge): subcommands over the API, offline validation, watch; composes its HTTP/WebSocket client and the notation compiler. | Given /tmp/draft.yaml and no running service, When `apc64 validate /tmp/draft.yaml` and `apc64 load jam` run, Then validate prints the structure result with 'ports not checked' and exit 0/1, and load prints 'service not running on port 5058' and exits 2. | pi13, inv22 | OWNS: _apc64_host/presentation/cli.py; BINDS: s2:to, s10:from, s29:from, s31:from; DISCHARGES: A45, A46; AFTER: T32, T31, T8; WIRES: s10, s29, s31 |
| T34 | Static page base (presentation): page shell, styles, API wrapper, pure state reducer, node module manifest. | Given a fake fetch and fake socket, When api.js calls each route and state.js receives snapshot, diffs, a drop and a new snapshot, Then requests match docs/api.md, 400/409 map to UI problems, and the page model resets to the new snapshot. | pi11, inv22 | OWNS: _apc64_host/presentation/static/package.json, _apc64_host/presentation/static/index.html, _apc64_host/presentation/static/style.css, _apc64_host/presentation/static/api.js, _apc64_host/presentation/static/state.js; AFTER: T32 |
| T35 | Static replica views (presentation): replica, nav bar, detail card, overview, activity list. | Given a page model and the surface catalog, When rendered, Then every control shows its current label or is visibly empty, the nav bar shows layout/page/bank/Shift, holding page Shift swaps labels, the card shows both layers and elsewhere, and the activity list shows the latest 200 entries. | inv1, inv2, pi11 | OWNS: _apc64_host/presentation/static/replica.js, _apc64_host/presentation/static/nav.js, _apc64_host/presentation/static/card.js, _apc64_host/presentation/static/overview.js, _apc64_host/presentation/static/activity.js; AFTER: T34 |
| T36 | Static page interactions and bootstrap (presentation): banners, learn/calibration, tweak form, app bootstrap; composes the page's API and socket clients. | Given a recording API double, When the user's gestures run (Yes/No/Release, press/release r1c1, drag strip, page/bank clicks, learn toggles, tweak save), Then each issues exactly its API call and shows the answer, and no static module calls requestMIDIAccess. | pi11, pi12, inv12 | OWNS: _apc64_host/presentation/static/banner.js, _apc64_host/presentation/static/learn.js, _apc64_host/presentation/static/tweak.js, _apc64_host/presentation/static/app.js; BINDS: s8:to, s9:from, s30:from; DISCHARGES: A11; AFTER: T35, T34, T32, T31; WIRES: s9, s30 |
| T37 | Composition root (wiring): build every adapter and service, register modules, build the app behind the guard, run uvicorn dual-stack with lifespan start/release. | Given the composed object graph with the simulated APC64 in place of rawmidi, When lifespan starts and stops, Then a single composition test reaches each wired seam's supplier once through the real graph (one named case per seam), session.start() runs once at start and release('stop') once at shutdown, and uvicorn is called with host '::' and lifespan 'on'. | inv14, inv23, pi2 | OWNS: _apc64_host/__main__.py; BINDS: s7:to, s76:from, s77:from, s78:from, s79:from; AFTER: T9, T10, T11, T12, T13, T14, T15, T16, T17, T18, T19, T20, T21, T22, T23, T24, T25, T26, T27, T28, T29, T30, T31, T32; WIRES: s11, s12, s13, s14, s15, s16, s17, s18, s19, s20, s21, s22, s23, s24, s25, s26, s27, s28, s32, s33, s34, s35, s36, s37, s38, s39, s40, s41, s42, s43, s44, s45, s46, s47, s48, s49, s50, s51, s52, s53, s54, s55, s56, s57, s58, s59, s60, s61, s62, s63, s64, s65, s66, s67, s68, s69, s70, s71, s72, s73, s74, s75, s76, s77, s78, s89, s90 |
| T38 | Operator docs and deployment (document): API/CLI reference, README, systemd user unit, desktop launcher. | Given the built service, When docs/api.md examples are compared with the routes and the unit file is checked, Then every route and CLI command is documented with a working example, and the unit runs `python -m _apc64_host` from the repo venv with Restart=on-failure and a TimeoutStopSec covering release. | pi13, inv22 | OWNS: docs/api.md, README.md, deploy/apc64-host.service, deploy/apc64-host.desktop; AFTER: T37, T33 |

## 7 · Final Design Guide
Role: binding — the drawings. `layout` uses the artifact-line form of §0 form 4 and states the size bound.
- **layout:**
  - `pyproject.toml` — Package manifest: name apc64-host, requires-python >=3.14, dependencies fastapi, uvicorn, websockets, ruamel.yaml, alsa-midi; dev extras pytest, httpx; console script apc64 = _apc64_host.presentation.cli:main; pytest testpaths _apc64_host, marker live, addopts -m 'not live' — layer: document
  - `.gitignore` — Adds config.local, .venv/, *.egg-info/ and __pycache__/ to the existing ignores. Version copies live outside the repo — layer: document
  - `config.local.example` — Documented KEY=VALUE defaults: APC64_HTTP_PORT=5058, APC64_LAYOUTS_DIR=layouts, APC64_STATE_DIR=~/.local/state/apc64-host, APC64_ALLOWED_NETWORKS, APC64_AUTO_ACCEPT=0, APC64_PORT_STEM=APC64 — layer: document
  - `README.md` — What the host does, install (venv, user unit), Take/Release/Busy behaviour, the Bitwig and Chrome hand-over, gates (pytest, node --test, APC64_LIVE=1 pytest -m live) — layer: document
  - `deploy/apc64-host.service` — systemd user unit: ExecStart=<repo>/.venv/bin/python -m _apc64_host, WorkingDirectory=<repo>, Restart=on-failure, TimeoutStopSec covering release, WantedBy=default.target — layer: document
  - `deploy/apc64-host.desktop` — Launcher that opens http://localhost:5058 — layer: document
  - `docs/layout-guide.md` — Authoring guide for agents: control names diagram (r1 = bottom row), devices, ranges, layers, pages/banks, toggles, feedback, routing rules, note names (C3 = 60), worked examples that validate as shipped — layer: document
  - `docs/layout.schema.json` — Machine-readable layout schema generated by _apc64_host/notation/schema.py from the shared grammar — layer: document
  - `docs/api.md` — HTTP/WebSocket API and apc64 CLI reference with request/response examples for every route — layer: document
  - `layouts/jam.yaml` — Shipped example layout 'Jam': one device, page 'Drums', bank 'Mix', Notes-port routing — layer: document
  - `_apc64_host/__init__.py` — Package marker and version — layer: wiring
  - `_apc64_host/__main__.py` — Composition root: loads Config, builds adapters, application services and HostModules (none in contract 1), builds the FastAPI app, runs uvicorn on [::]:<port> with lifespan; on startup calls DeviceSession.start(), on shutdown DeviceSession.release('stop') — layer: wiring
  - `_apc64_host/config.py` — Config value from config.local KEY=VALUE overridden by environment; validates each key, failing with the key name — layer: wiring
  - `_apc64_host/domain/__init__.py` — Domain package marker — layer: domain
  - `_apc64_host/domain/controls.py` — ControlId sum type, ControlRole, SURFACE (the single catalog of every physical control: id, role, display name including the strip-mode panel names, panel geometry), control-name parse/format ('pad r1c1', 'pads r1c1-r2c8') — layer: domain
  - `_apc64_host/domain/midi.py` — Channel, Note, Velocity, Value7, Value14, CcNumber, Program, Pressure, the MidiMessage sum type, and note-name parse/format with C3 = 60 — layer: domain
  - `_apc64_host/domain/palette.py` — The one colour table: name ↔ palette index ↔ approximate RGB, marked as an approximation — layer: domain
  - `_apc64_host/domain/layout.py` — The Layout aggregate (LayoutId, LayoutName, DeviceDecl, Page with per-Layer bindings plus a base-only encoder binding, Bank with per-Layer StripBindings, RoutingRule per UnitPortRole), Binding, Action, ValueSource, FeedbackRule, FeedbackIndex; constructor invariants — layer: domain
  - `_apc64_host/domain/resolver.py` — resolve(layout, nav) → SurfaceMeaning; elsewhere(layout, control); overview(layout) — the single read model for labels, preview, card, overview, nav and OLED — layer: domain
  - `_apc64_host/domain/effects.py` — SurfaceInput, FeedbackMessage, PlayedMidi, Tick and the Effect sum type (Send, Led, StripBar, Oled, Activity, Play, ScheduleAfter, RequestLayout), ActivityEntry, PlayEvent — layer: domain
  - `_apc64_host/domain/surface_parts.py` — Navigator, ToggleBook (keyed by LayoutId, page, layer, control), FeedbackBook, PressLedger, EncoderDial, BrowseCursor, StripPositions (keyed by LayoutId, bank, strip) — layer: domain
  - `_apc64_host/domain/surface.py` — The HostSurface aggregate root: handle(input) → [Effect] composed from surface_parts. Navigation, momentary/toggle, Shift layer, browse/load, feedback, unbound handling — layer: domain
  - `_apc64_host/domain/router.py` — ExpressiveRouter: held-note table, velocity untouched, aftertouch PASS/CHANNEL_PRESSURE/DROP, transpose, remap, out-of-range drop — layer: domain
  - `_apc64_host/domain/leds.py` — LedBehaviour, LedState, StripBarStyle, LedFrame.for_state (the full desired surface), idle/on brightness rule (25% / full) — layer: domain
  - `_apc64_host/domain/oled.py` — OledText (two ASCII rows, '?' for others, 14-character cut, trailing spaces trimmed), idle and transient texts — layer: domain
  - `_apc64_host/domain/unit_status.py` — The UnitStatus sum type and pure transitions on presence, consent, decline, open failure, release and stale marker — layer: domain
  - `_apc64_host/domain/outbound.py` — SysexCommand enum, OutboundPolicy, CONTRACT1_POLICY (no 0x13/0x14/0x17/0x18) — layer: domain
  - `_apc64_host/domain/calibration.py` — Calibration (taken at, Note → PadPos) and position_of(note) → PadPosition flagged assumed — layer: domain
  - `_apc64_host/domain/issues.py` — SourceRef, Severity, LayoutIssue, DomainInvariantError (field + problem + fix) — layer: domain
  - `_apc64_host/domain/network.py` — AllowedNetworks and ClientAddress membership (loopback, RFC 1918, IPv6 loopback/link-local/ULA, IPv4-mapped unwrapped) — layer: domain
  - `_apc64_host/protocol/__init__.py` — Protocol package marker — layer: domain
  - `_apc64_host/protocol/sysex.py` — Akai frame build/parse, identity request/reply → Identity, handshake, DAW on/off, mode report → UnitView, OLED frames, command_of(frame) — layer: domain
  - `_apc64_host/protocol/surface_map.py` — The one bidirectional ControlId ↔ wire table: decode DAW bytes → SurfaceInput (encoder multi-step rule, pad 0 = r1c1); encode LedState/StripBar → bytes — layer: domain
  - `_apc64_host/protocol/midi_codec.py` — MidiMessage ↔ bytes with running status and velocity-0 note-on as note-off — layer: domain
  - `_apc64_host/protocol/stream.py` — Byte-stream splitter for chunked rawmidi reads (SysEx and channel messages) — layer: domain
  - `_apc64_host/notation/__init__.py` — Notation package marker — layer: domain
  - `_apc64_host/notation/grammar.py` — The shared grammar tables (keys, control-name forms, action forms, value forms) used by compiler, splice and schema — layer: domain
  - `_apc64_host/notation/parser.py` — YAML text → syntax tree with a SourceRef on every node (ruamel.yaml round-trip loader, parse only) — layer: domain
  - `_apc64_host/notation/compiler.py` — Syntax tree (+ optional port catalog snapshot) → Layout or [LayoutIssue]: range expansion, precedence rule, device and default-channel resolution, note names, all issues in line order with fixes — layer: domain
  - `_apc64_host/notation/splice.py` — plan_splice(text, tweak) → new text: insert, replace or remove one single-control entry line in the parser's own notation; never re-dumps — layer: domain
  - `_apc64_host/notation/schema.py` — Generates docs/layout.schema.json from grammar.py and SURFACE — layer: domain
  - `_apc64_host/application/__init__.py` — Application package marker — layer: application
  - `_apc64_host/application/ports.py` — Protocols UnitLocator, HolderLookup, UnitPort/UnitConnection, TargetPorts, FeedbackInputs, PortCatalog, LayoutSource, VersionStore, StateStore, ConsentPrompt, Clock, HostModule; errors PortBusy, PortNoPermission, PortGone — layer: application
  - `_apc64_host/application/session.py` — DeviceSession: presence and holder observation, consent (banner/notification/agent/auto-accept), exclusive open by role, identity check, handshake, holding marker, engine supervision, the single release() — layer: application
  - `_apc64_host/application/outbound_gate.py` — OutboundGate: the only writer to the DAW connection, policy check, single write queue, silent sink when not held, DeviceLog ring of sent/refused frames — layer: application
  - `_apc64_host/application/engine.py` — HostEngine: the thread-safe input queue, HostSurface/ExpressiveRouter calls, effect execution (targets, gate, activity, play stream, timers, layout requests), learn/calibration interception, nav persistence — layer: application
  - `_apc64_host/application/layout_pipeline.py` — LayoutPipeline: change → settle ≤ 250 ms → read → compile (with port catalog) → hash dedupe → version → register → swap; validate_text, versions, restore — layer: application
  - `_apc64_host/application/library.py` — LayoutLibrary: compiled layouts, summaries, issues and warnings per LayoutId, duplicate-name refusal, alphabetical LayoutCatalog — layer: application
  - `_apc64_host/application/tweaks.py` — TweakService: hash check, splice, full compile, write — layer: application
  - `_apc64_host/application/learn.py` — LearnService: touch-select interception and MIDI-learn capture on a chosen input port → assignment tweak — layer: application
  - `_apc64_host/application/calibration.py` — CalibrationService: captures two Note-view notes, builds and stores the Calibration, serves current() — layer: application
  - `_apc64_host/application/play_stream.py` — PlayStream: ordered fan-out from now, per-subscriber bounded queue, close after 5 s lag — layer: application
  - `_apc64_host/application/activity.py` — ActivityLog: ring of 200 entries, newest first, aftertouch folded into its note's entry, subscriptions — layer: application
  - `_apc64_host/application/state_view.py` — StateView: snapshot, card, overview and surface-catalog views, with change subscriptions built from resolver, engine, session, library, learn and calibration — layer: application
  - `_apc64_host/application/modules.py` — HostModule registry: union of outbound policy additions and module routers (none registered in contract 1) — layer: application
  - `_apc64_host/infrastructure/__init__.py` — Infrastructure package marker — layer: infrastructure
  - `_apc64_host/infrastructure/alsa_rawmidi.py` — UnitPort via ctypes libasound: exclusive non-blocking open of hw:<card>,0,<sub> by role (Notes/Custom input-only), 1 MiB buffer reader thread, errno → PortBusy/PortNoPermission/PortGone — layer: infrastructure
  - `_apc64_host/infrastructure/unit_locator.py` — UnitLocator: `amidi -l` parse by port-name stem, plus inotify on /dev/snd for hotplug with a 1 s rescan fallback — layer: infrastructure
  - `_apc64_host/infrastructure/alsa_seq.py` — alsa-midi client: TargetPorts, FeedbackInputs, PortCatalog and HolderLookup (subscriber query plus System Announce); never connects to the APC64 client — layer: infrastructure
  - `_apc64_host/infrastructure/layout_files.py` — LayoutSource over the layouts dir: list, read with ContentHash, atomic write (temp + rename), inotify watch with a 2 s stat-poll fallback — layer: infrastructure
  - `_apc64_host/infrastructure/version_store.py` — VersionStore under <state>/versions/<layout>/<timestamp>-<hash>.yaml — layer: infrastructure
  - `_apc64_host/infrastructure/state_store.py` — StateStore: holding marker, calibration.json, nav.json (last NavState and strip positions) — layer: infrastructure
  - `_apc64_host/infrastructure/notifier.py` — ConsentPrompt via `notify-send -A take=Take -w` subprocess; resolves the pending ask on the user's click; withdraw by terminating it — layer: infrastructure
  - `_apc64_host/infrastructure/clock.py` — Clock over the asyncio loop and time.monotonic — layer: infrastructure
  - `_apc64_host/infrastructure/simulated_apc64.py` — A UnitPort/UnitLocator fake speaking the fixture formats (identity, presses, strips, view reports, Notes/Custom streams), recording written frames, with scriptable busy/permission/unplug faults — layer: infrastructure
  - `_apc64_host/presentation/__init__.py` — Presentation package marker — layer: presentation
  - `_apc64_host/presentation/network_guard.py` — ASGI middleware: client in AllowedNetworks and Origin/Host same-site, else 403 with a problem — layer: presentation
  - `_apc64_host/presentation/api.py` — build_app(services): every route of docs/api.md, static file serving, WebSocket routes delegated to ws_hub; maps service answers to 200/400/409 — layer: presentation
  - `_apc64_host/presentation/ws_hub.py` — /ws (snapshot on connect, state diffs, activity) and /ws/play (play events, 'closed: too slow') — layer: presentation
  - `_apc64_host/presentation/view_model.py` — Deterministic JSON shaping of StateView, CardView, OverviewView, SurfaceCatalogView, issues, activity and play events — layer: presentation
  - `_apc64_host/presentation/cli.py` — The apc64 command: take, release, ports, layouts, validate PATH (via the API when the service is up, else offline structure-only), load, page, bank, state, watch, versions, restore — layer: edge
  - `_apc64_host/presentation/static/package.json` — {"type": "module"} so node --test loads the ES modules — layer: document
  - `_apc64_host/presentation/static/index.html` — The single page shell: banner, nav bar, replica, card, overview, activity, errors — layer: presentation
  - `_apc64_host/presentation/static/style.css` — Page styles, including the 'empty' and 'approximate colour' looks — layer: presentation
  - `_apc64_host/presentation/static/api.js` — fetch wrapper for every API route, mapping 400/409 bodies to UI messages — layer: presentation
  - `_apc64_host/presentation/static/state.js` — Pure reducer: snapshot + diffs + activity → page model; reconnect resets to snapshot — layer: presentation
  - `_apc64_host/presentation/static/app.js` — Bootstrap: loads /api/surface, opens /ws, wires gesture handlers to api.js — layer: presentation
  - `_apc64_host/presentation/static/replica.js` — Renders the whole unit from the surface catalog and page model: labels, empty controls, LEDs, strips, OLED, played notes row; gestures → press/release/move — layer: presentation
  - `_apc64_host/presentation/static/nav.js` — Nav bar for layout, pages 1–8, banks 1–6 and Shift (hold for preview) — layer: presentation
  - `_apc64_host/presentation/static/card.js` — Detail card: both layers, mode, toggle state, feedback, port status, elsewhere list, reachability — layer: presentation
  - `_apc64_host/presentation/static/overview.js` — Overview of every page (mini grid) and bank, clickable — layer: presentation
  - `_apc64_host/presentation/static/activity.js` — Live activity list (latest 200) — layer: presentation
  - `_apc64_host/presentation/static/banner.js` — Consent/Busy/No permission/firmware/maybe-stuck banners and validation errors — layer: presentation
  - `_apc64_host/presentation/static/learn.js` — Learn toggles (touch, MIDI-learn with port choice) and calibration steps — layer: presentation
  - `_apc64_host/presentation/static/tweak.js` — Single-control tweak form (assignment, label, colour, momentary/toggle) carrying base_hash — layer: presentation
- **value objects:**
  ControlId — sum type: PadPos(row 1–8, col 1–8), TrackButton(1–8), TrackControl(1–8), SceneButton(1–8), StripModeButton(1–6), Strip(1–8), StripTouch(1–8), FunctionButton(Tempo, Clear, Duplicate, Quantize, Fixed, Undo), Transport(Play, Rec, Stop), Nav(Up, Down, Left, Right), ModeButton(RecArm, Mute, Solo, Stop), Encoder, EncoderPress, Shift
  ControlRole — BINDABLE, NAVIGATION, MODIFIER, DEVICE_LOCAL; SurfaceEntry(id, role, display name, geometry)
  Layer — BASE, SHIFT; PageNo (1–8); BankNo (1–6)
  LayoutId — file stem matching [A-Za-z0-9_-]+; LayoutName (display); LayoutCatalog (ordered ids + names)
  NavState(layout, page, bank, shift held)
  Channel (1–16), Note (0–127), Velocity, Value7, Value14 (0–16383), CcNumber, Program, Pressure
  MidiMessage — NoteOn, NoteOff, ControlChange, ControlChange14, ProgramChange, PitchBend, PolyAftertouch, ChannelPressure
  DeviceName, PortName, PortPattern (exact or unique part), DeviceDecl(name, pattern, default Channel?)
  ValueSource — Fixed(Value7), PressVelocity, StripPosition, EncoderValue, ToggleState(ToggleValues)
  Action(device, message kind with ValueSource); Binding(actions, BindingMode, label?, colour?, feedback?, fixed velocity?); BindingMode — MOMENTARY, TOGGLE; ToggleValues(on = 127, off = 0)
  FeedbackRule(device, note-or-CC on Channel, colours per value?); FeedbackIndex (incoming message → bound controls)
  StripBinding(position Action, touch Action?, colour, StripBarStyle, feedback?)
  RoutingRule(UnitPortRole, target DeviceName, Channel, AftertouchPolicy, Transpose −127…127, NoteRemap); AftertouchPolicy — PASS, CHANNEL_PRESSURE, DROP
  Colour (palette index + optional name), PaletteEntry(name, index, approx RGB); LedBehaviour; LedState(colour, behaviour); StripBarStyle — BAR, BIPOLAR; LedFrame
  OledText (two rows, ASCII, ≤ 14 chars)
  UnitPortRole — DAW, NOTES, CUSTOM; UnitView — SESSION, OVERVIEW, NOTE, CHORD, DRUM, STEP, PROJECT, CUSTOM
  Identity(product, FirmwareVersion, serial); UnitPresence(subdevice address per role)
  UnitStatus — Absent, Asking, Busy(Holder | unknown), NoPermission, Held(by ConsentSource, firmware warning?), Unplugged, MaybeStuck; ConsentSource — BANNER, NOTIFICATION, LAN_BROWSER, AGENT, AUTO_ACCEPT; Holder(name)
  SysexCommand; OutboundPolicy (frozenset of SysexCommand); DeviceLogEntry(at, frame, SENT | REFUSED)
  SurfaceInput — Press(ControlId, Velocity), Release(ControlId), StripMove(Strip, Value14), EncoderTurn(steps), ViewReport(UnitView); PlayedMidi(UnitPortRole, MidiMessage); FeedbackMessage(PortName, MidiMessage); Tick(kind)
  Effect — Send(PortName, MidiMessage), Led(ControlId, LedState), StripBar(Strip, Value14, style), Oled(OledText), Activity(ActivityEntry), Play(PlayEvent), ScheduleAfter(duration, Tick), RequestLayout(LayoutId)
  PressToken(ControlId, Binding that received the press)
  SourceRef(file, line); Severity — ERROR, WARNING; LayoutIssue(severity, source, control?, problem, fix)
  ContentHash; VersionId(timestamp, hash)
  Calibration(at, Note → PadPos); PadPosition(PadPos, assumed = true)
  ActivityEntry(at, control or note, message?, port?, ActivityResult, reason?); ActivityResult — SENT, NOT_SENT, REFUSED, UNBOUND, DROPPED
  PlayEvent(at, source, view, control or note, value, velocity?, aftertouch?, sent?, reason?)
  TweakRequest(layout, page-or-bank, layer, control, field, value, base ContentHash); LearnMode — TOUCH, MIDI(PortName), OFF
  AllowedNetworks; ClientAddress
- **ports:**
  UnitLocator.find() -> UnitPresence | None; subscribe(callback(UnitPresence | None))
  HolderLookup.holder_of(UnitPortRole) -> Holder | None; subscribe(callback(role, Holder | None))
  UnitPort.open(role, address) -> UnitConnection, raising PortBusy(holder?), PortNoPermission or PortGone. UnitConnection: listen(on_bytes, on_gone), write(bytes) (DAW only; Notes/Custom are input-only), close()
  TargetPorts.send(PortName, MidiMessage) -> SENT | MISSING | FAILED; subscribe_presence(callback(PortName, present))
  FeedbackInputs.listen(PortName, callback(MidiMessage)) -> Subscription
  PortCatalog.list() -> [PortInfo(name, direction, present)], never including the APC64
  LayoutSource.list() -> [LayoutId]; read(LayoutId) -> (text, ContentHash) | MISSING; write(LayoutId, text) atomically; changes(callback(LayoutId, CHANGED | DELETED))
  VersionStore.save(LayoutId, text, ContentHash) -> VersionId; list(LayoutId) -> [VersionId]; read(VersionId) -> text
  StateStore: marker_set/marker_clear/marker_present; calibration_get/put; nav_get/put(NavState, strip positions)
  ConsentPrompt.ask(text) -> awaitable TAKE | DISMISSED; withdraw()
  Clock.monotonic(); call_later(seconds, callback) -> cancel handle
  HostModule: name; outbound_additions() -> frozenset[SysexCommand]; router() -> API routes; panel() -> static path
- **dependency direction:** Dependencies point inward only: edge (cli.py) and presentation → application → domain. protocol/ and notation/ are pure packages that depend on domain/ only (notation also imports ruamel.yaml, for parsing). infrastructure/ implements application/ports.py and uses domain/protocol types. domain/ imports only the standard library (dataclasses, enum, typing, ipaddress, datetime): no I/O, threads, asyncio, ALSA, YAML or web. application/ never imports infrastructure/ or presentation/; adapters arrive by constructor injection from _apc64_host/__main__.py, the only composition root, with no module-level singletons. Enforcement: a hermetic test walks every module's imports and fails on an outward edge, fails if any static JS calls requestMIDIAccess, and fails if anything other than application/outbound_gate.py calls UnitConnection.write.

Artifact lines (one per module, inside `layout`): `` - `path` — responsibility — layer: <layer> ``.
Size bound: `5` artifacts per unit.

### 7.1 Design decisions
| decision | principle preserved |
|---|---|
| `_apc64_host/domain/resolver.py` is the single read model. Every surface (replica labels, Shift preview, card, overview, nav bar, OLED names) is derived from resolve(layout, nav), and the page renders from it rather than re-deriving meaning. | SRP / one read model (no duplicated derivation) |
| `_apc64_host/domain/controls.py` SURFACE is the only enumeration of physical controls (role, names, geometry). surface_map, schema and the page (/api/surface) derive from it, and a test checks that the wire table covers it. | DRY: collapse the control cascade into one accessor |
| `_apc64_host/domain/surface.py` HostSurface is pure (input → effects), composed of the parts in surface_parts.py. Time enters only as Tick, through ScheduleAfter effects. | Functional core / imperative shell; SRP via composition |
| `_apc64_host/domain/router.py` ExpressiveRouter routes Notes/Custom-port playing by note number. Its held-note table makes each note-off reuse its note-on's transform; replica positions are never used for routing. | SRP; the domain model matches real-world invariants |
| `_apc64_host/application/session.py` DeviceSession holds the unit only between consent and release. Consent and identity come before DAW mode, holder changes are watched (no probe-open), and one release() serves every exit path. | SRP; fail-safe single exit |
| `_apc64_host/application/outbound_gate.py` OutboundGate is the only writer to the unit. It checks every frame against the injected OutboundPolicy, defined in `_apc64_host/domain/outbound.py` as CONTRACT1_POLICY with the 0x13/0x14/0x17/0x18 commands taken out, and logs refused frames. | DIP + OCP: the policy is injected and extended by modules |
| `_apc64_host/application/modules.py` HostModule is the contract 2 seam: policy additions plus routers, registered at the composition root. | OCP: extend by adding a module, not by editing the core |
| `_apc64_host/application/layout_pipeline.py` LayoutPipeline validates and compiles before an atomic swap, keeps a version copy of every live version, and discards invalid content while the previous layout stays live. | Fail-safe staging; immutable aggregate swap |
| `_apc64_host/notation/splice.py` saves a page tweak as one single-control entry line in the parser's own notation. It never re-dumps the document. | Inverse pairs co-located; minimal blast radius |
| `_apc64_host/presentation/network_guard.py` guards every request locally: allowed networks plus a same-site Origin/Host. There is no login anywhere. | Separation of concerns: the transport guard lives at the edge, not in services |
| `_apc64_host/notation/grammar.py` is the one grammar table, shared by compiler, splice and schema, so the docs schema, the validator and the tweak writer cannot drift. | DRY / co-located emit and parse |
| `_apc64_host/protocol/surface_map.py` is one bidirectional wire table for input decode and LED encode. | DRY / inverse pair in one module |
| `_apc64_host/__main__.py` is the only composition root, using constructor injection everywhere. The simulated unit and in-test doubles are swapped in through the same ports. | DIP; testability |
| `_apc64_host/domain/layout.py` makes LayoutId a value object constrained to file stems, and `_apc64_host/presentation/api.py` accepts layout text or LayoutId only (never a filesystem path). | Value objects against primitive obsession; boundary security |
| `_apc64_host/infrastructure/alsa_seq.py` implements HolderLookup from sequencer subscriptions and System Announce events, so freeing the port is noticed without ever probe-opening it. | DIP (HolderLookup port) and co-existence by design |
| `_apc64_host/application/engine.py` funnels every input (unit threads, feedback, replica, timers) through one ordered queue. Replica input enters the same HostSurface.handle as hardware. | Single entry point / determinism (inv10) |

### 7.2 Seams
Role: binding — every connection to prove; each row's two sides are attached to tasks by their BINDS notation.
| # | from | to | contract | proven by |
|---|---|---|---|---|
| s1 | `LAN HTTP client` (any browser or tool on the network) | `_apc64_host/presentation/network_guard.py` | Every HTTP request and WebSocket handshake → passed on unchanged or refused with 403. | supplier: `_apc64_host/presentation/test_network_guard.py` — one case per branch: 192.168.1.23, fd00::23, ::1 and ::ffff:192.168.1.40 pass; 203.0.113.5 refused; Origin https://example.com refused; no Origin (CLI) passes. |
| s2 | `Agent` (shell) | `_apc64_host/presentation/cli.py` | apc64 subcommands → output and exit code. | supplier: `_apc64_host/presentation/test_cli.py` — runs main(argv) per subcommand against a fake HTTP transport: success, 409 refusal and connection refused (offline validate vs exit 2). |
| s3 | `APC64` (unit, unprompted) | `_apc64_host/infrastructure/alsa_rawmidi.py` | Unprompted MIDI/SysEx bytes on the DAW, Notes and Custom subdevices → delivered to the role's listener in order; read failure → gone. | supplier: `_apc64_host/infrastructure/test_alsa_rawmidi.py` — a stubbed snd_rawmidi_read replays fixtures/daw-mode-views-velocity-aftertouch-2026-10-23.log bytes in random chunk sizes; asserts byte order per role and a single on_gone on EIO. |
| s4 | `Target devices and sequencer clients` (MPC, Bitwig, Chrome, ALSA System Announce; unprompted) | `_apc64_host/infrastructure/alsa_seq.py` | Incoming events on listened ports, and announce events → listener callbacks, presence changes and holder changes. | supplier: `_apc64_host/infrastructure/test_alsa_seq.py` — an alsa-midi event double feeds a recorded note, CC, port exit of 'MPC Live III MIDI 1' and unsubscribe of client 'Chrome' from 'APC64 DAW (APC64)'; asserts the callbacks. |
| s5 | `Linux kernel` (/dev/snd device nodes, unprompted) | `_apc64_host/infrastructure/unit_locator.py` | Device-node create/delete events → rescan and a presence notification. | supplier: `_apc64_host/infrastructure/test_unit_locator.py` — stubbed inotify events with stubbed `amidi -l` output moving the APC64 from card 4 to card 5; asserts one presence notification each. |
| s6 | `Layout file writers` (agent, editor, script) | `_apc64_host/infrastructure/layout_files.py` | File writes, renames and deletes in layouts/ → one change event per LayoutId. | supplier: `_apc64_host/infrastructure/test_layout_files.py` — in a temp dir with real inotify: write jam.yaml, rename a .tmp onto it, delete it, write notes.txt; asserts the event list. |
| s7 | `systemd` (service manager) | `_apc64_host/__main__.py` | Service start → lifespan startup → DeviceSession.start(); stop signal → lifespan shutdown → DeviceSession.release('stop') once. | supplier: `_apc64_host/test___main__.py` — runs the built app's lifespan start and shutdown with a recording session double; asserts start() once, then release('stop') once. |
| s8 | `the user` (page user) | `_apc64_host/presentation/static` | Gestures on the page → one API call each, with the response shown. | supplier: `_apc64_host/presentation/static/app.test.js` — dispatches each gesture to the pure handlers with a recording api double; asserts the call sequence and the displayed problem for a 409. |
| s9 | `_apc64_host/presentation/static` | `_apc64_host/presentation/api.py` | Page HTTP calls of docs/api.md → JSON answers. | collaboration: `_apc64_host/presentation/static/api.test.js` — fake fetch returning canned 200/400/409; asserts the requests api.js sends and the mapped results., supplier: `_apc64_host/presentation/test_api.py` — TestClient over build_app with service doubles: each route accepts its payload and maps 200/400/409. |
| s10 | `_apc64_host/presentation/cli.py` | `_apc64_host/presentation/api.py` | CLI subcommands → the same HTTP routes; validate sends the file's text. | collaboration: `_apc64_host/presentation/test_cli.py` — fake HTTP transport records requests per subcommand and returns canned 200/409; asserts output and exit codes., supplier: `_apc64_host/presentation/test_api.py` — the same routes accept CLI-shaped requests (no Origin header). |
| s11 | `_apc64_host/presentation/network_guard.py` | `_apc64_host/presentation/api.py` | Allowed requests forwarded unchanged → the app's response returned unchanged. | collaboration: `_apc64_host/presentation/test_network_guard.py` — inner-app double records the forwarded scope and returns a canned response., supplier: `_apc64_host/presentation/test_api.py` — build_app handles HTTP and websocket scopes passed through the middleware stack. |
| s12 | `_apc64_host/presentation/api.py` | `_apc64_host/presentation/ws_hub.py` | WebSocket routes /ws and /ws/play → hub accepts and owns the socket. | collaboration: `_apc64_host/presentation/test_api.py` — hub double records the accepted channel per route., supplier: `_apc64_host/presentation/test_ws_hub.py` — accept() for each channel runs until close. |
| s13 | `_apc64_host/presentation/api.py` | `_apc64_host/presentation/view_model.py` | Application views → JSON-safe dicts. | collaboration: `_apc64_host/presentation/test_api.py` — view_model double returns canned dicts; asserts they are the response bodies., supplier: `_apc64_host/presentation/test_view_model.py` — one case per view type. |
| s14 | `_apc64_host/presentation/ws_hub.py` | `_apc64_host/presentation/view_model.py` | Snapshots, diffs, activity and play events → JSON messages. | collaboration: `_apc64_host/presentation/test_ws_hub.py` — view_model double; asserts the frames sent., supplier: `_apc64_host/presentation/test_view_model.py` — one case per message type. |
| s15 | `_apc64_host/presentation/api.py` | `_apc64_host/application/session.py` | take/decline/release/status calls → session answers. | collaboration: `_apc64_host/presentation/test_api.py` — session double with one canned answer each; asserts the 200/409 mapping., supplier: `_apc64_host/application/test_session.py` — each answer produced from the simulated unit and port doubles. |
| s16 | `_apc64_host/presentation/api.py` | `_apc64_host/application/engine.py` | Navigation and replica input → engine. | collaboration: `_apc64_host/presentation/test_api.py` — engine double; asserts the calls and the 409 for UNKNOWN_LAYOUT., supplier: `_apc64_host/application/test_engine.py` — each call is handled through the same queue as hardware input. |
| s17 | `_apc64_host/presentation/api.py` | `_apc64_host/application/layout_pipeline.py` | Validate text, list versions, restore. | collaboration: `_apc64_host/presentation/test_api.py` — pipeline double with canned report and answers., supplier: `_apc64_host/application/test_layout_pipeline.py` — each call against layout/version doubles. |
| s18 | `_apc64_host/presentation/api.py` | `_apc64_host/application/library.py` | List layouts. | collaboration: `_apc64_host/presentation/test_api.py` — library double., supplier: `_apc64_host/application/test_library.py` — summaries after registrations. |
| s19 | `_apc64_host/presentation/api.py` | `_apc64_host/application/tweaks.py` | Single-control tweak → saved or refused. | collaboration: `_apc64_host/presentation/test_api.py` — tweaks double returning each answer; asserts 200/409/400., supplier: `_apc64_host/application/test_tweaks.py` — each answer from file and notation doubles. |
| s20 | `_apc64_host/presentation/api.py` | `_apc64_host/application/learn.py` | Learn mode changes. | collaboration: `_apc64_host/presentation/test_api.py` — learn double., supplier: `_apc64_host/application/test_learn.py` — each mode change. |
| s21 | `_apc64_host/presentation/api.py` | `_apc64_host/application/calibration.py` | Calibration steps. | collaboration: `_apc64_host/presentation/test_api.py` — calibration double., supplier: `_apc64_host/application/test_calibration.py` — start and cancel status transitions. |
| s22 | `_apc64_host/presentation/api.py` | `_apc64_host/application/state_view.py` | Read views. | collaboration: `_apc64_host/presentation/test_api.py` — state_view double., supplier: `_apc64_host/application/test_state_view.py` — each view from engine/session/library doubles. |
| s23 | `_apc64_host/presentation/api.py` | `_apc64_host/application/activity.py` | Recent activity. | collaboration: `_apc64_host/presentation/test_api.py` — activity double., supplier: `_apc64_host/application/test_activity.py` — recent() after appends. |
| s24 | `_apc64_host/presentation/api.py` | `_apc64_host/application/outbound_gate.py` | Device log read. | collaboration: `_apc64_host/presentation/test_api.py` — gate double., supplier: `_apc64_host/application/test_outbound_gate.py` — the log after sent and refused frames. |
| s25 | `_apc64_host/presentation/api.py` | `_apc64_host/infrastructure/alsa_seq.py` | Port listing (PortCatalog). | collaboration: `_apc64_host/presentation/test_api.py` — PortCatalog double., supplier: `_apc64_host/infrastructure/test_alsa_seq.py` — list() over an alsa-midi double including client 'APC64' excludes it. |
| s26 | `_apc64_host/presentation/ws_hub.py` | `_apc64_host/application/state_view.py` | State subscription. | collaboration: `_apc64_host/presentation/test_ws_hub.py` — state_view double emits snapshot + diff; asserts the frames., supplier: `_apc64_host/application/test_state_view.py` — subscribe yields snapshot then diffs. |
| s27 | `_apc64_host/presentation/ws_hub.py` | `_apc64_host/application/activity.py` | Activity subscription. | collaboration: `_apc64_host/presentation/test_ws_hub.py` — activity double., supplier: `_apc64_host/application/test_activity.py` — subscriber receives appends and folds. |
| s28 | `_apc64_host/presentation/ws_hub.py` | `_apc64_host/application/play_stream.py` | Play-stream subscription. | collaboration: `_apc64_host/presentation/test_ws_hub.py` — stream double emits events then CLOSED; asserts the frames and socket close., supplier: `_apc64_host/application/test_play_stream.py` — ordering and lag closure. |
| s29 | `_apc64_host/presentation/cli.py` | `_apc64_host/notation` | Offline validation. | collaboration: `_apc64_host/presentation/test_cli.py` — notation double returns canned issues; asserts printed lines and exit 1., supplier: `_apc64_host/notation/test_compiler.py` — compile_text without a catalog. |
| s30 | `_apc64_host/presentation/static` | `_apc64_host/presentation/ws_hub.py` | /ws connection → snapshot, diffs, activity. | collaboration: `_apc64_host/presentation/static/state.test.js` — fake socket delivers snapshot, diffs, drop and snapshot; asserts the reducer resets to the new snapshot., supplier: `_apc64_host/presentation/test_ws_hub.py` — snapshot first on each connect. |
| s31 | `_apc64_host/presentation/cli.py` | `_apc64_host/presentation/ws_hub.py` | /ws/play for `apc64 watch`. | collaboration: `_apc64_host/presentation/test_cli.py` — fake socket; asserts printed lines and exit on the closed notice., supplier: `_apc64_host/presentation/test_ws_hub.py` — play channel framing and closed notice. |
| s32 | `_apc64_host/application/session.py` | `_apc64_host/infrastructure/unit_locator.py` | Find the unit by name, and presence changes. | collaboration: `_apc64_host/application/test_session.py` — locator double reports None → presence → None; asserts Asking/Unplugged transitions., supplier: `_apc64_host/infrastructure/test_unit_locator.py` — find() over recorded amidi output for card 4 and card 5. |
| s33 | `_apc64_host/application/session.py` | `_apc64_host/infrastructure/alsa_seq.py` | HolderLookup: who holds an APC64 port, and changes. | collaboration: `_apc64_host/application/test_session.py` — holder double goes from 'Bitwig Studio' to None; asserts Busy then a new Asking prompt, with no open attempt., supplier: `_apc64_host/infrastructure/test_alsa_seq.py` — holder_of from subscriber queries and announce events. |
| s34 | `_apc64_host/application/session.py` | `_apc64_host/infrastructure/alsa_rawmidi.py` | Exclusive open per role, and close. | collaboration: `_apc64_host/application/test_session.py` — UnitPort double answering each; asserts Held / Busy / NoPermission and the Notes-busy notice., supplier: `_apc64_host/infrastructure/test_alsa_rawmidi.py` — open/close per role and errno mapping over a ctypes lib double. |
| s35 | `_apc64_host/application/session.py` | `_apc64_host/infrastructure/notifier.py` | Desktop consent prompt. | collaboration: `_apc64_host/application/test_session.py` — prompt double answers TAKE and DISMISSED; asserts take(NOTIFICATION) and the withdraw on a banner yes., supplier: `_apc64_host/infrastructure/test_notifier.py` — the subprocess double prints 'take' or exits silently. |
| s36 | `_apc64_host/application/session.py` | `_apc64_host/infrastructure/state_store.py` | Holding marker. | collaboration: `_apc64_host/application/test_session.py` — store double with a stale marker → MaybeStuck and nothing sent., supplier: `_apc64_host/infrastructure/test_state_store.py` — set/clear/present in a temp dir. |
| s37 | `_apc64_host/application/session.py` | `_apc64_host/application/outbound_gate.py` | Attach and detach the DAW connection; session frames. | collaboration: `_apc64_host/application/test_session.py` — gate double; asserts release order clear → DAW off → detach and handling of PortGone., supplier: `_apc64_host/application/test_outbound_gate.py` — attach/send/detach answers. |
| s38 | `_apc64_host/application/session.py` | `_apc64_host/application/engine.py` | Hold lifecycle and supervision. | collaboration: `_apc64_host/application/test_session.py` — engine double raising in run(); asserts release(reason=fault)., supplier: `_apc64_host/application/test_engine.py` — on_held redraw, on_released clear frames, fault propagation. |
| s39 | `_apc64_host/application/session.py` | `_apc64_host/protocol` | Handshake frames and identity parsing. | collaboration: `_apc64_host/application/test_session.py` — protocol double returns Identity(product 0x51) → NOT_AN_APC64., supplier: `_apc64_host/protocol/test_sysex.py` — frames byte-exact against PROTOCOL-SPEC.md §4; identity from the fixture reply. |
| s40 | `_apc64_host/application/session.py` | `_apc64_host/domain` | UnitStatus transitions. | collaboration: `_apc64_host/application/test_session.py` — real domain (pure) driven by the session's observations., supplier: `_apc64_host/domain/test_unit_status.py` — the transition table, one case per observation per state. |
| s41 | `_apc64_host/application/session.py` | `_apc64_host/infrastructure/clock.py` | Timers for the identity timeout and the presence fallback. | collaboration: `_apc64_host/application/test_session.py` — manual clock double fires the identity timeout → 'No APC64 identity reply'., supplier: `_apc64_host/infrastructure/test_clock.py` — call_later fires and cancels on a running loop. |
| s42 | `_apc64_host/application/engine.py` | `_apc64_host/domain` | Pure handling: surface, feedback, played MIDI, ticks, layout swaps → effects. | collaboration: `_apc64_host/application/test_engine.py` — executes canned effect lists against port doubles; asserts each effect kind reaches its port., supplier: `_apc64_host/domain/test_surface.py` — navigation, momentary/toggle, Shift, browse, feedback, unbound; `_apc64_host/domain/test_router.py` — velocity, aftertouch policies, transpose, remap, held notes. |
| s43 | `_apc64_host/application/engine.py` | `_apc64_host/protocol` | Decode unit bytes, encode LED/OLED. | collaboration: `_apc64_host/application/test_engine.py` — protocol double yields canned inputs; asserts they reach the domain., supplier: `_apc64_host/protocol/test_surface_map.py` — decode of fixture bytes and encode per LED kind; `_apc64_host/protocol/test_midi_codec.py`. |
| s44 | `_apc64_host/application/engine.py` | `_apc64_host/application/outbound_gate.py` | LED and OLED frames. | collaboration: `_apc64_host/application/test_engine.py` — gate double; asserts redraw frames on a Session report and no error when DROPPED., supplier: `_apc64_host/application/test_outbound_gate.py`. |
| s45 | `_apc64_host/application/engine.py` | `_apc64_host/infrastructure/alsa_seq.py` | Target sends, feedback listening, port presence. | collaboration: `_apc64_host/application/test_engine.py` — TargetPorts double answering MISSING → activity 'not sent: mpc missing'., supplier: `_apc64_host/infrastructure/test_alsa_seq.py` — send/listen/presence over an alsa-midi double. |
| s46 | `_apc64_host/application/engine.py` | `_apc64_host/infrastructure/alsa_rawmidi.py` | Listen to held connections. | collaboration: `_apc64_host/application/test_engine.py` — connection double pushes chunks from two threads; asserts queue order., supplier: `_apc64_host/infrastructure/test_alsa_rawmidi.py`. |
| s47 | `_apc64_host/application/engine.py` | `_apc64_host/application/activity.py` | Activity entries. | collaboration: `_apc64_host/application/test_engine.py` — activity double records entries., supplier: `_apc64_host/application/test_activity.py`. |
| s48 | `_apc64_host/application/engine.py` | `_apc64_host/application/play_stream.py` | Play events. | collaboration: `_apc64_host/application/test_engine.py` — stream double records events., supplier: `_apc64_host/application/test_play_stream.py` — publish never blocks with a stalled subscriber. |
| s49 | `_apc64_host/application/engine.py` | `_apc64_host/application/library.py` | Compiled layouts and the browse catalog. | collaboration: `_apc64_host/application/test_engine.py` — library double; asserts RequestLayout fulfilment and 'No layout' when none., supplier: `_apc64_host/application/test_library.py`. |
| s50 | `_apc64_host/application/engine.py` | `_apc64_host/application/learn.py` | Touch interception. | collaboration: `_apc64_host/application/test_engine.py` — learn double answers CAPTURED; asserts no Send., supplier: `_apc64_host/application/test_learn.py`. |
| s51 | `_apc64_host/application/engine.py` | `_apc64_host/application/calibration.py` | Played-note observation. | collaboration: `_apc64_host/application/test_engine.py` — calibration double records observations., supplier: `_apc64_host/application/test_calibration.py`. |
| s52 | `_apc64_host/application/engine.py` | `_apc64_host/infrastructure/clock.py` | ScheduleAfter fulfilment. | collaboration: `_apc64_host/application/test_engine.py` — manual clock; asserts the OLED name reverts after 2 s., supplier: `_apc64_host/infrastructure/test_clock.py`. |
| s53 | `_apc64_host/application/engine.py` | `_apc64_host/infrastructure/state_store.py` | Last nav and strip positions. | collaboration: `_apc64_host/application/test_engine.py` — store double; asserts restore on hold., supplier: `_apc64_host/infrastructure/test_state_store.py`. |
| s54 | `_apc64_host/application/outbound_gate.py` | `_apc64_host/infrastructure/alsa_rawmidi.py` | The single DAW write path. | collaboration: `_apc64_host/application/test_outbound_gate.py` — connection double; asserts serialised writes and PortGone propagation., supplier: `_apc64_host/infrastructure/test_alsa_rawmidi.py` — write maps errno to PortGone. |
| s55 | `_apc64_host/application/outbound_gate.py` | `_apc64_host/protocol` | Classify a frame. | collaboration: `_apc64_host/application/test_outbound_gate.py` — real protocol (pure)., supplier: `_apc64_host/protocol/test_sysex.py` — command_of for 0x10/0x13/0x14/0x17/0x18/0x19/0x1B/0x1C, identity and note frames. |
| s56 | `_apc64_host/application/outbound_gate.py` | `_apc64_host/domain` | Policy decision. | collaboration: `_apc64_host/application/test_outbound_gate.py` — injected CONTRACT1_POLICY refuses 0x14; asserts REFUSED, the device log and no write., supplier: `_apc64_host/domain/test_outbound.py` — CONTRACT1_POLICY excludes 0x13/0x14/0x17/0x18 and allows the handshake/OLED commands. |
| s57 | `_apc64_host/application/layout_pipeline.py` | `_apc64_host/infrastructure/layout_files.py` | Read, watch and write layout files. | collaboration: `_apc64_host/application/test_layout_pipeline.py` — LayoutSource double emitting CHANGED twice within 200 ms; asserts one compile., supplier: `_apc64_host/infrastructure/test_layout_files.py`. |
| s58 | `_apc64_host/application/layout_pipeline.py` | `_apc64_host/notation` | Compile with port checks. | collaboration: `_apc64_host/application/test_layout_pipeline.py` — notation double returns issues → live layout unchanged and issues published., supplier: `_apc64_host/notation/test_compiler.py` — every issue kind with file, line, control, problem and fix. |
| s59 | `_apc64_host/application/layout_pipeline.py` | `_apc64_host/infrastructure/version_store.py` | Version copies. | collaboration: `_apc64_host/application/test_layout_pipeline.py` — store double; asserts save only for valid, changed content., supplier: `_apc64_host/infrastructure/test_version_store.py`. |
| s60 | `_apc64_host/application/layout_pipeline.py` | `_apc64_host/application/library.py` | Register results. | collaboration: `_apc64_host/application/test_layout_pipeline.py` — library double answers DUPLICATE_NAME; asserts an issue naming both files and no swap., supplier: `_apc64_host/application/test_library.py`. |
| s61 | `_apc64_host/application/layout_pipeline.py` | `_apc64_host/application/engine.py` | Swap the live layout. | collaboration: `_apc64_host/application/test_layout_pipeline.py` — engine double records swaps., supplier: `_apc64_host/application/test_engine.py` — swap carries toggles and redraws. |
| s62 | `_apc64_host/application/layout_pipeline.py` | `_apc64_host/infrastructure/clock.py` | Settle window. | collaboration: `_apc64_host/application/test_layout_pipeline.py` — manual clock., supplier: `_apc64_host/infrastructure/test_clock.py`. |
| s63 | `_apc64_host/application/tweaks.py` | `_apc64_host/notation` | Splice and re-validate. | collaboration: `_apc64_host/application/test_tweaks.py` — notation double returns issues → INVALID and no write., supplier: `_apc64_host/notation/test_splice.py` — each tweak kind; untouched bytes identical; tweak back to the range value removes the entry. |
| s64 | `_apc64_host/application/tweaks.py` | `_apc64_host/infrastructure/layout_files.py` | Read with hash, atomic write. | collaboration: `_apc64_host/application/test_tweaks.py` — source double with a different hash → STALE and no write., supplier: `_apc64_host/infrastructure/test_layout_files.py`. |
| s65 | `_apc64_host/application/learn.py` | `_apc64_host/infrastructure/alsa_seq.py` | MIDI-learn listening. | collaboration: `_apc64_host/application/test_learn.py` — FeedbackInputs double delivers CC 74 ch 1 → one tweak; cancel delivers nothing., supplier: `_apc64_host/infrastructure/test_alsa_seq.py`. |
| s66 | `_apc64_host/application/learn.py` | `_apc64_host/application/tweaks.py` | Save the learned assignment. | collaboration: `_apc64_host/application/test_learn.py` — tweaks double; asserts the request built from CC 74 on 'mpc'., supplier: `_apc64_host/application/test_tweaks.py`. |
| s67 | `_apc64_host/application/calibration.py` | `_apc64_host/infrastructure/state_store.py` | Persist the calibration. | collaboration: `_apc64_host/application/test_calibration.py` — store double., supplier: `_apc64_host/infrastructure/test_state_store.py`. |
| s68 | `_apc64_host/application/state_view.py` | `_apc64_host/domain` | Meaning, card and overview. | collaboration: `_apc64_host/application/test_state_view.py` — real domain (pure)., supplier: `_apc64_host/domain/test_resolver.py` — base/Shift labels, generated labels, empty, missing port, elsewhere, 50 × 8 × 6 layout. |
| s69 | `_apc64_host/application/state_view.py` | `_apc64_host/application/engine.py` | Engine snapshot and changes. | collaboration: `_apc64_host/application/test_state_view.py` — engine double., supplier: `_apc64_host/application/test_engine.py` — snapshot equals the frame sent to the gate. |
| s70 | `_apc64_host/application/state_view.py` | `_apc64_host/application/session.py` | Unit status. | collaboration: `_apc64_host/application/test_state_view.py` — session double., supplier: `_apc64_host/application/test_session.py`. |
| s71 | `_apc64_host/application/state_view.py` | `_apc64_host/application/library.py` | Layouts, issues, warnings. | collaboration: `_apc64_host/application/test_state_view.py` — library double., supplier: `_apc64_host/application/test_library.py`. |
| s72 | `_apc64_host/application/state_view.py` | `_apc64_host/application/calibration.py` | Current calibration. | collaboration: `_apc64_host/application/test_state_view.py` — calibration double: None → 'pad position unknown', present → 'calibrated <time> (assumed)'., supplier: `_apc64_host/application/test_calibration.py`. |
| s73 | `_apc64_host/application/play_stream.py` | `_apc64_host/infrastructure/clock.py` | Lag measurement. | collaboration: `_apc64_host/application/test_play_stream.py` — manual clock advances 6 s with a stalled subscriber → CLOSED., supplier: `_apc64_host/infrastructure/test_clock.py`. |
| s74 | `_apc64_host/notation` | `_apc64_host/domain` | Build the Layout aggregate. | collaboration: `_apc64_host/notation/test_compiler.py` — real domain; asserts each DomainInvariantError becomes a LayoutIssue at the right SourceRef., supplier: `_apc64_host/domain/test_layout.py` — page 9, bank 7, strip toggle, Shift encoder binding, APC64 target, value ranges; `_apc64_host/domain/test_controls.py` and `test_midi.py` for names. |
| s75 | `_apc64_host/protocol` | `_apc64_host/domain` | Domain types for codecs. | collaboration: `_apc64_host/protocol/test_surface_map.py` — real domain; asserts the wire table covers every non-DEVICE_LOCAL SURFACE entry., supplier: `_apc64_host/domain/test_controls.py`. |
| s76 | `_apc64_host/__main__.py` | `_apc64_host/application/session.py` | Start and final release. | collaboration: `_apc64_host/test___main__.py` — session double records start then release., supplier: `_apc64_host/application/test_session.py`. |
| s77 | `_apc64_host/__main__.py` | `_apc64_host/application/modules.py` | Module registration. | collaboration: `_apc64_host/test___main__.py` — asserts the gate gets CONTRACT1_POLICY when no module is registered., supplier: `_apc64_host/application/test_modules.py` — a fake module adding one SysexCommand and one route is collected without core edits. |
| s78 | `_apc64_host/__main__.py` | `_apc64_host/config.py` | Load configuration. | collaboration: `_apc64_host/test___main__.py` — config double with a ConfigError → clear exit., supplier: `_apc64_host/test_config.py` — defaults, file values, env override, bad value per key. |
| s79 | `_apc64_host/__main__.py` | `uvicorn` (third-party server) | Serve the app dual-stack with lifespan. | collaboration: `_apc64_host/test___main__.py` — uvicorn.run double records host '::', port and lifespan 'on'. |
| s80 | `_apc64_host/infrastructure/alsa_rawmidi.py` | `ALSA rawmidi` (libasound via ctypes) | Exclusive subdevice open, read, write, close; errno mapping. | collaboration: `_apc64_host/infrastructure/test_alsa_rawmidi.py` — ctypes library double returning each errno; asserts the open strings and the error mapping. The real device runs once in `_apc64_host/infrastructure/test_alsa_rawmidi_live.py` (-m live). |
| s81 | `_apc64_host/infrastructure/unit_locator.py` | `alsa-utils amidi and inotify on /dev/snd` | List rawmidi devices and watch device nodes. | collaboration: `_apc64_host/infrastructure/test_unit_locator.py` — subprocess double returns the `amidi -l` output recorded in this run; asserts DAW hw:4,0,0, Notes hw:4,0,1, Custom hw:4,0,3, and None without APC64 lines. |
| s82 | `_apc64_host/infrastructure/alsa_seq.py` | `ALSA sequencer` (alsa-midi) | Client, ports, sends, subscriptions, announce, subscriber queries. | collaboration: `_apc64_host/infrastructure/test_alsa_seq.py` — alsa-midi double; asserts the calls sent, the exclusion of client 'APC64', and the MISSING/FAILED mapping. The real sequencer runs once in `_apc64_host/infrastructure/test_alsa_seq_live.py` (-m live). |
| s83 | `_apc64_host/infrastructure/layout_files.py` | `Filesystem and inotify` (layouts dir on ntfs-3g) | Atomic writes and change events. | collaboration: `_apc64_host/infrastructure/test_layout_files.py` — runs the adapter in a temp dir; asserts temp-then-rename and the event mapping. |
| s84 | `_apc64_host/infrastructure/version_store.py` | `Filesystem` (state dir) | Version files. | collaboration: `_apc64_host/infrastructure/test_version_store.py` — temp dir; asserts names, ordering and read-back. |
| s85 | `_apc64_host/infrastructure/state_store.py` | `Filesystem` (state dir) | Marker and JSON state files. | collaboration: `_apc64_host/infrastructure/test_state_store.py` — temp dir round trips. |
| s86 | `_apc64_host/infrastructure/notifier.py` | `notify-send` (libnotify) | Show the notification with an action, and withdraw it. | collaboration: `_apc64_host/infrastructure/test_notifier.py` — subprocess double; asserts argv, both outputs mapped, and termination on withdraw. |
| s87 | `_apc64_host/infrastructure/clock.py` | `Python runtime` (asyncio, time) | Timers and monotonic time. | collaboration: `_apc64_host/infrastructure/test_clock.py` — on a running loop asserts call_later fires and its handle cancels. |
| s88 | `_apc64_host/config.py` | `Environment and config.local` | Read KEY=VALUE and the environment. | collaboration: `_apc64_host/test_config.py` — temp config.local plus env dict; asserts precedence. |
| s89 | `_apc64_host/application/layout_pipeline.py` | `_apc64_host/infrastructure/alsa_seq.py` | Port catalog snapshot for compile. | collaboration: `_apc64_host/application/test_layout_pipeline.py` — catalog double with 'MPC Live III MIDI 1' and 'USB MIDI Interface MIDI 1' passed into compile., supplier: `_apc64_host/infrastructure/test_alsa_seq.py`. |
| s90 | `_apc64_host/application/state_view.py` | `_apc64_host/application/learn.py` | Learn status for the page. | collaboration: `_apc64_host/application/test_state_view.py` — learn double with a selected 'track 3'., supplier: `_apc64_host/application/test_learn.py`. |
| s91 | `the user` (desktop notification, unprompted click) | `_apc64_host/infrastructure/notifier.py` | A click on Take, or a dismissal, on the shown notification → the pending ask resolves. | supplier: `_apc64_host/infrastructure/test_notifier.py` — the subprocess double emits 'take' after ask (TAKE once), exits silently (DISMISSED), and emits 'take' after withdraw (ignored). |

### 7.3 Seam clauses
Role: binding — each seam's contract, clause by clause: an expectation is what the consumer sends, which the supplier must accept; an answer is what the consumer relies on getting back, and when. Every clause is proven on both sides — by the consumer's test over a double and by the supplier's test of the real thing. Where the supplier is a third party outside the design, our side is the test of how we USE it, and its side is the clause's `basis`: `documented: <where its documentation says so>`, `assumption <a §2.6 id>` (relied on, not guaranteed — validated as its grade says), or `customer-ci` (a supplier the customer's organisation owns, whose CI runs our consumer contract). Clauses whose supplier is in this design leave `basis` empty.
| clause | seam | kind | the promise | basis |
|---|---|---|---|---|
| s1.c1 | s1 | expectation | Any HTTP request or WebSocket handshake carrying a client address, a Host header and optionally an Origin header. | - |
| s1.c2 | s1 | answer | A client in the allowed networks with no Origin, or a same-site Origin, is passed on unchanged. | - |
| s1.c3 | s1 | answer | A client outside the allowed networks gets 403 {problem:'not on the home network'}, and nothing else runs. | - |
| s1.c4 | s1 | answer | A foreign Origin or a mismatched Host gets 403 {problem:'cross-site request refused'}, and nothing else runs. | - |
| s2.c1 | s2 | expectation | apc64 take \| release \| ports \| layouts \| validate PATH \| load NAME \| page N \| bank N \| state \| watch \| versions NAME \| restore NAME VERSION. | - |
| s2.c2 | s2 | answer | Success prints the result and exits 0. | - |
| s2.c3 | s2 | answer | A refusal or validation error from the service prints its problem/issues and exits 1. | - |
| s2.c4 | s2 | answer | When the service is unreachable, validate runs offline (structure only, with 'ports not checked') and other commands print 'service not running on port 5058' and exit 2. | - |
| s3.c1 | s3 | expectation | MIDI and SysEx bytes in the formats of fixtures/*.log (identity reply, note on/off, pitch bend, poly aftertouch, view reports), in any chunking. | - |
| s3.c2 | s3 | answer | Each chunk is delivered unmodified and in arrival order to the listener registered for that role. | - |
| s3.c3 | s3 | answer | A read failing with ENODEV or EIO calls on_gone(role) exactly once and stops that reader. | - |
| s4.c1 | s4 | expectation | Note on/off, CC, program change and pitch-bend events from a listened port, plus System Announce events (port start/exit, subscribe/unsubscribe). | - |
| s4.c2 | s4 | answer | Each MIDI event reaches the port's listener as a MidiMessage, in order. | - |
| s4.c3 | s4 | answer | A port start/exit becomes a presence change for that PortName. | - |
| s4.c4 | s4 | answer | A subscribe/unsubscribe touching an APC64 port becomes a holder change (Holder name or None) for that role. | - |
| s5.c1 | s5 | expectation | inotify create/delete events for /dev/snd/midiC<n>D0 nodes, or any other node. | - |
| s5.c2 | s5 | answer | A midiC node event triggers a rescan and notifies subscribers with UnitPresence (any card number) or None. | - |
| s5.c3 | s5 | answer | Non-MIDI nodes are ignored. | - |
| s6.c1 | s6 | expectation | Create, write-and-close, rename-into and delete of files in the layouts directory, including temporary names. | - |
| s6.c2 | s6 | answer | For *.yaml with a valid LayoutId stem: CLOSE_WRITE or MOVED_TO → CHANGED; DELETE or MOVED_FROM → DELETED. | - |
| s6.c3 | s6 | answer | Other names (temp files, non-yaml, invalid stems) produce no event. | - |
| s7.c1 | s7 | expectation | The service process is started, and later receives SIGTERM or SIGINT. | - |
| s7.c2 | s7 | answer | Lifespan startup calls DeviceSession.start() exactly once; nothing is sent to the unit by startup itself. | - |
| s7.c3 | s7 | answer | Lifespan shutdown calls DeviceSession.release('stop') exactly once before the process exits with status 0. | - |
| s8.c1 | s8 | expectation | Pointer down/up on a control, drag on a strip, banner Yes/No/Release, nav clicks, holding the page Shift, selecting a control, learn/calibrate buttons, saving a tweak. | - |
| s8.c2 | s8 | answer | Each gesture issues exactly its API call (press on down, release on up, move per drag step, shift held/released) and shows the answer or problem in the banner or card. | - |
| s9.c1 | s9 | expectation | GET state, surface, controls/{id}, overview, activity, layouts, layouts/{id}/versions; POST unit/take\|decline\|release, layout, page, bank, shift, control/{id}/press\|release\|move, tweak, learn, calibrate, layouts/{id}/restore, validate {text}. | - |
| s9.c2 | s9 | answer | 200 with the JSON body of that route. | - |
| s9.c3 | s9 | answer | 400 {problem, allowed} for a malformed or out-of-range request. | - |
| s9.c4 | s9 | answer | 409 {problem} for a refusal (e.g. 'already held', 'layout changed, reload', 'unknown layout'). | - |
| s10.c1 | s10 | expectation | The routes behind each subcommand; validate posts {text, file name}. | - |
| s10.c2 | s10 | answer | 200 JSON result. | - |
| s10.c3 | s10 | answer | 400/409 with {problem} or {issues}. | - |
| s11.c1 | s11 | expectation | The original ASGI scope, receive and send for an allowed HTTP or WebSocket request. | - |
| s11.c2 | s11 | answer | The app's response, returned to the client unchanged. | - |
| s12.c1 | s12 | expectation | accept(socket, channel STATE \| PLAY). | - |
| s12.c2 | s12 | answer | The hub owns the socket until either side closes, with no return value. | - |
| s13.c1 | s13 | expectation | A StateView, CardView, OverviewView, SurfaceCatalogView, ValidationReport, [ActivityEntry], [VersionId] or [DeviceLogEntry]. | - |
| s13.c2 | s13 | answer | A deterministic JSON-safe dict/list for that type. | - |
| s14.c1 | s14 | expectation | A StateView snapshot or diff, an ActivityEntry, a PlayEvent or a stream-closed notice. | - |
| s14.c2 | s14 | answer | A JSON-safe message {type, data}. | - |
| s15.c1 | s15 | expectation | take(ConsentSource), decline(), release(source), status(). | - |
| s15.c2 | s15 | answer | take → TAKEN(by) \| ALREADY_HELD \| BUSY(holder?) \| NO_PERMISSION \| NOT_AN_APC64 \| NOT_CONNECTED. | - |
| s15.c3 | s15 | answer | release → RELEASED \| NOT_HELD; decline → OK; status → UnitStatus. | - |
| s16.c1 | s16 | expectation | load(LayoutId), select_page(PageNo), select_bank(BankNo), set_page_shift(bool), replica_input(SurfaceInput). | - |
| s16.c2 | s16 | answer | OK(NavState) after the input has been queued and handled. | - |
| s16.c3 | s16 | answer | UNKNOWN_LAYOUT for a LayoutId the library does not hold. | - |
| s17.c1 | s17 | expectation | validate_text(text, file name), versions(LayoutId), restore(LayoutId, VersionId). | - |
| s17.c2 | s17 | answer | ValidationReport(issues in line order, warnings, counts). | - |
| s17.c3 | s17 | answer | [VersionId] newest first; restore → RESTORED \| UNKNOWN_VERSION. | - |
| s18.c1 | s18 | expectation | summaries(). | - |
| s18.c2 | s18 | answer | [LayoutSummary(id, name, valid, pages, banks)] in browse order. | - |
| s19.c1 | s19 | expectation | apply(TweakRequest). | - |
| s19.c2 | s19 | answer | SAVED \| STALE('layout changed, reload') \| INVALID([LayoutIssue]). | - |
| s20.c1 | s20 | expectation | set_mode(LearnMode TOUCH \| MIDI(PortName) \| OFF). | - |
| s20.c2 | s20 | answer | OK(LearnStatus) \| UNKNOWN_PORT. | - |
| s21.c1 | s21 | expectation | start() \| cancel(). | - |
| s21.c2 | s21 | answer | OK(CalibrationStatus: waiting for bottom-left, waiting for top-right, done, idle). | - |
| s22.c1 | s22 | expectation | snapshot(), card(ControlId), overview(), surface(). | - |
| s22.c2 | s22 | answer | StateView, CardView, OverviewView, SurfaceCatalogView; card of an unknown control → UNKNOWN_CONTROL. | - |
| s23.c1 | s23 | expectation | recent(limit ≤ 200). | - |
| s23.c2 | s23 | answer | [ActivityEntry], newest first. | - |
| s24.c1 | s24 | expectation | device_log(). | - |
| s24.c2 | s24 | answer | [DeviceLogEntry(at, frame, SENT \| REFUSED)] in send order. | - |
| s25.c1 | s25 | expectation | list(). | - |
| s25.c2 | s25 | answer | [PortInfo(name, direction, present)] without any APC64 port. | - |
| s26.c1 | s26 | expectation | subscribe(callback) / unsubscribe(token). | - |
| s26.c2 | s26 | answer | An immediate snapshot, then a diff after every change. | - |
| s27.c1 | s27 | expectation | subscribe(callback). | - |
| s27.c2 | s27 | answer | Every new or updated (aftertouch-folded) entry, in order. | - |
| s28.c1 | s28 | expectation | subscribe(). | - |
| s28.c2 | s28 | answer | PlayEvents from now on, in order. | - |
| s28.c3 | s28 | answer | CLOSED('too slow') when the subscriber lags more than 5 s. | - |
| s29.c1 | s29 | expectation | compile_text(text, file name) with no port catalog. | - |
| s29.c2 | s29 | answer | Layout plus warnings, or [LayoutIssue] in line order; port-dependent checks reported as 'ports not checked'. | - |
| s30.c1 | s30 | expectation | Open /ws, and reopen after a drop. | - |
| s30.c2 | s30 | answer | A snapshot first on every (re)connect, then diffs and activity messages. | - |
| s31.c1 | s31 | expectation | Open /ws/play. | - |
| s31.c2 | s31 | answer | One JSON event per message from now; a final {type:'closed', reason:'too slow'} before close when lagging. | - |
| s32.c1 | s32 | expectation | find(); subscribe(callback). | - |
| s32.c2 | s32 | answer | UnitPresence (DAW/Notes/Custom addresses on whatever card) or None, and a callback on every change. | - |
| s33.c1 | s33 | expectation | holder_of(role); subscribe(callback). | - |
| s33.c2 | s33 | answer | Holder(name) or None now, and a callback whenever it changes. | - |
| s34.c1 | s34 | expectation | open(role, address) (Notes/Custom input-only); close(). | - |
| s34.c2 | s34 | answer | UnitConnection. | - |
| s34.c3 | s34 | answer | PortBusy \| PortNoPermission \| PortGone. | - |
| s35.c1 | s35 | expectation | ask('Take control of APC64?'); withdraw(). | - |
| s35.c2 | s35 | answer | TAKE when the action is clicked; DISMISSED when closed or withdrawn. | - |
| s36.c1 | s36 | expectation | marker_set() on DAW on, marker_clear() after release, marker_present() at start. | - |
| s36.c2 | s36 | answer | marker_present → bool. | - |
| s37.c1 | s37 | expectation | attach(UnitConnection), send(frames) (identity request, handshake, DAW on, clear frames, DAW off), detach(). | - |
| s37.c2 | s37 | answer | Per frame SENT \| REFUSED; when detached, DROPPED silently. | - |
| s37.c3 | s37 | answer | PortGone propagated when the write fails. | - |
| s38.c1 | s38 | expectation | on_held(HeldUnit: DAW connection, Notes/Custom connections or None); on_released(); run() supervised by session. | - |
| s38.c2 | s38 | answer | on_held → the engine listens and emits a full LedFrame; on_released → clear frames returned and LED output stopped. | - |
| s38.c3 | s38 | answer | An unhandled engine fault surfaces as the run task's exception to the session's supervisor callback. | - |
| s39.c1 | s39 | expectation | identity_request(), handshake_frames(), daw_on(), daw_off(), parse_identity(bytes). | - |
| s39.c2 | s39 | answer | Frame bytes; parse_identity → Identity \| NOT_IDENTITY. | - |
| s40.c1 | s40 | expectation | UnitStatus.on(observation) for presence, consent(source), decline, open_failed(kind), released, stale_marker. | - |
| s40.c2 | s40 | answer | The next UnitStatus. | - |
| s41.c1 | s41 | expectation | call_later(2.0, identity_timeout); call_later(1.0, rescan). | - |
| s41.c2 | s41 | answer | Callback after the delay, unless cancelled. | - |
| s42.c1 | s42 | expectation | HostSurface.handle(SurfaceInput \| FeedbackMessage \| Tick \| LayoutSwap \| LayoutCatalog); ExpressiveRouter.handle(PlayedMidi, view); LedFrame.for_state(state). | - |
| s42.c2 | s42 | answer | An ordered [Effect]: Send, Led, StripBar, Oled, Activity, Play, ScheduleAfter, RequestLayout. | - |
| s43.c1 | s43 | expectation | decode_daw(bytes), decode_midi(bytes), encode(Led \| StripBar), oled_frames(OledText). | - |
| s43.c2 | s43 | answer | [SurfaceInput] / [MidiMessage] / frame bytes; unknown bytes → skipped with a debug log. | - |
| s44.c1 | s44 | expectation | send(frames). | - |
| s44.c2 | s44 | answer | SENT \| REFUSED \| DROPPED (not held, silently). | - |
| s45.c1 | s45 | expectation | send(PortName, MidiMessage); listen(PortName, callback) for feedback ports; subscribe_presence(callback). | - |
| s45.c2 | s45 | answer | send → SENT \| MISSING \| FAILED. | - |
| s45.c3 | s45 | answer | listener receives FeedbackMessages; presence callback on appear/vanish. | - |
| s46.c1 | s46 | expectation | connection.listen(on_bytes, on_gone) for DAW, Notes and Custom. | - |
| s46.c2 | s46 | answer | Byte chunks per role in order on the reader thread; on_gone once. | - |
| s47.c1 | s47 | expectation | append(ActivityEntry); fold(note, aftertouch). | - |
| s47.c2 | s47 | answer | None (fire and forget). | - |
| s48.c1 | s48 | expectation | publish(PlayEvent). | - |
| s48.c2 | s48 | answer | None; never blocks the engine. | - |
| s49.c1 | s49 | expectation | compiled(LayoutId); catalog(); subscribe(callback). | - |
| s49.c2 | s49 | answer | Layout \| None; LayoutCatalog; callback on change. | - |
| s50.c1 | s50 | expectation | intercept(ControlId) on every press. | - |
| s50.c2 | s50 | answer | CAPTURED (the engine runs no binding) \| PASS. | - |
| s51.c1 | s51 | expectation | observe(PlayedMidi note-on, view). | - |
| s51.c2 | s51 | answer | None; consumed only while calibration is active. | - |
| s52.c1 | s52 | expectation | call_later(duration, enqueue Tick). | - |
| s52.c2 | s52 | answer | The Tick is enqueued after the delay. | - |
| s53.c1 | s53 | expectation | nav_put(NavState, positions) on change; nav_get() on hold. | - |
| s53.c2 | s53 | answer | Stored NavState + positions, or None. | - |
| s54.c1 | s54 | expectation | connection.write(bytes) from one queue task. | - |
| s54.c2 | s54 | answer | OK \| PortGone. | - |
| s55.c1 | s55 | expectation | command_of(frame). | - |
| s55.c2 | s55 | answer | SysexCommand \| CHANNEL_MESSAGE \| UNKNOWN_SYSEX. | - |
| s56.c1 | s56 | expectation | policy.allows(command). | - |
| s56.c2 | s56 | answer | True \| False. | - |
| s57.c1 | s57 | expectation | changes(callback); read(LayoutId); write(LayoutId, text) for restore; list(). | - |
| s57.c2 | s57 | answer | (text, ContentHash) \| MISSING; CHANGED/DELETED events. | - |
| s58.c1 | s58 | expectation | compile_text(text, file name, PortCatalog snapshot). | - |
| s58.c2 | s58 | answer | (Layout, warnings) \| [LayoutIssue]. | - |
| s59.c1 | s59 | expectation | save(LayoutId, text, ContentHash); list(LayoutId); read(VersionId). | - |
| s59.c2 | s59 | answer | VersionId; [VersionId] newest first; text \| UNKNOWN. | - |
| s60.c1 | s60 | expectation | register(LayoutId, Layout, warnings); set_issues(LayoutId, issues); mark_deleted(LayoutId). | - |
| s60.c2 | s60 | answer | OK \| DUPLICATE_NAME(other LayoutId). | - |
| s61.c1 | s61 | expectation | swap(LayoutId, Layout) when the active layout's content changed. | - |
| s61.c2 | s61 | answer | OK after a redraw, with toggles kept for unchanged bindings and reset otherwise. | - |
| s62.c1 | s62 | expectation | call_later(0.25, settle(LayoutId)), restarted on each change. | - |
| s62.c2 | s62 | answer | Callback once the writes have been quiet for 250 ms. | - |
| s63.c1 | s63 | expectation | plan_splice(text, TweakRequest); compile_text(new text). | - |
| s63.c2 | s63 | answer | New text (only the target entry inserted, replaced or removed) \| [LayoutIssue]. | - |
| s64.c1 | s64 | expectation | read(LayoutId); write(LayoutId, text). | - |
| s64.c2 | s64 | answer | (text, ContentHash) \| MISSING; write OK. | - |
| s65.c1 | s65 | expectation | listen(PortName, callback); subscription.cancel(). | - |
| s65.c2 | s65 | answer | Incoming MidiMessages until cancelled. | - |
| s66.c1 | s66 | expectation | apply(TweakRequest assignment from the captured message). | - |
| s66.c2 | s66 | answer | SAVED \| STALE \| INVALID. | - |
| s67.c1 | s67 | expectation | calibration_put(Calibration); calibration_get(). | - |
| s67.c2 | s67 | answer | Calibration \| None. | - |
| s68.c1 | s68 | expectation | resolve(layout, nav); elsewhere(layout, control); overview(layout); SURFACE; palette. | - |
| s68.c2 | s68 | answer | SurfaceMeaning (label, binding or empty, reachable, port status), elsewhere list, overview, catalog. | - |
| s69.c1 | s69 | expectation | snapshot(); subscribe(callback). | - |
| s69.c2 | s69 | answer | EngineSnapshot(nav, LedFrame, OledText, view, toggles, bars, routing status, played notes) and change callbacks. | - |
| s70.c1 | s70 | expectation | status(); subscribe(callback). | - |
| s70.c2 | s70 | answer | UnitStatus (holder, taken_by, firmware warning) and change callbacks. | - |
| s71.c1 | s71 | expectation | summaries(); issues(LayoutId); subscribe(callback). | - |
| s71.c2 | s71 | answer | Summaries, [LayoutIssue], 'file deleted, still active' marks, change callbacks. | - |
| s72.c1 | s72 | expectation | current(); status(). | - |
| s72.c2 | s72 | answer | Calibration \| None and CalibrationStatus. | - |
| s73.c1 | s73 | expectation | monotonic(). | - |
| s73.c2 | s73 | answer | Monotonic seconds. | - |
| s74.c1 | s74 | expectation | Constructors of LayoutId, DeviceDecl, Page, Bank, Binding, Action, ValueSource, StripBinding, RoutingRule, Layout; controls and note-name parsing. | - |
| s74.c2 | s74 | answer | A valid value, or DomainInvariantError(field, problem, fix). | - |
| s75.c1 | s75 | expectation | SURFACE lookups, ControlId, MidiMessage, LedState, OledText, UnitView constructors. | - |
| s75.c2 | s75 | answer | Values, or DomainInvariantError. | - |
| s76.c1 | s76 | expectation | start() at lifespan start; release('stop') at lifespan shutdown. | - |
| s76.c2 | s76 | answer | start → observing presence (asks if present; MaybeStuck on a stale marker); release → RELEASED \| NOT_HELD. | - |
| s77.c1 | s77 | expectation | collect(modules). | - |
| s77.c2 | s77 | answer | (policy additions frozenset, routers list); an empty pair in contract 1. | - |
| s78.c1 | s78 | expectation | load(environ, config.local path). | - |
| s78.c2 | s78 | answer | Config(port 5058, layouts dir, state dir, AllowedNetworks, auto_accept False, port stem 'APC64'), or ConfigError naming the key. | - |
| s79.c1 | s79 | expectation | uvicorn.run(app, host='::', port=config.port, lifespan='on'). | documented: uvicorn settings (host, port, lifespan) |
| s79.c2 | s79 | answer | Accepts IPv4 (as IPv4-mapped) and IPv6 clients on the port. | assumption a28 |
| s79.c3 | s79 | answer | On SIGTERM/SIGINT runs lifespan shutdown before exiting. | assumption a7 |
| s80.c1 | s80 | expectation | snd_rawmidi_open(in, out or NULL, 'hw:<card>,0,<sub>', SND_RAWMIDI_NONBLOCK), snd_rawmidi_read/write, snd_rawmidi_close. | documented: ALSA library rawmidi API (snd_rawmidi_open, snd_rawmidi_read, snd_rawmidi_write) |
| s80.c2 | s80 | answer | -EBUSY while another program holds the subdevice → PortBusy. | assumption a3 |
| s80.c3 | s80 | answer | -EACCES without seat permission → PortNoPermission. | assumption a34 |
| s80.c4 | s80 | answer | -ENODEV/-EIO after unplug → PortGone. | assumption a8 |
| s80.c5 | s80 | answer | Subdevices 0, 1 and 3 can be held by one process at once. | assumption a4 |
| s81.c1 | s81 | expectation | Run `amidi -l`; inotify_add_watch('/dev/snd', IN_CREATE\|IN_DELETE). | documented: amidi(1) --list-devices; inotify(7) |
| s81.c2 | s81 | answer | Lines 'IO  hw:<c>,0,<s>  APC64 <Role> (APC64)' parsed into UnitPresence by name stem. | documented: amidi(1) --list-devices |
| s82.c1 | s82 | expectation | SequencerClient('apc64-host'); list_ports; create_port; connect to target/feedback ports; event_output + drain; subscribe to System Announce; query subscribers of APC64 ports; never connect to the APC64 client. | documented: alsa-midi documentation (SequencerClient, list_ports, event_output, subscriptions) |
| s82.c2 | s82 | answer | A missing port raises → MISSING; send errors → FAILED. | assumption a33 |
| s82.c3 | s82 | answer | Subscribers of 'APC64 DAW (APC64)' name the holding client (e.g. 'Chrome', 'Bitwig Studio'). | assumption a2 |
| s82.c4 | s82 | answer | Our own client never appears as a subscriber of any APC64 port. | assumption a14 |
| s83.c1 | s83 | expectation | Write <name>.yaml.tmp, fsync, rename over <name>.yaml; inotify watch CLOSE_WRITE\|MOVED_TO\|MOVED_FROM\|DELETE. | documented: rename(2) atomic replace; inotify(7) |
| s83.c2 | s83 | answer | Events are delivered for local writes on the fuseblk mount. | assumption a10 |
| s84.c1 | s84 | expectation | Create <state>/versions/<layout>/<timestamp>-<hash>.yaml; list the directory; read a file. | documented: Python pathlib/os file APIs |
| s85.c1 | s85 | expectation | Create/remove <state>/holding; atomic write of calibration.json and nav.json. | documented: Python pathlib/os file APIs |
| s86.c1 | s86 | expectation | Run `notify-send -a 'APC64 Host' -A take=Take -w 'Take control of APC64?'`; terminate it to withdraw. | documented: notify-send(1) --action, --wait |
| s86.c2 | s86 | answer | stdout 'take' after a click on Take; exit without output when dismissed. | assumption a11 |
| s87.c1 | s87 | expectation | loop.call_later(delay, cb); time.monotonic(). | documented: Python asyncio event loop call_later; time.monotonic |
| s88.c1 | s88 | expectation | Read config.local lines KEY=VALUE (comments allowed) and os.environ overrides. | documented: Python os.environ and text file reading |
| s89.c1 | s89 | expectation | list(). | - |
| s89.c2 | s89 | answer | [PortInfo] without APC64 ports. | - |
| s90.c1 | s90 | expectation | status(); subscribe(callback). | - |
| s90.c2 | s90 | answer | LearnStatus(mode, selected ControlId?, port?) and change callbacks. | - |
| s91.c1 | s91 | expectation | A click on the notification's 'Take' action, or a dismissal, while an ask is pending — or after it was withdrawn. | - |
| s91.c2 | s91 | answer | Take → the pending ask() resolves TAKE exactly once. | - |
| s91.c3 | s91 | answer | Dismissal → the pending ask() resolves DISMISSED; a click arriving after withdraw() is ignored. | - |

### 7.4 Acceptance by composition
Role: binding — how each §4.2 row recomposes from the design: the seams its behaviour crosses, in order, from where its trigger enters to where its observable leaves, and the artifact whose behaviour decides its outcome. A row is proven by composition — the deciding piece's own test on the row's values, and every seam on its path proven for any input it receives.
| row | path | decided at |
|---|---|---|
| A1 | s5, s32, s81, s40, s35, s86, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A2 | s8, s9, s15, s33, s82, s34, s80, s37, s39, s54, s80, s38, s42, s43, s44, s56, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A3 | s91, s35, s34, s80, s37, s39, s38, s42, s44, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A4 | s8, s9, s15, s40, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A5 | s5, s32, s81, s40, s34, s80, s37, s39, s38, s42, s44, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A6 | s5, s32, s35, s86, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A7 | s8, s9, s15, s34, s80, s35, s86, s40 | `_apc64_host/application/session.py` |
| A8 | s8, s9, s15, s40, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A9 | s8, s9, s15, s33, s82, s34, s80, s40, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A10 | s8, s9, s15, s33, s82, s34, s80, s40, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A11 | s8, s9 | `_apc64_host/presentation/static` |
| A12 | s8, s9, s15, s34, s80, s40, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A13 | s4, s33, s40, s35, s86, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A14 | s8, s9, s15, s34, s80 | `_apc64_host/infrastructure/alsa_rawmidi.py` |
| A15 | s8, s9, s15, s34, s80, s40, s38, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A16 | s8, s9, s16, s42, s45, s82, s44 | `_apc64_host/application/engine.py` |
| A17 | s5, s32, s81, s40, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A18 | s8, s9, s15, s34, s80, s37, s39, s41, s87, s40, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A19 | s8, s9, s15, s34, s80, s37, s3, s39, s40, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A20 | s7, s76, s36, s85, s40, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A21 | s8, s9, s15, s34, s80, s38, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A22 | s2, s10, s15, s34, s80, s38, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A23 | s5, s32, s81, s40, s35, s86, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A24 | s5, s32, s40, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A25 | s8, s9, s15, s38, s37, s39, s54, s80, s34, s36, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A26 | s7, s76, s38, s37, s39, s54, s80, s34 | `_apc64_host/application/session.py` |
| A27 | s3, s46, s38, s40, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A28 | s3, s46, s43, s42, s38, s37, s54, s80, s70, s26, s14, s30 | `_apc64_host/application/session.py` |
| A29 | s8, s9, s15, s40 | `_apc64_host/application/session.py` |
| A30 | s2, s10, s15, s37, s54, s80, s70 | `_apc64_host/application/session.py` |
| A31 | s8, s9, s16, s44, s55, s56, s47, s27, s14, s30 | `_apc64_host/application/outbound_gate.py` |
| A32 | s2, s10, s24 | `_apc64_host/application/outbound_gate.py` |
| A33 | s2, s29, s74 | `_apc64_host/notation` |
| A34 | s2, s29, s74 | `_apc64_host/notation` |
| A35 | s8, s9, s18, s16, s49, s42, s68, s26, s14, s30 | `_apc64_host/domain` |
| A36 | s2, s29, s74 | `_apc64_host/notation` |
| A37 | s8, s9, s15, s38, s49, s42, s43, s44, s56, s54, s80 | `_apc64_host/application/engine.py` |
| A38 | s2, s29, s74 | `_apc64_host/notation` |
| A39 | s2, s29, s74 | `_apc64_host/notation` |
| A40 | s2, s29, s74 | `_apc64_host/notation` |
| A41 | s6, s57, s58, s74, s61, s3, s46, s43, s42, s45, s82 | `_apc64_host/notation` |
| A42 | s6, s57, s58, s60, s71, s26, s14, s30 | `_apc64_host/application/library.py` |
| A43 | s2, s29, s74, s8, s9, s16, s42, s43, s44, s56, s54, s80 | `_apc64_host/domain` |
| A44 | s6, s57, s62, s58, s74, s60, s71, s26, s14, s30 | `_apc64_host/application/layout_pipeline.py` |
| A45 | s2, s29, s74 | `_apc64_host/presentation/cli.py` |
| A46 | s2, s29, s74, s10 | `_apc64_host/presentation/cli.py` |
| A47 | s2, s29, s74 | `_apc64_host/notation` |
| A48 | s2, s29, s74 | `_apc64_host/notation` |
| A49 | s2, s29, s74 | `_apc64_host/domain` |
| A50 | s6, s57, s62, s89, s58, s74, s59, s60, s61, s42, s43, s44, s54, s80, s69, s26, s14, s30 | `_apc64_host/application/layout_pipeline.py` |
| A51 | s6, s57, s62, s58, s61 | `_apc64_host/application/layout_pipeline.py` |
| A52 | s6, s57, s62, s58, s74, s60, s71, s26, s14, s30, s59, s61 | `_apc64_host/application/layout_pipeline.py` |
| A53 | s6, s57, s62 | `_apc64_host/application/layout_pipeline.py` |
| A54 | s8, s9, s17, s59, s57, s83, s6, s58, s61 | `_apc64_host/application/layout_pipeline.py` |
| A55 | s6, s57, s59, s84 | `_apc64_host/infrastructure/version_store.py` |
| A56 | s6, s57, s60, s71, s26, s14, s30 | `_apc64_host/application/layout_pipeline.py` |
| A57 | s2, s10, s17, s58, s74, s60, s71, s26, s14, s30 | `_apc64_host/notation` |
| A58 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A59 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A60 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A61 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A62 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A63 | s3, s46, s43, s75, s42, s45, s82 | `_apc64_host/protocol` |
| A64 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A65 | s3, s46, s43, s42, s69, s26, s14, s30 | `_apc64_host/domain` |
| A66 | s3, s46, s43, s42, s68, s26, s14, s30 | `_apc64_host/domain` |
| A67 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A68 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A69 | s3, s46, s43, s75, s42, s45, s82 | `_apc64_host/protocol` |
| A70 | s8, s9, s16, s42, s45, s82 | `_apc64_host/application/engine.py` |
| A71 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A72 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A73 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A74 | s3, s46, s43, s42, s47, s27, s14, s30 | `_apc64_host/domain` |
| A75 | s3, s46, s43, s42, s45, s82, s44, s56, s54, s80 | `_apc64_host/domain` |
| A76 | s6, s57, s58, s61, s42, s44, s54, s80 | `_apc64_host/domain` |
| A77 | s4, s45, s42, s44, s54, s80, s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A78 | s4, s45, s42, s44, s54, s80, s69, s26, s14, s30 | `_apc64_host/domain` |
| A79 | s4, s45, s42, s44, s54, s80 | `_apc64_host/domain` |
| A80 | s4, s45, s42 | `_apc64_host/domain` |
| A81 | s4, s45, s42, s44, s54, s80 | `_apc64_host/domain` |
| A82 | s4, s45, s42, s3, s46, s43, s42, s44, s54, s80 | `_apc64_host/domain` |
| A83 | s3, s46, s43, s42, s45, s82, s47, s27, s14, s30 | `_apc64_host/application/engine.py` |
| A84 | s2, s10, s17, s89, s82, s58, s74 | `_apc64_host/notation` |
| A85 | s6, s57, s58, s74, s61, s3, s46, s43, s42, s45, s82 | `_apc64_host/notation` |
| A86 | s4, s45, s42, s69, s26, s14, s30 | `_apc64_host/infrastructure/alsa_seq.py` |
| A87 | s3, s46, s43, s42, s68, s26, s14, s30 | `_apc64_host/domain` |
| A88 | s8, s9, s16, s42, s68, s26, s14, s30, s3, s46, s43, s45, s82 | `_apc64_host/domain` |
| A89 | s3, s46, s43, s42, s44, s56, s54, s80 | `_apc64_host/domain` |
| A90 | s3, s46, s43, s42, s44, s56, s54, s80 | `_apc64_host/domain` |
| A91 | s3, s46, s43, s42, s44, s54, s80, s68, s26, s14, s30 | `_apc64_host/domain` |
| A92 | s3, s46, s43, s42, s44, s54, s80 | `_apc64_host/domain` |
| A93 | s3, s46, s43, s42, s68, s26, s14, s30 | `_apc64_host/domain` |
| A94 | s3, s46, s43, s42, s44, s54, s80 | `_apc64_host/domain` |
| A95 | s3, s46, s43, s42, s49, s42, s44, s54, s80 | `_apc64_host/domain` |
| A96 | s3, s46, s43, s42, s52, s44, s54, s80 | `_apc64_host/domain` |
| A97 | s3, s46, s43, s42 | `_apc64_host/domain` |
| A98 | s3, s46, s43, s42, s44, s54, s80 | `_apc64_host/domain` |
| A99 | s8, s9, s16, s49, s42, s43, s44, s54, s80 | `_apc64_host/domain` |
| A100 | s3, s46, s43, s42, s52, s44, s54, s80 | `_apc64_host/domain` |
| A101 | s3, s46, s43, s42, s44, s56, s54, s80 | `_apc64_host/domain` |
| A102 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A103 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A104 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A105 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A106 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A107 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A108 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A109 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A110 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A111 | s3, s46, s43, s42, s45, s82 | `_apc64_host/protocol` |
| A112 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A113 | s3, s46, s43, s42, s6, s57, s58, s61, s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A114 | s3, s34 | `_apc64_host/application/session.py` |
| A115 | s3, s46, s43, s42, s69, s26, s14, s30 | `_apc64_host/domain` |
| A116 | s3, s46, s43, s42, s47, s27, s14, s30 | `_apc64_host/domain` |
| A117 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A118 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A119 | s3, s46, s43, s42, s45, s82 | `_apc64_host/domain` |
| A120 | s3, s46, s43, s42, s45, s82, s47, s27, s14, s30, s48, s28, s31, s2 | `_apc64_host/application/engine.py` |
| A121 | s8, s9, s21, s3, s46, s43, s51, s67, s85, s72, s26, s14, s30 | `_apc64_host/application/calibration.py` |
| A122 | s3, s46, s43, s42, s51, s72, s26, s14, s30 | `_apc64_host/application/calibration.py` |
| A123 | s3, s46, s43, s42, s51, s72, s26, s14, s30 | `_apc64_host/application/calibration.py` |
| A124 | s3, s46, s43, s42, s48, s73, s28, s31, s2 | `_apc64_host/application/play_stream.py` |
| A125 | s3, s46, s43, s42, s48, s28, s31, s2 | `_apc64_host/application/play_stream.py` |
| A126 | s2, s31, s28, s48 | `_apc64_host/application/play_stream.py` |
| A127 | s8, s9, s23 | `_apc64_host/application/activity.py` |
| A128 | s3, s46, s43, s42, s44, s54, s80, s69, s26, s14, s30 | `_apc64_host/domain` |
| A129 | s8, s9, s22, s68 | `_apc64_host/domain` |
| A130 | s8, s9, s16, s42, s69, s26, s14, s30 | `_apc64_host/presentation/ws_hub.py` |
| A131 | s8, s30, s26, s14 | `_apc64_host/presentation/ws_hub.py` |
| A132 | s8, s9, s20, s3, s46, s43, s50, s90, s26, s14, s30 | `_apc64_host/application/learn.py` |
| A133 | s8, s9, s20, s65, s82, s4, s66, s63, s74, s64, s83, s6, s57, s58, s61 | `_apc64_host/application/learn.py` |
| A134 | s8, s9, s20 | `_apc64_host/application/learn.py` |
| A135 | s8, s9, s19, s64, s63, s74, s64, s83, s6, s57, s58, s61, s42, s44, s54, s80 | `_apc64_host/notation` |
| A136 | s8, s9, s19, s64, s63, s74 | `_apc64_host/application/tweaks.py` |
| A137 | s8, s9, s19, s64, s63, s64 | `_apc64_host/notation` |
| A138 | s8, s9, s19, s64, s63, s64, s6, s57, s58, s61 | `_apc64_host/notation` |
| A139 | s8, s9, s19, s64 | `_apc64_host/application/tweaks.py` |
| A140 | s2, s10, s25, s82, s18, s16, s49, s22, s68 | `_apc64_host/presentation/api.py` |
| A141 | s2, s10 | `_apc64_host/presentation/api.py` |
| A142 | s8, s9, s16, s2, s10, s16, s69, s26, s14, s30 | `_apc64_host/application/engine.py` |
| A143 | s1, s11 | `_apc64_host/presentation/network_guard.py` |
| A144 | s1 | `_apc64_host/presentation/network_guard.py` |
| A145 | s1 | `_apc64_host/presentation/network_guard.py` |
| A146 | s1, s11 | `_apc64_host/presentation/network_guard.py` |
| A147 | s1, s11, s16, s42 | `_apc64_host/presentation/network_guard.py` |

## 8 · Downstream
Role: informational — appended at completion.
- **delivery (self-report):** status `pending` · components `[…]` · acceptance_self_run `pending`
- **verification (verdict):** intent_verified_vs_reality `pending` · can_i_deploy `no` · recorded_run `pending`
