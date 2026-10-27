"""Act as a minimal DAW host for the APC64: enter DAW mode, write the OLED,
light some pads, log everything the device sends, then leave DAW mode.

usage: daw_probe.py LOGFILE [SECONDS]
Handshake and message formats from Bitwig's MIT-licensed APC64 extension.
"""
import signal, sys, time, rtmidi

# Turn SIGTERM into a normal exit so the finally-block always leaves DAW mode.
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

log_path = sys.argv[1]
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 120
api = rtmidi.API_LINUX_ALSA
SYSEX = lambda s: [int(x, 16) for x in s.split()]


def open_pair(needle):
    o, i = rtmidi.MidiOut(api, name="apc64-daw-probe"), rtmidi.MidiIn(api, name="apc64-daw-probe")
    for p in (o, i):
        idx = [k for k, n in enumerate(p.get_ports()) if needle in n]
        p.open_port(idx[0])
    i.ignore_types(sysex=False, timing=True, active_sense=True)
    return o, i


def oled(out, row, text):
    data = [row] + [ord(c) for c in text] + [0]
    out.send_message([0xF0, 0x47, 0x00, 0x53, 0x10, 0x00, len(data)] + data + [0xF7])


daw_out, daw_in = open_pair("APC64 DAW")
listeners = {"DAW": daw_in}
for name in ("Notes", "MIDI", "Custom"):
    listeners[name] = open_pair(f"APC64 {name}")[1]

log = open(log_path, "w", buffering=1)
t0 = time.monotonic()


def make_cb(port):
    def cb(event, _):
        msg, _dt = event
        log.write(f"{time.monotonic() - t0:8.3f} {port:6} " + " ".join(f"{b:02X}" for b in msg) + "\n")
    return cb


for name, p in listeners.items():
    p.set_callback(make_cb(name))

for s in ("F0 47 00 53 1B 00 01 00 F7", "F0 47 00 53 19 00 01 00 F7", "F0 7E 7F 06 01 F7"):
    daw_out.send_message(SYSEX(s))
time.sleep(0.3)
daw_out.send_message(SYSEX("F0 47 00 53 1C 00 01 01 F7"))   # DAW mode on
time.sleep(0.3)
oled(daw_out, 0, "LINUX HOST")
oled(daw_out, 1, "APC64 probe")
for pad, colour in enumerate([5, 9, 13, 21, 37, 45, 49, 53]):  # bottom row, Ableton palette
    daw_out.send_message([0x96, pad, colour])                  # ch 6 = full brightness
log.write("# DAW mode on, OLED written, pads 0-7 lit\n")

try:
    time.sleep(seconds)
finally:
    daw_out.send_message(SYSEX("F0 47 00 53 1C 00 01 00 F7"))  # DAW mode off
    log.write("# DAW mode off\n")
