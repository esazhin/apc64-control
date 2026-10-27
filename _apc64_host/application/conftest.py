"""Doubles shared by the application tests: a manual clock and recording port doubles (all hermetic)."""
import asyncio

from _apc64_host.application.ports import ChangeKind, PortDirection, PortInfo, SendResult


class ManualClock:
    """Time stands still until the test advances it; due timers fire in order, on the caller's thread."""

    class _Timer:
        def __init__(self, due, callback):
            self.due, self.callback, self.cancelled = due, callback, False

        def cancel(self):
            self.cancelled = True

    def __init__(self, now=1000.0):
        self.now = now
        self.timers = []

    def monotonic(self):
        return self.now

    def call_later(self, seconds, callback):
        timer = self._Timer(self.now + seconds, callback)
        self.timers.append(timer)
        return timer

    def pending(self):
        return [t for t in self.timers if not t.cancelled]

    def advance(self, seconds):
        target = self.now + seconds
        while True:
            due = sorted((t for t in self.timers if not t.cancelled and t.due <= target), key=lambda t: t.due)
            if not due:
                break
            timer = due[0]
            self.timers.remove(timer)
            self.now = max(self.now, timer.due)
            timer.callback()
        self.now = target


class RecordingConnection:
    """A UnitConnection double: records writes, can be told to fail, and lets the test push bytes."""

    def __init__(self, fail_after=None):
        self.written = []
        self.closed = False
        self.on_bytes = self.on_gone = None
        self.fail_after = fail_after

    def listen(self, on_bytes, on_gone):
        self.on_bytes, self.on_gone = on_bytes, on_gone

    def write(self, data):
        from _apc64_host.application.ports import PortGone
        if self.fail_after is not None and len(self.written) >= self.fail_after:
            raise PortGone("unplugged")
        self.written.append(bytes(data))

    def close(self):
        self.closed = True


class RecordingTargets:
    """TargetPorts double: every send recorded; ports listed in `missing` answer MISSING."""

    def __init__(self, missing=()):
        self.sent = []
        self.missing = set(missing)
        self.presence = []

    def send(self, port, message):
        if any(m.casefold() in str(port).casefold() for m in self.missing):
            return SendResult.MISSING
        self.sent.append((str(port), message))
        return SendResult.SENT

    def subscribe_presence(self, callback):
        self.presence.append(callback)


class RecordingFeedback:
    """FeedbackInputs double: listeners per port; deliver() plays a message to them."""

    class _Sub:
        def __init__(self, owner, port, callback):
            self.owner, self.port, self.callback, self.cancelled = owner, port, callback, False

        def cancel(self):
            self.cancelled = True

    def __init__(self):
        self.subs = []

    def listen(self, port, callback):
        sub = self._Sub(self, str(port), callback)
        self.subs.append(sub)
        return sub

    def active(self):
        return [s for s in self.subs if not s.cancelled]

    def deliver(self, port, message):
        for sub in self.active():
            if sub.port.casefold() == str(port).casefold():
                sub.callback(message)


class Catalog:
    def __init__(self, *names):
        self.names = list(names)

    def list(self):
        return [PortInfo(n, PortDirection.BOTH) for n in self.names]


class MemorySource:
    """LayoutSource double over a dict; write() emits CHANGED like the real watch."""

    def __init__(self, files=None, emit_on_write=True):
        from _apc64_host.domain.layout import ContentHash
        self._hash = ContentHash.of
        self.files = dict(files or {})
        self.callbacks = []
        self.writes = []
        self.emit_on_write = emit_on_write

    def list(self):
        from _apc64_host.domain.layout import LayoutId
        return sorted(LayoutId(k) for k in self.files)

    def read(self, layout):
        text = self.files.get(str(layout))
        return None if text is None else (text, self._hash(text))

    def write(self, layout, text):
        self.files[str(layout)] = text
        self.writes.append((str(layout), text))
        if self.emit_on_write:
            self.emit(layout, ChangeKind.CHANGED)

    def changes(self, callback):
        self.callbacks.append(callback)

    def emit(self, layout, kind=ChangeKind.CHANGED):
        from _apc64_host.domain.layout import LayoutId
        for callback in list(self.callbacks):
            callback(LayoutId(layout), kind)


class MemoryStore:
    """StateStore double."""

    def __init__(self, marker=False, nav=None, calibration=None):
        self.marker = marker
        self.nav = nav
        self.calibration = calibration
        self.marker_log = []
        self.nav_puts = []

    def marker_set(self):
        self.marker = True
        self.marker_log.append("set")

    def marker_clear(self):
        self.marker = False
        self.marker_log.append("clear")

    def marker_present(self):
        return self.marker

    def calibration_get(self):
        return self.calibration

    def calibration_put(self, calibration):
        self.calibration = calibration

    def nav_get(self):
        return self.nav

    def nav_put(self, nav, positions):
        self.nav = (nav, dict(positions))
        self.nav_puts.append(nav)


def run(coro):
    """Runs one coroutine on a fresh loop (the suite has no async plugin)."""
    return asyncio.run(coro)
