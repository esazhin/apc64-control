"""Build/parse pairs for the unit-memory SysEx (PROTOCOL-SPEC §8; contract §7.1: inverse pairs co-located).

  project read   F0 47 00 53 13 00 01 <slot> F7
  project dump   F0 47 00 53 14 07 6F <slot> <1006 packed> F7   (the reply, and the write)
  global read    F0 47 00 53 17 00 00 F7
  global dump    F0 47 00 53 18 00 40 <64 packed> F7            (the reply, and the write)
  view request   F0 47 00 53 19 00 01 <mode> F7                 (9 = Custom)

The payloads are 7-bit packed: groups of 7 raw bytes become 8, the first holding bit 7 of the next seven.
This is the codec knowledge of tools/apc64_project.py, ported (the service never calls tools/, contract §2.5).
"""
from dataclasses import dataclass

from _apc64_host.domain.effects import UnitView

from .memory import Slot
from .records import GLOBAL_SIZE, PROJECT_SIZE, GlobalSettings, ProjectRecord

HEADER = bytes([0xF0, 0x47, 0x00, 0x53])
END = 0xF7
PROJECT_READ, PROJECT_DUMP, GLOBAL_READ, GLOBAL_DUMP, PAD_MODE = 0x13, 0x14, 0x17, 0x18, 0x19
VIEW_CODE = {UnitView.SESSION: 0, UnitView.OVERVIEW: 1, UnitView.NOTE: 2, UnitView.CHORD: 3, UnitView.DRUM: 5,
             UnitView.STEP: 6, UnitView.PROJECT: 8, UnitView.CUSTOM: 9}
PROJECT_FRAME_SIZE = 1015


def pack7(raw: bytes) -> bytes:
    out = bytearray()
    for start in range(0, len(raw), 7):
        group = raw[start:start + 7]
        out.append(sum(1 << i for i, b in enumerate(group) if b & 0x80))
        out += bytes(b & 0x7F for b in group)
    return bytes(out)


def unpack7(packed: bytes) -> bytes:
    out = bytearray()
    for start in range(0, len(packed), 8):
        high, group = packed[start], packed[start + 1:start + 8]
        out += bytes(b | (0x80 if (high >> i) & 1 else 0) for i, b in enumerate(group))
    return bytes(out)


def _frame(command: int, data: bytes) -> bytes:
    return HEADER + bytes([command, len(data) >> 7, len(data) & 0x7F]) + bytes(data) + bytes([END])


def _data(frame: bytes, command: int) -> bytes | None:
    """The data of a well-formed Akai frame of `command` whose length field matches, else None."""
    frame = bytes(frame)
    if len(frame) < 8 or frame[:4] != HEADER or frame[4] != command or frame[-1] != END:
        return None
    data = frame[7:-1]
    return data if ((frame[5] << 7) | frame[6]) == len(data) else None


@dataclass(frozen=True)
class Malformed:
    """A reply that is not a whole record (contract d66, s7.c2): what came, and how long it unpacked to."""
    received: int
    expected: int
    reason: str = ""

    def text(self, what: str) -> str:
        """'slot 7 read returned 700 bytes, expected 880' (A51)."""
        return f"{what} read returned {self.received} bytes, expected {self.expected}"


# --- projects --------------------------------------------------------------------------------------------
def project_read_frame(slot: Slot) -> bytes:
    return _frame(PROJECT_READ, bytes([Slot(slot)]))


def project_write_frame(slot: Slot, record: ProjectRecord) -> bytes:
    """The 0x14 dump that writes `record` to `slot` (1015 bytes)."""
    return _frame(PROJECT_DUMP, bytes([Slot(slot)]) + pack7(record.to_raw()))


def dump_slot(frame: bytes) -> int | None:
    """The slot a 0x14 frame names, or None when the frame is not a project dump."""
    data = _data(frame, PROJECT_DUMP)
    return data[0] if data else None


def parse_project_dump(frame: bytes) -> tuple[Slot, ProjectRecord] | Malformed:
    """(slot, record), or Malformed with the unpacked length (A51's 700 of 880)."""
    frame = bytes(frame)
    data = _data(frame, PROJECT_DUMP)
    if data is None:
        # a frame cut short or mislabelled: report what its body would unpack to
        body = frame[8:-1] if frame[:4] == HEADER and len(frame) > 9 else b""
        return Malformed(len(unpack7(body)), PROJECT_SIZE, "not a whole project dump")
    if not data or data[0] > 24:
        return Malformed(0, PROJECT_SIZE, "no slot")
    raw = unpack7(data[1:])
    if len(raw) != PROJECT_SIZE:
        return Malformed(len(raw), PROJECT_SIZE)
    return Slot(data[0]), ProjectRecord(raw)


# --- global settings -------------------------------------------------------------------------------------
def global_read_frame() -> bytes:
    return _frame(GLOBAL_READ, b"")


def global_write_frame(settings: GlobalSettings) -> bytes:
    return _frame(GLOBAL_DUMP, pack7(settings.to_raw()))


def parse_global_dump(frame: bytes) -> GlobalSettings | Malformed:
    data = _data(frame, GLOBAL_DUMP)
    if data is None:
        return Malformed(0, GLOBAL_SIZE, "not a global-settings dump")
    raw = unpack7(data)
    if len(raw) != GLOBAL_SIZE:
        return Malformed(len(raw), GLOBAL_SIZE)
    return GlobalSettings(raw)


# --- the view request ------------------------------------------------------------------------------------
def view_request_frame(view: UnitView = UnitView.CUSTOM) -> bytes:
    """Ask the unit for a pad mode (s10.c7: F0 47 00 53 19 00 01 09 F7 for Custom)."""
    return _frame(PAD_MODE, bytes([VIEW_CODE[view]]))
