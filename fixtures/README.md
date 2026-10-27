# Test fixtures

Captures of a real APC64 (firmware 1.2.1.6, October 2026) that the hermetic tests and the simulated unit replay.
They are the unit's own MIDI and SysEx output. **The unit's serial number is masked:** the identity replies
carry ASCII `000000000000000` (`30` × 15) where the serial was, same length, so every file still parses.

| file | what it is |
|---|---|
| `apc64-snapshot-2026-10-22.hex` | identity reply + the 0x14 dumps of all 25 project slots, one SysEx message per line |
| `apc64-factory-project.syx` | one project dump (0x14, 1015 bytes) of a factory project |
| `apc64-global-settings-2026-10-22.syx` | the global-settings dump (0x18) |
| `apc64-global-backup-before-write.bin` | the 56 raw global-settings bytes, as backed up before a verified write |
| `daw-mode-*.log` | DAW-mode sessions: `<seconds> <PORT> <hex bytes>` per line (surface presses, strips, Shift, views, velocity, aftertouch) |
| `slot0-under-daw-mode-spike-2026-10-25.log` | a slot-0 read/write check run while in DAW mode (see `NOTES-daw-mode.md`) |
| `aseqdump-*.log` | `aseqdump` output of Custom-mode pad and strip experiments (outside DAW mode) |
| `Boss RC-600.APC64` | a preset file saved by Akai's APC64 Project Editor, the test vector for the `.APC64` format (PROTOCOL-SPEC.md §8.4) |

Protocol details: [PROTOCOL-SPEC.md](../PROTOCOL-SPEC.md) and [NOTES-daw-mode.md](../NOTES-daw-mode.md).
