"""APC64 SysEx (PROTOCOL-SPEC §2–§4, §6): Akai framing, identity, the DAW-mode handshake, pad-mode reports,
OLED text, 7-bit packing, and command_of — the classifier the outbound gate checks every frame with.

Akai frame: F0 47 00 53 <cmd> <len_hi> <len_lo> <data…> F7, length = (len_hi << 7) | len_lo.
"""
from dataclasses import dataclass

from ..domain.effects import UnitView
from ..domain.oled import OLED_WIDTH, OledText
from ..domain.outbound import SysexCommand
from .stream import data_length

AKAI, APC64_PRODUCT = 0x47, 0x53
HEADER = bytes([0xF0, AKAI, 0x00, APC64_PRODUCT])
END = 0xF7
IDENTITY_REQUEST = bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])
KNOWN_FIRMWARE = "1.2.1.6"

OLED, PROJECT_READ, PROJECT_WRITE, GLOBAL_READ, GLOBAL_WRITE = 0x10, 0x13, 0x14, 0x17, 0x18
PAD_MODE, DRUM_FLAG, DAW_MODE = 0x19, 0x1B, 0x1C
_COMMANDS = {
    OLED: SysexCommand.OLED_TEXT, PROJECT_READ: SysexCommand.PROJECT_READ,
    PROJECT_WRITE: SysexCommand.PROJECT_WRITE, GLOBAL_READ: SysexCommand.GLOBAL_READ,
    GLOBAL_WRITE: SysexCommand.GLOBAL_WRITE, PAD_MODE: SysexCommand.PAD_MODE,
    DRUM_FLAG: SysexCommand.DRUM_FLAG, DAW_MODE: SysexCommand.DAW_MODE,
}
# Pad-mode report codes (PROTOCOL-SPEC §4.5; 1 Overview and 5 Drum are [CODE])
VIEW_CODES = {0: UnitView.SESSION, 1: UnitView.OVERVIEW, 2: UnitView.NOTE, 3: UnitView.CHORD, 5: UnitView.DRUM,
              6: UnitView.STEP, 8: UnitView.PROJECT, 9: UnitView.CUSTOM}


def akai_frame(command: int, data: bytes = b"") -> bytes:
    data = bytes(data)
    return HEADER + bytes([command, len(data) >> 7, len(data) & 0x7F]) + data + bytes([END])


def parse_akai(frame: bytes) -> tuple[int, bytes] | None:
    """(command, data) of a well-formed Akai APC64 frame whose length field matches, else None."""
    frame = bytes(frame)
    if len(frame) < 8 or not frame.startswith(HEADER) or frame[-1] != END:
        return None
    length = (frame[5] << 7) | frame[6]
    data = frame[7:-1]
    return (frame[4], data) if len(data) == length else None


# --- DAW-mode session ------------------------------------------------------------------------------------
def handshake_frames() -> tuple[bytes, ...]:
    """What Bitwig's start() sends before DAW mode on: drum flag off, Session pad mode, identity request."""
    return (akai_frame(DRUM_FLAG, b"\x00"), akai_frame(PAD_MODE, b"\x00"), IDENTITY_REQUEST)


def daw_on() -> bytes:
    return akai_frame(DAW_MODE, b"\x01")


def daw_off() -> bytes:
    return akai_frame(DAW_MODE, b"\x00")


def view_report(frame: bytes) -> UnitView | None:
    """The unit's pad-mode report 'F0 47 00 53 19 00 01 <m> F7' → UnitView (unknown codes → None)."""
    parsed = parse_akai(frame)
    if parsed is None or parsed[0] != PAD_MODE or len(parsed[1]) != 1:
        return None
    return VIEW_CODES.get(parsed[1][0])


def encode_view_report(view: UnitView) -> bytes:
    code = next(c for c, v in VIEW_CODES.items() if v is view)
    return akai_frame(PAD_MODE, bytes([code]))


def oled_frames(text: OledText) -> tuple[bytes, bytes]:
    """Both OLED rows, each padded with spaces to 14 characters so a shorter name fully replaces a longer
    one: 'F0 47 00 53 10 00 <n+2> <row> <ascii…> 00 F7' (PROTOCOL-SPEC §6; rows/length [TBD], ≤14 safe)."""
    return tuple(akai_frame(OLED, bytes([row]) + line.ljust(OLED_WIDTH).encode("ascii") + b"\x00")
                 for row, line in enumerate(text.rows))


def parse_oled(frame: bytes) -> tuple[int, str] | None:
    parsed = parse_akai(frame)
    if parsed is None or parsed[0] != OLED or len(parsed[1]) < 2:
        return None
    return parsed[1][0], parsed[1][1:-1].decode("ascii", "replace").rstrip()


# --- identity --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class FirmwareVersion:
    parts: tuple[int, int, int, int]

    def __str__(self) -> str:
        return ".".join(str(p) for p in self.parts)


@dataclass(frozen=True)
class Identity:
    manufacturer: int
    product: int
    firmware: FirmwareVersion
    serial: str

    @property
    def is_apc64(self) -> bool:
        return self.manufacturer == AKAI and self.product == APC64_PRODUCT

    @property
    def firmware_warning(self) -> str | None:
        """Unknown firmware is warned about, never refused (PROTOCOL-SPEC §3)."""
        return None if str(self.firmware) == KNOWN_FIRMWARE else f"untested firmware {self.firmware}"

    @property
    def refusal(self) -> str:
        return f"not an APC64 (product 0x{self.product:02X})"


NOT_IDENTITY = None


def parse_identity(frame: bytes) -> Identity | None:
    """'F0 7E <dev> 06 02 <mfr> <product> 00 19 <fw×4> 00×5 <serial…> 00 F7' → Identity; else NOT_IDENTITY."""
    frame = bytes(frame)
    if len(frame) < 14 or frame[:2] != b"\xf0\x7e" or frame[3:5] != b"\x06\x02" or frame[-1] != END:
        return NOT_IDENTITY
    serial = frame[18:-1].split(b"\x00", 1)[0].decode("ascii", "replace") if len(frame) > 19 else ""
    return Identity(frame[5], frame[6], FirmwareVersion(tuple(frame[9:13])), serial)


def identity_reply(firmware=(1, 2, 1, 6), product=APC64_PRODUCT, serial="000000000000000") -> bytes:
    """An identity reply in this unit's format (fixtures/*.log line 1), for simulators and tests."""
    return (bytes([0xF0, 0x7E, 0x00, 0x06, 0x02, AKAI, product, 0x00, 0x19, *firmware, 0, 0, 0, 0, 0])
            + serial.encode("ascii") + b"\x00\xf7")


# --- the gate's classifier -------------------------------------------------------------------------------
def command_of(frame: bytes) -> SysexCommand:
    """What one outbound frame is. A frame must be exactly one message: one channel message of the right
    length, the identity request, or one well-formed Akai frame. Anything else — several messages in one
    frame, a channel message with a SysEx tail, other manufacturers' SysEx — is UNKNOWN_SYSEX (refused)."""
    frame = bytes(frame)
    if not frame:
        return SysexCommand.UNKNOWN_SYSEX
    status = frame[0]
    if 0x80 <= status <= 0xEF:
        well_formed = len(frame) == data_length(status) + 1 and not any(b & 0x80 for b in frame[1:])
        return SysexCommand.CHANNEL_MESSAGE if well_formed else SysexCommand.UNKNOWN_SYSEX
    if frame == IDENTITY_REQUEST:
        return SysexCommand.IDENTITY_REQUEST
    if status == 0xF0 and frame[-1] == END and not any(b & 0x80 for b in frame[1:-1]):
        parsed = parse_akai(frame)
        if parsed is not None:
            return _COMMANDS.get(parsed[0], SysexCommand.UNKNOWN_SYSEX)
    return SysexCommand.UNKNOWN_SYSEX


# --- 7-bit packing (projects and global settings; contract 2) --------------------------------------------
def pack7(raw: bytes) -> bytes:
    """Groups of 7 bytes → 8: a first byte holding bit 7 of the next 7 (PROTOCOL-SPEC §2)."""
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
