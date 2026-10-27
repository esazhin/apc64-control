"""APC64 project dump codec + read/write over the DAW port.

Protocol (see PROTOCOL-SPEC.md §8.1):
  read:  F0 47 00 53 13 00 01 <slot> F7
  dump:  F0 47 00 53 14 07 6F <slot> <1006 packed bytes> F7   (also used to write)
Payload is 7-bit packed (8-byte groups, first byte = bit 7 of the next 7) and
unpacks to 880 bytes: 64 pad records x 12, then 8 strip records x 14.
"""
import sys, time

HDR = [0xF0, 0x47, 0x00, 0x53]
CMD_READ, CMD_DUMP = 0x13, 0x14
NUM_SLOTS = 25
PAD_SIZE, STRIP_SIZE, NUM_PADS, NUM_STRIPS = 12, 14, 64, 8
RAW_SIZE = NUM_PADS * PAD_SIZE + NUM_STRIPS * STRIP_SIZE  # 880


def unpack7(packed):
    out = bytearray()
    for g in range(0, len(packed), 8):
        hi = packed[g]
        for i, b in enumerate(packed[g + 1:g + 8]):
            out.append(b | (0x80 if (hi >> i) & 1 else 0))
    return out


def pack7(raw):
    out = bytearray()
    for g in range(0, len(raw), 7):
        chunk = raw[g:g + 7]
        out.append(sum(1 << i for i, b in enumerate(chunk) if b & 0x80))
        out.extend(b & 0x7F for b in chunk)
    return out


def parse_dump(msg):
    msg = bytes(msg)
    if msg[:5] != bytes(HDR + [CMD_DUMP]) or msg[-1] != 0xF7:
        raise ValueError("not an APC64 project dump")
    length = (msg[5] << 7) | msg[6]
    body = msg[7:-1]
    if len(body) != length:
        raise ValueError(f"length field {length} != body {len(body)}")
    slot, raw = body[0], unpack7(body[1:])
    if len(raw) != RAW_SIZE:
        raise ValueError(f"unpacked {len(raw)} bytes, expected {RAW_SIZE}")
    return slot, raw


def build_dump(slot, raw):
    body = bytes([slot]) + bytes(pack7(raw))
    return bytes(HDR + [CMD_DUMP, len(body) >> 7, len(body) & 0x7F]) + body + b"\xF7"


def pad(raw, i):
    return raw[i * PAD_SIZE:(i + 1) * PAD_SIZE]


def strip(raw, i):
    o = NUM_PADS * PAD_SIZE + i * STRIP_SIZE
    return raw[o:o + STRIP_SIZE]


class Device:
    def __init__(self, port_name="APC64 DAW"):
        import rtmidi
        api = rtmidi.API_LINUX_ALSA
        self.out = rtmidi.MidiOut(api, name="apc64-project")
        self.inp = rtmidi.MidiIn(api, name="apc64-project")
        for p in (self.out, self.inp):
            idx = [i for i, n in enumerate(p.get_ports()) if port_name in n]
            if not idx:
                sys.exit(f"{port_name!r} not found")
            p.open_port(idx[0])
        self.inp.ignore_types(sysex=False, timing=True, active_sense=True)

    def _wait_sysex(self, pred, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            m = self.inp.get_message()
            if not m:
                time.sleep(0.005)
            elif m[0] and m[0][0] == 0xF0 and pred(m[0]):
                return m[0]
        return None

    def read(self, slot, timeout=2.0):
        while self.inp.get_message():
            pass
        self.out.send_message(HDR + [CMD_READ, 0x00, 0x01, slot, 0xF7])
        msg = self._wait_sysex(lambda m: m[:5] == HDR + [CMD_DUMP] and m[7] == slot, timeout)
        if msg is None:
            raise TimeoutError(f"no dump for slot {slot}")
        return parse_dump(msg)[1]

    def write(self, slot, raw):
        if not 0 <= slot < NUM_SLOTS:
            raise ValueError("slot out of range")
        self.out.send_message(list(build_dump(slot, raw)))
