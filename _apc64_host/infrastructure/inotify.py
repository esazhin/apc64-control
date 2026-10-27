"""A minimal inotify(7) watch through ctypes libc, shared by the unit locator (/dev/snd) and the layout files.

Non-blocking: read() returns the events pending now (possibly none). fileno() is for select().
"""
import ctypes
import ctypes.util
import os
import struct
from dataclasses import dataclass

IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000
IN_ISDIR = 0x40000000
IN_NONBLOCK = os.O_NONBLOCK
IN_CLOEXEC = os.O_CLOEXEC

_HEADER = struct.Struct("iIII")   # wd, mask, cookie, len
_READ_SIZE = 64 * 1024


@dataclass(frozen=True)
class InotifyEvent:
    mask: int
    name: str
    cookie: int = 0


def parse_events(buffer: bytes) -> list[InotifyEvent]:
    events, offset = [], 0
    while offset + _HEADER.size <= len(buffer):
        _wd, mask, cookie, length = _HEADER.unpack_from(buffer, offset)
        offset += _HEADER.size
        name = buffer[offset:offset + length].split(b"\0", 1)[0].decode("utf-8", "surrogateescape")
        offset += length
        events.append(InotifyEvent(mask, name, cookie))
    return events


def _libc():
    libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
    libc.inotify_init1.argtypes = [ctypes.c_int]
    libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    return libc


class Inotify:
    """One directory watched for `mask`. Raises OSError when inotify is unavailable (callers then poll)."""

    def __init__(self, directory, mask: int, libc=None):
        libc = libc or _libc()
        fd = libc.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
        if fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        if libc.inotify_add_watch(fd, os.fsencode(directory), mask) < 0:
            error = ctypes.get_errno()
            os.close(fd)
            raise OSError(error, f"inotify_add_watch failed for {directory}")
        self._fd = fd

    def fileno(self) -> int:
        return self._fd

    def read(self) -> list[InotifyEvent]:
        try:
            return parse_events(os.read(self._fd, _READ_SIZE))
        except BlockingIOError:
            return []

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1


class Waker:
    """A self-pipe that wakes a select() at once, so stopping a watch thread never waits for its timeout."""

    def __init__(self):
        self._r, self._w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)

    def fileno(self) -> int:
        return self._r

    def wake(self) -> None:
        try:
            os.write(self._w, b"\0")
        except OSError:
            pass

    def close(self) -> None:
        for fd in (self._r, self._w):
            try:
                os.close(fd)
            except OSError:
                pass
