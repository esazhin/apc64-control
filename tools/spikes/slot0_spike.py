"""Spike for contract 2 a1/a2/a3/a4: slot-0 writes while the APC64 is in DAW mode + Custom view.

Backs slot 0 up first, restores it at the end, always sends DAW mode off.
usage: slot0_spike.py TOOLS_DIR OUT_DIR RAWMIDI_NODE
"""
import os, select, sys, threading, time

if len(sys.argv) < 4:
    sys.exit("usage: slot0_spike.py TOOLS_DIR OUT_DIR RAWMIDI_NODE   (the APC64 DAW port's node, e.g. "
             "/dev/snd/midiC<card>D0 with <card> from `amidi -l`)")
sys.path.insert(0, sys.argv[1])
from apc64_project import build_dump, parse_dump, PAD_SIZE  # noqa: E402

OUT = sys.argv[2]
NODE = sys.argv[3]
fd = os.open(NODE, os.O_RDWR | os.O_NONBLOCK)
log = open(os.path.join(OUT, "spike.log"), "w", buffering=1)
t0 = time.monotonic()
sysex_replies, mode = [], [None]
stop = threading.Event()


def note(s):
    line = f"{time.monotonic() - t0:8.3f} {s}"
    log.write(line + "\n"); print(line, flush=True)


def send(b):
    b = bytes(b); off = 0
    while off < len(b):
        try:
            off += os.write(fd, b[off:])
        except BlockingIOError:
            select.select([], [fd], [], 0.05)


def reader():
    buf, in_sx = bytearray(), False
    while not stop.is_set():
        r, _, _ = select.select([fd], [], [], 0.05)
        if not r:
            continue
        try:
            data = os.read(fd, 4096)
        except BlockingIOError:
            continue
        for b in data:
            if b == 0xF8 or b == 0xFE:
                continue
            if b == 0xF0:
                buf, in_sx = bytearray([b]), True
            elif in_sx:
                buf.append(b)
                if b == 0xF7:
                    in_sx = False
                    m = bytes(buf)
                    if m[:5] == bytes([0xF0, 0x47, 0, 0x53, 0x19]):
                        mode[0] = m[7]; note(f"mode report {m[7]}")
                    elif m[:5] == bytes([0xF0, 0x47, 0, 0x53, 0x14]):
                        sysex_replies.append(m); note(f"dump reply {len(m)} bytes")
                    else:
                        note("sysex " + m[:12].hex(" "))
            else:
                if b & 0x80:
                    buf = bytearray([b])
                else:
                    buf.append(b)
                if len(buf) == 3:
                    note("msg " + buf.hex(" ")); buf = bytearray([buf[0]])


def oled(text):
    data = [0] + [ord(c) for c in text[:16]] + [0]
    send([0xF0, 0x47, 0, 0x53, 0x10, 0, len(data)] + data + [0xF7])


def read_slot0(timeout=2.0):
    n = len(sysex_replies)
    send([0xF0, 0x47, 0, 0x53, 0x13, 0, 1, 0, 0xF7])
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if len(sysex_replies) > n:
            return bytearray(parse_dump(sysex_replies[-1])[1])
        time.sleep(0.01)
    raise TimeoutError("no slot-0 reply")


def with_rest(raw, pad_i, rgb):
    r = bytearray(raw); o = pad_i * PAD_SIZE
    r[o + 4:o + 7] = bytes(rgb); return r


def diff(a, b):
    return [(i, a[i], b[i]) for i in range(len(a)) if a[i] != b[i]]


threading.Thread(target=reader, daemon=True).start()
backup = None
try:
    for s in ("F0 47 00 53 1B 00 01 00 F7", "F0 47 00 53 19 00 01 00 F7", "F0 7E 7F 06 01 F7"):
        send(bytes.fromhex(s.replace(" ", "")))
    time.sleep(0.3)
    send(bytes.fromhex("F0470053 1C000101F7".replace(" ", "")))
    time.sleep(0.3)
    oled("SPIKE: CUSTOM?")
    note("DAW on; waiting up to 600 s for Custom view (mode 9)")
    end = time.monotonic() + 600
    while mode[0] != 9 and time.monotonic() < end:
        time.sleep(0.1)
    if mode[0] != 9:
        raise SystemExit("never saw Custom view")
    time.sleep(1.0)

    backup = read_slot0()
    open(os.path.join(OUT, "slot0-backup.bin"), "wb").write(backup)
    note(f"backup taken; pad0 = {backup[:PAD_SIZE].hex(' ')}; pad1 = {backup[PAD_SIZE:2*PAD_SIZE].hex(' ')}")

    # A: one write under DAW mode (a1) + exact read-back with odd RGB values (a3)
    a = with_rest(with_rest(backup, 0, (0xFF, 0x00, 0xFF)), 1, (0x01, 0x7F, 0x80))
    oled("A: BL MAGENTA")
    tw = time.monotonic(); send(build_dump(0, a)); note(f"A written ({(time.monotonic()-tw)*1000:.1f} ms to queue)")
    time.sleep(0.5)
    rb = read_slot0(); d = diff(a, rb)
    note(f"A read-back diff vs intended: {d[:20]} ({len(d)} bytes)")
    time.sleep(8)

    # B: burst of 10 back-to-back writes, no waiting for read-back (a2)
    oled("B: BURST->CYAN")
    colours = [(0xFF, 0, 0), (0, 0xFF, 0), (0, 0, 0xFF)] * 3 + [(0, 0xFF, 0xFF)]
    tw = time.monotonic()
    for c in colours:
        send(build_dump(0, with_rest(backup, 0, c)))
    note(f"B 10 writes queued in {(time.monotonic()-tw)*1000:.1f} ms")
    time.sleep(0.5)
    rb = read_slot0(); d = diff(with_rest(backup, 0, colours[-1]), rb)
    note(f"B final read-back diff vs cyan record: {d[:20]} ({len(d)} bytes)")
    time.sleep(6)

    # C: DAW-port pad LED message while in Custom view (a4)
    oled("C: BL RED?")
    send([0x96, 0x00, 0x05]); note("C sent 96 00 05 (pad 0 full red) on DAW port")
    time.sleep(6)
finally:
    if backup is not None:
        oled("RESTORING")
        send(build_dump(0, backup)); time.sleep(0.5)
        try:
            rb = read_slot0(); d = diff(backup, rb)
            note(f"restore read-back diff vs backup: {len(d)} bytes {d[:10]}")
        except TimeoutError as e:
            note(f"restore read-back failed: {e}")
    send(bytes.fromhex("F04700531C000100F7")); note("DAW off sent")
    time.sleep(0.3); stop.set()
