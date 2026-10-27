"""UnitPort over ALSA rawmidi through ctypes libasound (contract §7, s34/s46/s54/s80), in the style of
the author's MOTU 828 mixer (github.com/esazhin/motu-828-mixer), alsa_rawmidi.py.

One exclusive, non-blocking open per subdevice: 'hw:<card>,0,0' (DAW) in and out, 'hw:<card>,0,1' (Notes)
and 'hw:<card>,0,3' (Custom) input only, so nothing can ever be written to them (inv11). The open is
non-blocking so a held subdevice answers -EBUSY at once instead of waiting for it (never fight, inv13).
Each connection reads on its own thread and hands every chunk, unmodified and in order, to its listener on
that thread (s46.c2); the consumer (the engine) moves it onto its queue. A failing read calls on_gone()
once and stops the reader (s3.c3). Only the OutboundGate writes, and only to the DAW connection (a6).
"""
import ctypes
import errno
import logging
import os
import threading
import time
from typing import Callable

from ..application.ports import HolderLookup, PortBusy, PortGone, PortNoPermission
from ..domain.layout import UnitPortRole

SND_RAWMIDI_NONBLOCK = 0x0002
READ_BUFFER = 64 * 1024
# The kernel's rawmidi maximum (as in the MOTU mixer): strip and aftertouch bursts must not overrun while the
# reader thread waits for the GIL (contract a5).
INPUT_BUFFER = 1 << 20
IDLE_WAIT = 0.001        # the reader's pause when nothing is pending (the MOTU mixer's device_pump, proven there)
WRITE_TIMEOUT = 2.0      # a write the device never drains is treated as a gone device, not a hang
_NO_PERMISSION = (errno.EACCES, errno.EPERM)

log = logging.getLogger(__name__)


class InputOnlyPort(Exception):
    """A write to the Notes or Custom subdevice: those are opened input-only and are never written (inv11)."""


def load_libasound():
    lib = ctypes.CDLL("libasound.so.2")
    handle_ref = ctypes.POINTER(ctypes.c_void_p)
    lib.snd_rawmidi_open.argtypes = [handle_ref, handle_ref, ctypes.c_char_p, ctypes.c_int]
    lib.snd_rawmidi_nonblock.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.snd_rawmidi_read.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    lib.snd_rawmidi_read.restype = ctypes.c_ssize_t
    lib.snd_rawmidi_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
    lib.snd_rawmidi_write.restype = ctypes.c_ssize_t
    lib.snd_rawmidi_close.argtypes = [ctypes.c_void_p]
    lib.snd_rawmidi_params_malloc.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    lib.snd_rawmidi_params_current.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.snd_rawmidi_params_set_buffer_size.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    lib.snd_rawmidi_params.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.snd_rawmidi_params_free.argtypes = [ctypes.c_void_p]
    lib.snd_rawmidi_params_free.restype = None
    return lib


def _describe(rc: int) -> str:
    return os.strerror(-rc) if rc < 0 else str(rc)


class AlsaRawMidi:
    """UnitPort: opens one subdevice per call. `holders` (optional) names who holds a busy subdevice."""

    def __init__(self, lib=None, holders: HolderLookup | None = None, idle_wait: float = IDLE_WAIT,
                 write_timeout: float = WRITE_TIMEOUT):
        self._lib = lib
        self._holders = holders
        self._idle_wait = idle_wait
        self._write_timeout = write_timeout

    def _library(self):
        if self._lib is None:
            self._lib = load_libasound()
        return self._lib

    def open(self, role: UnitPortRole, address: str) -> "RawMidiConnection":
        role = UnitPortRole(role)
        lib = self._library()
        writable = role is UnitPortRole.DAW
        handle_in, handle_out = ctypes.c_void_p(), ctypes.c_void_p()
        rc = lib.snd_rawmidi_open(ctypes.byref(handle_in), ctypes.byref(handle_out) if writable else None,
                                  address.encode(), SND_RAWMIDI_NONBLOCK)
        if rc < 0:
            raise self._open_error(role, address, rc)
        self._grow_input_buffer(lib, handle_in)
        return RawMidiConnection(lib, role, address, handle_in, handle_out if writable else None,
                                 self._idle_wait, self._write_timeout)

    def _open_error(self, role: UnitPortRole, address: str, rc: int) -> Exception:
        if rc == -errno.EBUSY:
            holder = None
            if self._holders is not None:
                try:
                    holder = self._holders.holder_of(role)
                except Exception:   # the lookup is a courtesy; Busy stands without a name
                    log.exception("rawmidi: holder lookup failed for %s", role)
            return PortBusy(holder)
        if -rc in _NO_PERMISSION:
            return PortNoPermission(f"{address}: {_describe(rc)}")
        return PortGone(f"{address}: {_describe(rc)}")

    @staticmethod
    def _grow_input_buffer(lib, handle) -> None:
        params = ctypes.c_void_p()
        if lib.snd_rawmidi_params_malloc(ctypes.byref(params)) < 0:
            log.warning("rawmidi: no params object; input buffer left at its default")
            return
        try:
            rc = lib.snd_rawmidi_params_current(handle, params)
            if rc >= 0:
                rc = lib.snd_rawmidi_params_set_buffer_size(handle, params, INPUT_BUFFER)
            if rc >= 0:
                rc = lib.snd_rawmidi_params(handle, params)
            if rc < 0:
                log.warning("rawmidi: input buffer not raised to %d bytes (%s)", INPUT_BUFFER, _describe(rc))
        finally:
            lib.snd_rawmidi_params_free(params)


class RawMidiConnection:
    """One held subdevice (UnitConnection)."""

    def __init__(self, lib, role: UnitPortRole, address: str, handle_in, handle_out, idle_wait: float,
                 write_timeout: float):
        self.role, self.address = role, address
        self._lib = lib
        self._in, self._out = handle_in, handle_out
        self._idle_wait, self._write_timeout = idle_wait, write_timeout
        self._buffer = ctypes.create_string_buffer(READ_BUFFER)
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._closed = False

    # --- input ------------------------------------------------------------------------------------------
    def listen(self, on_bytes: Callable[[bytes], None], on_gone: Callable[[], None]) -> None:
        if self._thread is not None:
            raise RuntimeError(f"{self.role} already has a listener")
        self._thread = threading.Thread(target=self._read_loop, args=(on_bytes, on_gone),
                                        name=f"apc64-rawmidi-{self.role}", daemon=True)
        self._thread.start()

    def _read_loop(self, on_bytes, on_gone) -> None:
        while not self._stopped.is_set():
            n = self._lib.snd_rawmidi_read(self._in, self._buffer, READ_BUFFER)
            if n > 0:
                try:
                    on_bytes(self._buffer.raw[:n])
                except Exception:   # a listener bug must not end the holding's input
                    log.exception("rawmidi %s: listener failed", self.role)
            elif n == 0 or n == -errno.EAGAIN:
                time.sleep(self._idle_wait)
            else:
                if self._stopped.is_set():   # closed underneath the read: not a loss of the device
                    return
                log.warning("rawmidi %s (%s): read failed (%s); the subdevice is gone",
                            self.role, self.address, _describe(n))
                self._stopped.set()
                try:
                    on_gone()
                except Exception:
                    log.exception("rawmidi %s: on_gone failed", self.role)
                return

    # --- output (DAW only, from the OutboundGate) ---------------------------------------------------------
    def write(self, data: bytes) -> None:
        if self._out is None:
            raise InputOnlyPort(f"{self.role} is input-only and is never written")
        data = bytes(data)
        with self._write_lock:
            if self._closed:
                raise PortGone(f"{self.address}: closed")
            deadline = time.monotonic() + self._write_timeout
            sent = 0
            while sent < len(data):
                rest = data[sent:]
                n = self._lib.snd_rawmidi_write(self._out, rest, len(rest))
                if n > 0:
                    sent += n
                elif n == 0 or n == -errno.EAGAIN:
                    if time.monotonic() > deadline:
                        raise PortGone(f"{self.address}: write not drained in {self._write_timeout} s")
                    time.sleep(self._idle_wait)
                else:
                    raise PortGone(f"{self.address}: write failed ({_describe(n)})")

    # --- release ------------------------------------------------------------------------------------------
    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._stopped.set()
            if self._thread is not None and self._thread is not threading.current_thread():
                self._thread.join(timeout=1.0)
            with self._write_lock:
                self._closed = True
                for handle in (self._in, self._out):
                    if handle is not None:
                        self._lib.snd_rawmidi_close(handle)
