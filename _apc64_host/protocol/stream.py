"""Splits a chunked byte stream (rawmidi reads of any size) into whole MIDI messages."""

REALTIME_FIRST = 0xF8
SYSEX_START, SYSEX_END = 0xF0, 0xF7
_SYSTEM_DATA = {0xF1: 1, 0xF2: 2, 0xF3: 1, 0xF6: 0}


def data_length(status: int) -> int:
    """Data bytes that follow a status byte."""
    if 0x80 <= status <= 0xEF:
        return 1 if 0xC0 <= status <= 0xDF else 2
    return _SYSTEM_DATA.get(status, 0)


class MidiStreamSplitter:
    """feed(chunk) → complete messages, in order. SysEx comes out whole (F0 … F7); running status is
    expanded into full channel messages; realtime bytes (F8–FF) come out on their own, even from inside
    a SysEx; a SysEx cut short by another status byte is dropped; stray data bytes are dropped.

    channel_in_sysex=True (contract 2, a33: the session's SysEx tap): a whole channel message inside a SysEx (a
    1015-byte project dump with B0 5A 01 encoder turns between its USB packets) comes out on its own and the
    SysEx goes on; any other status byte still cuts the SysEx short. The default is contract 1's behaviour."""

    def __init__(self, channel_in_sysex: bool = False):
        self._sysex: bytearray | None = None
        self._status: int | None = None    # running status (channel messages only)
        self._pending = bytearray()
        self._channel_in_sysex = channel_in_sysex
        self._embedded: bytearray | None = None   # a channel message inside the SysEx being read

    def feed(self, chunk: bytes) -> list[bytes]:
        out: list[bytes] = []
        for byte in bytes(chunk):
            if byte >= REALTIME_FIRST:
                out.append(bytes([byte]))
            elif self._sysex is not None:
                if self._embedded is not None and not byte & 0x80:
                    self._embedded.append(byte)
                    if len(self._embedded) == data_length(self._embedded[0]) + 1:
                        out.append(bytes(self._embedded))
                        self._embedded = None
                elif byte == SYSEX_END:
                    self._embedded = None
                    self._sysex.append(byte)
                    out.append(bytes(self._sysex))
                    self._sysex = None
                elif self._channel_in_sysex and 0x80 <= byte <= 0xEF:
                    self._embedded = bytearray([byte])
                elif byte & 0x80:   # interrupted: drop the partial frame and treat the byte as a new status
                    self._sysex = self._embedded = None
                    self._status_byte(byte, out)
                else:
                    self._sysex.append(byte)
            elif byte & 0x80:
                self._status_byte(byte, out)
            elif self._status is not None:
                self._pending.append(byte)
                if len(self._pending) == data_length(self._status) + 1:
                    out.append(bytes(self._pending))
                    self._pending = bytearray([self._status]) if self._status < 0xF0 else bytearray()
                    if self._status >= 0xF0:
                        self._status = None
        return out

    def _status_byte(self, byte: int, out: list[bytes]):
        self._pending = bytearray()
        if byte == SYSEX_START:
            self._sysex, self._status = bytearray([byte]), None
        elif byte == SYSEX_END:
            self._status = None
        elif data_length(byte) == 0:
            out.append(bytes([byte]))
            self._status = None
        else:
            self._status = byte
            self._pending = bytearray([byte])
