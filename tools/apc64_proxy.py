"""Logging MIDI proxy: exposes a virtual port named "APC64" (what the Windows
editor looks for) and bridges it to a real APC64 port, logging both directions.

usage: apc64_proxy.py LOGFILE [REAL_PORT_SUBSTRING]   (default "APC64 DAW")
"""
import sys, time, rtmidi

log_path = sys.argv[1]
real_name = sys.argv[2] if len(sys.argv) > 2 else "APC64 DAW"
api = rtmidi.API_LINUX_ALSA
# Wine names ports "client - port" unless that exceeds 31 chars; a long client
# name makes Wine show the bare port name "APC64".
VCLIENT = "APC64 logging proxy virtual device"
log = open(log_path, "a", buffering=1)
t0 = time.monotonic()


def emit(direction, msg):
    hexs = " ".join(f"{b:02X}" for b in msg)
    log.write(f"{time.monotonic() - t0:9.3f} {direction} [{len(msg)}] {hexs}\n")


def find(port_obj, needle):
    for i, n in enumerate(port_obj.get_ports()):
        if needle in n:
            return i, n
    sys.exit(f"real port containing {needle!r} not found: {port_obj.get_ports()}")


real_out = rtmidi.MidiOut(api, name="apc64proxy-real")
real_in = rtmidi.MidiIn(api, name="apc64proxy-real", queue_size_limit=4096)
i, n = find(real_out, real_name); real_out.open_port(i); log.write(f"# real out: {n}\n")
i, n = find(real_in, real_name); real_in.open_port(i); log.write(f"# real in:  {n}\n")

# Virtual side, named the way the editor expects.
v_out = rtmidi.MidiOut(api, name=VCLIENT)
v_out.open_virtual_port("APC64")
v_in = rtmidi.MidiIn(api, name=VCLIENT, queue_size_limit=4096)
v_in.open_virtual_port("APC64")

for p in (real_in, v_in):
    p.ignore_types(sysex=False, timing=True, active_sense=True)


def host_to_dev(event, _):
    msg, _dt = event
    emit("H>D", msg)
    real_out.send_message(msg)


def dev_to_host(event, _):
    msg, _dt = event
    emit("D>H", msg)
    v_out.send_message(msg)


v_in.set_callback(host_to_dev)
real_in.set_callback(dev_to_host)
log.write("# proxy up\n")
print("proxy up", flush=True)
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
