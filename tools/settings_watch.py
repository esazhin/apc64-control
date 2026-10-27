"""Poll the APC64 global settings (cmd 0x17/0x18) and the live project (slot 0)
and log every byte that changes, so on-device settings can be mapped to bytes.

usage: settings_watch.py LOGFILE [SECONDS]
"""
import signal, sys, time
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from apc64_project import Device, unpack7, NUM_PADS, PAD_SIZE, STRIP_SIZE

signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
log_path = sys.argv[1]
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 600
GLOBAL_REQ = [0xF0, 0x47, 0x00, 0x53, 0x17, 0x00, 0x00, 0xF7]

dev = Device()
log = open(log_path, "w", buffering=1)
t0 = time.monotonic()


def read_global(timeout=1.0):
    while dev.inp.get_message():
        pass
    dev.out.send_message(GLOBAL_REQ)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        m = dev.inp.get_message()
        if m and m[0][:5] == [0xF0, 0x47, 0x00, 0x53, 0x18]:
            return bytes(unpack7(m[0][7:-1]))
        if not m:
            time.sleep(0.005)
    return None


def where(offset):
    if offset < NUM_PADS * PAD_SIZE:
        return f"pad {offset // PAD_SIZE + 1} b{offset % PAD_SIZE}"
    o = offset - NUM_PADS * PAD_SIZE
    return f"strip {o // STRIP_SIZE + 1} b{o % STRIP_SIZE}"


def diff(name, old, new, label=lambda i: f"b{i}"):
    for i, (a, b) in enumerate(zip(old, new)):
        if a != b:
            log.write(f"{time.monotonic() - t0:8.2f} {name:7} {label(i):16} {a:3} -> {b:3}   (0x{a:02x} -> 0x{b:02x})\n")


g, p = read_global(), bytes(dev.read(0))
log.write("# start global: " + g.hex(" ") + "\n")
try:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        time.sleep(0.4)
        g2 = read_global()
        if g2 and g2 != g:
            diff("GLOBAL", g, g2)
            g = g2
        try:
            p2 = bytes(dev.read(0, timeout=1.0))
        except TimeoutError:
            continue
        if p2 != p:
            diff("PROJECT", p, p2, where)
            p = p2
finally:
    log.write("# end global: " + g.hex(" ") + "\n")
