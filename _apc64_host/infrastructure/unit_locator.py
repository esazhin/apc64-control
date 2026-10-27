"""UnitLocator: the APC64 found by port name in `amidi -l`, wherever its card lands (contract inv17, s32, s81).

Hotplug: inotify on /dev/snd for create/delete of midiC<n>D<m> nodes triggers a rescan (s5); a rescan also
runs every second as a fallback (and is all there is when inotify is unavailable). Subscribers are told
only when the presence changes, through `dispatch` (default: called on the locator's thread; the
composition root passes loop.call_soon_threadsafe). `amidi -l` only lists devices: it never opens one.
"""
import logging
import select
import subprocess
import threading
from typing import Callable

from ..domain.unit_status import UnitPresence
from .inotify import Waker, IN_CREATE, IN_DELETE, Inotify

DEV_SND = "/dev/snd"
RESCAN_INTERVAL = 1.0
_ROLE_WORDS = {"daw": "daw", "notes": "notes", "custom": "custom"}

log = logging.getLogger(__name__)


def parse_amidi_listing(text: str, stem: str = "APC64") -> UnitPresence | None:
    """'IO  hw:<c>,0,<s>  APC64 <Role> (APC64)' lines → the first unit (by DAW port name, then card) with
    its DAW/Notes/Custom addresses; further units are counted as ignored (d5)."""
    units: dict[str, dict[str, str]] = {}
    names: dict[str, str] = {}
    for line in text.splitlines():
        columns = line.split(None, 2)
        if len(columns) != 3 or not columns[1].startswith("hw:"):
            continue
        device, name = columns[1], columns[2].strip()
        words = name.split()
        if not words or words[0].casefold() != stem.casefold():
            continue
        card = device[3:].split(",", 1)[0]
        role = next((_ROLE_WORDS[w.casefold()] for w in words[1:] if w.casefold() in _ROLE_WORDS), None)
        if role is None:
            continue
        unit = units.setdefault(card, {})
        unit.setdefault(role, device)
        if role == "daw":
            names[card] = name
    offered = sorted((card for card in units if "daw" in units[card]),
                     key=lambda card: (names[card], int(card) if card.isdigit() else card))
    if not offered:
        return None
    first = units[offered[0]]
    return UnitPresence(first["daw"], first.get("notes"), first.get("custom"), ignored=len(offered) - 1)


def _direct(fn, *args):
    fn(*args)


class AmidiUnitLocator:
    def __init__(self, stem: str = "APC64", runner=subprocess.run, watch_factory=Inotify, dev_dir: str = DEV_SND,
                 rescan_interval: float = RESCAN_INTERVAL, dispatch: Callable = _direct):
        self._stem = stem
        self._run = runner
        self._watch_factory = watch_factory
        self._dev_dir = dev_dir
        self._interval = rescan_interval
        self._dispatch = dispatch
        self._subscribers: list[Callable[[UnitPresence | None], None]] = []
        self._last: UnitPresence | None = None
        self._primed = False
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._waker: Waker | None = None

    # --- UnitLocator -----------------------------------------------------------------------------------
    def find(self) -> UnitPresence | None:
        try:
            listing = self._run(["amidi", "-l"], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as error:
            log.warning("unit locator: `amidi -l` failed (%s); the APC64 reads as absent", error)
            return None
        if listing.returncode != 0:
            log.warning("unit locator: `amidi -l` exited %s", listing.returncode)
            return None
        return parse_amidi_listing(listing.stdout, self._stem)

    def subscribe(self, callback: Callable[[UnitPresence | None], None]) -> None:
        self._subscribers.append(callback)

    # --- watching ---------------------------------------------------------------------------------------
    def prime(self) -> UnitPresence | None:
        """The start-up scan: remembers the presence without notifying (the session calls find() itself)."""
        with self._lock:
            self._last, self._primed = self.find(), True
            return self._last

    def rescan(self) -> None:
        presence = self.find()
        with self._lock:
            if self._primed and presence == self._last:
                return
            self._last, self._primed = presence, True
        for callback in list(self._subscribers):
            self._dispatch(callback, presence)

    def handle_events(self, events) -> None:
        """inotify events from /dev/snd: a MIDI node created or deleted means a rescan (s5.c2–c3)."""
        if any(event.name.startswith("midiC") for event in events):
            self.rescan()

    def start(self) -> None:
        if self._thread is not None:
            return
        if not self._primed:
            self.prime()
        self._stopped.clear()
        self._waker = Waker()
        watch = self._open_watch()   # before returning, so no node event after start() is missed
        self._thread = threading.Thread(target=self._watch_loop, args=(watch,), name="apc64-unit-locator",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._waker is not None:
            self._waker.wake()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._thread = None
        if self._waker is not None:
            self._waker.close()
            self._waker = None

    def _open_watch(self):
        try:
            return self._watch_factory(self._dev_dir, IN_CREATE | IN_DELETE)
        except OSError as error:
            log.warning("unit locator: no inotify on %s (%s); polling every %s s", self._dev_dir, error,
                        self._interval)
            return None

    def _watch_loop(self, watch) -> None:
        waker = self._waker
        try:
            while not self._stopped.is_set():
                if watch is None:
                    self._stopped.wait(self._interval)
                    if not self._stopped.is_set():
                        self._safely(self.rescan)
                    continue
                ready, _, _ = select.select([watch, waker], [], [], self._interval)
                if self._stopped.is_set():
                    break
                if watch in ready:
                    events = watch.read()
                    self._safely(self.handle_events, events)
                else:
                    self._safely(self.rescan)
        finally:
            if watch is not None:
                watch.close()

    @staticmethod
    def _safely(fn, *args) -> None:
        try:
            fn(*args)
        except Exception:
            log.exception("unit locator: rescan failed")
