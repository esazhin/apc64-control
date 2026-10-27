import ctypes
import errno
import random
import threading
from types import SimpleNamespace

import pytest

from _apc64_host.application.ports import PortBusy, PortGone, PortNoPermission, UnitConnection, UnitPort
from _apc64_host.domain.layout import UnitPortRole
from _apc64_host.domain.unit_status import Holder
from _apc64_host.infrastructure.alsa_rawmidi import (
    INPUT_BUFFER, SND_RAWMIDI_NONBLOCK, AlsaRawMidi, InputOnlyPort,
)
from _apc64_host.infrastructure.conftest import capture, wait_for

VIEWS = "daw-mode-views-velocity-aftertouch-2026-10-23.log"
ROLE_OF_PORT = {"DAW": UnitPortRole.DAW, "Notes": UnitPortRole.NOTES, "Custom": UnitPortRole.CUSTOM}
ADDRESS = {UnitPortRole.DAW: "hw:4,0,0", UnitPortRole.NOTES: "hw:4,0,1", UnitPortRole.CUSTOM: "hw:4,0,3"}


class FakeLibasound:
    """Stands in for libasound's rawmidi API, with the kernel's exclusivity: a subdevice opened once answers
    -EBUSY to every further open until it is closed. Each opened input handle replays scripted bytes in
    random chunk sizes, then answers -EAGAIN, then (if scripted) the end errno."""

    def __init__(self, open_rc=None, streams=None, end=None, write_rc=None, seed=7):
        self.calls = []
        self.open_rc = dict(open_rc or {})          # address -> negative errno
        self.streams = dict(streams or {})          # address -> bytes the device sends
        self.end = dict(end or {})                  # address -> errno once the bytes are read
        self.write_rc = write_rc
        self.random = random.Random(seed)
        self.held = {}                              # address -> (in handle, out handle)
        self.pending = {}                           # in handle -> bytearray
        self.ended = {}                             # in handle -> errno
        self.written = []
        self.lock = threading.Lock()
        self._next = 0x100

    @staticmethod
    def _value(arg):
        return getattr(arg, "value", arg)

    @staticmethod
    def _target(ref):
        return ref._obj if hasattr(ref, "_obj") else ref.contents

    def snd_rawmidi_open(self, in_ref, out_ref, name, mode):
        name = self._value(name).decode()
        with self.lock:
            self.calls.append(("open", name, "in" if in_ref is not None else None,
                               "out" if out_ref is not None else None, self._value(mode)))
            if name in self.open_rc:
                return self.open_rc[name]
            if name in self.held:
                return -errno.EBUSY
            self._next += 2
            handle_in, handle_out = self._next, self._next + 1
            self._target(in_ref).value = handle_in
            if out_ref is not None:
                self._target(out_ref).value = handle_out
            self.held[name] = (handle_in, handle_out if out_ref is not None else None)
            self.pending[handle_in] = bytearray(self.streams.get(name, b""))
            if name in self.end:
                self.ended[handle_in] = self.end[name]
            return 0

    def snd_rawmidi_nonblock(self, handle, flag):
        self.calls.append(("nonblock", self._value(handle), self._value(flag)))
        return 0

    def snd_rawmidi_read(self, handle, buf, size):
        handle = self._value(handle)
        with self.lock:
            pending = self.pending[handle]
            if not pending:
                return -self.ended[handle] if handle in self.ended else -errno.EAGAIN
            n = min(self.random.randint(1, 17), len(pending), self._value(size))
            chunk = bytes(pending[:n])
            del pending[:n]
        ctypes.memmove(buf, chunk, n)
        return n

    def snd_rawmidi_write(self, handle, data, size):
        size = self._value(size)
        frame = ctypes.string_at(data, size)
        self.calls.append(("write", self._value(handle), frame))
        if self.write_rc is not None:
            answer = self.write_rc.pop(0) if isinstance(self.write_rc, list) else self.write_rc
            if answer is not None:
                return answer if answer < 0 else min(answer, size)
        self.written.append(frame)
        return size

    def snd_rawmidi_close(self, handle):
        handle = self._value(handle)
        with self.lock:
            self.calls.append(("close", handle))
            for name, handles in list(self.held.items()):
                if handle in handles:
                    remaining = tuple(h for h in handles if h not in (handle, None))
                    if remaining:
                        self.held[name] = remaining
                    else:
                        del self.held[name]
        return 0

    # input-buffer sizing through the params API
    def snd_rawmidi_params_malloc(self, ref):
        self._target(ref).value = 0x3333
        return 0

    def snd_rawmidi_params_current(self, handle, params):
        return 0

    def snd_rawmidi_params_set_buffer_size(self, handle, params, size):
        self.calls.append(("input buffer", self._value(handle), self._value(size)))
        return 0

    def snd_rawmidi_params(self, handle, params):
        return 0

    def snd_rawmidi_params_free(self, params):
        return None


def views_streams():
    """The views capture's bytes per subdevice address, in capture order."""
    streams = {}
    for port, data in capture(VIEWS):
        address = ADDRESS[ROLE_OF_PORT[port]]
        streams[address] = streams.get(address, b"") + data
    return streams


def collect(connection):
    chunks, gone = [], []
    connection.listen(chunks.append, lambda: gone.append(True))
    return chunks, gone


def test_open_strings_modes_and_the_input_only_subdevices():
    # T12/s80.c1: 'hw:<card>,0,<sub>' opened non-blocking; DAW in+out, Notes and Custom input only
    lib = FakeLibasound()
    port = AlsaRawMidi(lib=lib, idle_wait=0.0005)
    assert isinstance(port, UnitPort)
    daw = port.open(UnitPortRole.DAW, "hw:4,0,0")
    notes = port.open(UnitPortRole.NOTES, "hw:4,0,1")
    custom = port.open("custom", "hw:4,0,3")
    assert isinstance(daw, UnitConnection)
    opens = [c for c in lib.calls if c[0] == "open"]
    assert opens == [("open", "hw:4,0,0", "in", "out", SND_RAWMIDI_NONBLOCK),
                     ("open", "hw:4,0,1", "in", None, SND_RAWMIDI_NONBLOCK),
                     ("open", "hw:4,0,3", "in", None, SND_RAWMIDI_NONBLOCK)]
    # each input's kernel buffer is raised to 1 MiB (aftertouch and strip bursts while the GIL is busy, a5)
    assert [c[2] for c in lib.calls if c[0] == "input buffer"] == [INPUT_BUFFER] * 3
    # inv11: nothing can be written to Notes or Custom
    for connection in (notes, custom):
        with pytest.raises(InputOnlyPort):
            connection.write(b"\x90\x24\x7f")
    assert not [c for c in lib.calls if c[0] == "write"]
    for connection in (daw, notes, custom):
        connection.close()
        connection.close()   # idempotent
    assert lib.held == {}


def test_chunks_reach_each_roles_listener_unmodified_and_in_order():
    # T12/s3.c1–c2, s46: the views capture replayed in random chunk sizes on three subdevices at once
    streams = views_streams()
    lib = FakeLibasound(streams=streams)
    port = AlsaRawMidi(lib=lib, idle_wait=0.0005)
    received = {}
    connections = []
    for role, address in ADDRESS.items():
        connection = port.open(role, address)
        received[address] = collect(connection)
        connections.append(connection)
    for address, expected in streams.items():
        assert wait_for(lambda: b"".join(received[address][0]) == expected), address
        assert len(received[address][0]) > 1           # it really was chunked
        assert received[address][1] == []              # nothing gone
    for connection in connections:
        connection.close()


def test_a_read_failing_with_eio_or_enodev_calls_on_gone_once_and_stops_that_reader():
    # T12/s3.c3, s80.c4 (a8): unplug while held
    for failure in (errno.EIO, errno.ENODEV):
        lib = FakeLibasound(streams={"hw:4,0,1": b"\x90\x35\x38\xa0\x35\x0a"}, end={"hw:4,0,1": failure})
        port = AlsaRawMidi(lib=lib, idle_wait=0.0005)
        notes = port.open(UnitPortRole.NOTES, "hw:4,0,1")
        chunks, gone = collect(notes)
        assert wait_for(lambda: gone)
        reads_at_gone = len([c for c in lib.calls if c[0] == "read"])
        threading.Event().wait(0.02)
        assert gone == [True]
        assert b"".join(chunks) == b"\x90\x35\x38\xa0\x35\x0a"
        assert len([c for c in lib.calls if c[0] == "read"]) == reads_at_gone   # the reader stopped
        notes.close()


def test_open_errnos_map_to_busy_no_permission_and_gone():
    # T12/s34.c3, s80.c2–c4; the holder comes from the HolderLookup when one is given (s33)
    class Holders:
        def holder_of(self, role):
            return Holder("Bitwig Studio") if role == UnitPortRole.DAW else None

        def subscribe(self, callback): ...

    cases = [(-errno.EBUSY, PortBusy), (-errno.EACCES, PortNoPermission), (-errno.EPERM, PortNoPermission),
             (-errno.ENODEV, PortGone), (-errno.ENOENT, PortGone), (-errno.EIO, PortGone)]
    for rc, error in cases:
        lib = FakeLibasound(open_rc={"hw:4,0,0": rc})
        with pytest.raises(error) as raised:
            AlsaRawMidi(lib=lib, holders=Holders()).open(UnitPortRole.DAW, "hw:4,0,0")
        if error is PortBusy:
            assert raised.value.holder == Holder("Bitwig Studio")
        assert [c[0] for c in lib.calls] == ["open"]
    # without a lookup, Busy names no holder
    with pytest.raises(PortBusy) as raised:
        AlsaRawMidi(lib=FakeLibasound(open_rc={"hw:4,0,1": -errno.EBUSY})).open("notes", "hw:4,0,1")
    assert raised.value.holder is None


def test_while_held_a_second_open_of_the_same_subdevice_is_busy_and_the_holding_keeps_working():
    # T12, A14: Bitwig (or a second host) cannot take a held subdevice; the host's connection is unaffected
    lib = FakeLibasound(streams={"hw:4,0,0": b"\x96\x00\x7f"})
    port = AlsaRawMidi(lib=lib, idle_wait=0.0005)
    daw = port.open(UnitPortRole.DAW, "hw:4,0,0")
    chunks, gone = collect(daw)
    with pytest.raises(PortBusy):
        port.open(UnitPortRole.DAW, "hw:4,0,0")
    with pytest.raises(PortBusy):
        AlsaRawMidi(lib=lib).open(UnitPortRole.DAW, "hw:4,0,0")   # another program, same kernel
    daw.write(b"\x96\x00\x05")
    assert wait_for(lambda: b"".join(chunks) == b"\x96\x00\x7f") and gone == []
    assert lib.written == [b"\x96\x00\x05"]
    daw.close()
    again = port.open(UnitPortRole.DAW, "hw:4,0,0")   # freed on close
    again.close()


def test_write_sends_whole_frames_in_order_retries_partial_writes_and_maps_failures_to_gone():
    # s54.c2: OK | PortGone
    lib = FakeLibasound(write_rc=[3, None, -errno.EAGAIN, None])
    port = AlsaRawMidi(lib=lib, idle_wait=0.0005)
    daw = port.open(UnitPortRole.DAW, "hw:4,0,0")
    frame = bytes.fromhex("F0 47 00 53 1C 00 01 01 F7")
    daw.write(frame)                       # 3 bytes accepted, then the rest
    daw.write(b"\x96\x00\x05")             # -EAGAIN (buffer full), then accepted
    writes = [c[2] for c in lib.calls if c[0] == "write"]
    assert writes == [frame, frame[3:], b"\x96\x00\x05", b"\x96\x00\x05"]
    assert lib.written == [frame[3:], b"\x96\x00\x05"]
    daw.close()

    for rc in (-errno.ENODEV, -errno.EIO):
        lib = FakeLibasound(write_rc=rc)
        daw = AlsaRawMidi(lib=lib).open(UnitPortRole.DAW, "hw:4,0,0")
        with pytest.raises(PortGone):
            daw.write(b"\x96\x00\x05")
        daw.close()

    # a write after close is refused as gone, and never reaches libasound
    lib = FakeLibasound()
    daw = AlsaRawMidi(lib=lib).open(UnitPortRole.DAW, "hw:4,0,0")
    daw.close()
    with pytest.raises(PortGone):
        daw.write(b"\x96\x00\x05")
    assert not [c for c in lib.calls if c[0] == "write"]


def test_a_write_that_never_drains_is_gone_rather_than_a_hang():
    lib = FakeLibasound(write_rc=-errno.EAGAIN)
    daw = AlsaRawMidi(lib=lib, idle_wait=0.0005, write_timeout=0.05).open(UnitPortRole.DAW, "hw:4,0,0")
    with pytest.raises(PortGone):
        daw.write(b"\x96\x00\x05")
    daw.close()


def test_close_stops_the_reader_without_calling_on_gone_and_frees_each_handle_once():
    lib = FakeLibasound()
    daw = AlsaRawMidi(lib=lib, idle_wait=0.0005).open(UnitPortRole.DAW, "hw:4,0,0")
    chunks, gone = collect(daw)
    daw.close()
    reads = len([c for c in lib.calls if c[0] == "read"])
    threading.Event().wait(0.02)
    assert len([c for c in lib.calls if c[0] == "read"]) == reads
    assert gone == [] and sorted(c[0] for c in lib.calls if c[0] == "close") == ["close", "close"]


def test_a_listener_that_raises_does_not_kill_the_reader():
    lib = FakeLibasound(streams={"hw:4,0,1": bytes(range(0x10, 0x50))})
    notes = AlsaRawMidi(lib=lib, idle_wait=0.0005).open(UnitPortRole.NOTES, "hw:4,0,1")
    seen = []

    def flaky(chunk):
        seen.append(chunk)
        if len(seen) == 1:
            raise RuntimeError("listener bug")

    notes.listen(flaky, lambda: None)
    assert wait_for(lambda: b"".join(seen) == bytes(range(0x10, 0x50)))
    with pytest.raises(RuntimeError):
        notes.listen(flaky, lambda: None)   # one listener per connection
    notes.close()


def test_libasound_loader_declares_the_rawmidi_signatures(monkeypatch):
    # the real library is only described here, never opened (hermetic): CDLL is replaced
    from _apc64_host.infrastructure import alsa_rawmidi

    made = {}

    class Fn:
        pass

    class Lib(SimpleNamespace):
        def __getattr__(self, name):
            made[name] = Fn()
            setattr(self, name, made[name])
            return made[name]

    monkeypatch.setattr(alsa_rawmidi.ctypes, "CDLL", lambda name: Lib())
    lib = alsa_rawmidi.load_libasound()
    assert lib.snd_rawmidi_read.restype is ctypes.c_ssize_t and lib.snd_rawmidi_write.restype is ctypes.c_ssize_t
    assert {"snd_rawmidi_open", "snd_rawmidi_nonblock", "snd_rawmidi_close", "snd_rawmidi_params"} <= set(made)
