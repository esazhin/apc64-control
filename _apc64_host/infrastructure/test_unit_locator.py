import os
import subprocess
import threading

from _apc64_host.application.ports import UnitLocator
from _apc64_host.domain.unit_status import UnitPresence
from _apc64_host.infrastructure.conftest import wait_for
from _apc64_host.infrastructure.inotify import IN_CREATE, IN_DELETE, Inotify, InotifyEvent
from _apc64_host.infrastructure.unit_locator import AmidiUnitLocator, parse_amidi_listing

HEADER = "Dir Device    Name\n"
INTERFACE = "IO  hw:1,0,0  USB MIDI Interface MIDI 1\n"


def apc64_on(card: int) -> str:
    """`amidi -l` as recorded in this run (contract p1), with the APC64 on the given card."""
    return "".join(f"IO  hw:{card},0,{sub}  APC64 {role} (APC64)\n"
                   for sub, role in enumerate(("DAW", "Notes", "MIDI", "Custom")))


CARD4 = HEADER + INTERFACE + apc64_on(4)
CARD5 = HEADER + apc64_on(5) + INTERFACE
NO_APC64 = HEADER + INTERFACE   # the listing on this machine with the unit unplugged


class Amidi:
    """A subprocess double for `amidi -l` answering the listings in turn (the last one repeats)."""

    def __init__(self, *listings, returncode=0, error=None):
        self.listings, self.returncode, self.error, self.argv = list(listings), returncode, error, []

    def __call__(self, argv, **kwargs):
        self.argv.append(argv)
        if self.error:
            raise self.error
        text = self.listings.pop(0) if len(self.listings) > 1 else self.listings[0]
        return subprocess.CompletedProcess(argv, self.returncode, stdout=text, stderr="")


class Watch:
    """A /dev/snd inotify double: a pipe makes select() wake, read() hands out the queued events."""

    def __init__(self):
        self._r, self._w = os.pipe()
        self._queue, self._lock = [], threading.Lock()
        self.closed = False

    def push(self, *events):
        with self._lock:
            self._queue.extend(events)
        os.write(self._w, b"x")

    def fileno(self):
        return self._r

    def read(self):
        os.read(self._r, 4096)
        with self._lock:
            events, self._queue = self._queue, []
        return events

    def close(self):
        self.closed = True
        os.close(self._r)
        os.close(self._w)


def test_find_names_each_role_by_address_wherever_the_card_lands():
    # T13, s32.c2, s81.c2, inv17: resolved by name, never by card number
    locator = AmidiUnitLocator(runner=Amidi(CARD4))
    assert isinstance(locator, UnitLocator)
    assert locator.find() == UnitPresence("hw:4,0,0", "hw:4,0,1", "hw:4,0,3")
    assert AmidiUnitLocator(runner=Amidi(CARD5)).find() == UnitPresence("hw:5,0,0", "hw:5,0,1", "hw:5,0,3")
    assert AmidiUnitLocator(runner=Amidi(NO_APC64)).find() is None
    assert Amidi(CARD4)(["amidi", "-l"]).stdout.count("APC64") == 8


def test_amidi_is_run_as_a_listing_only_and_its_failures_read_as_absent():
    amidi = Amidi(CARD4)
    AmidiUnitLocator(runner=amidi).find()
    assert amidi.argv == [["amidi", "-l"]]
    assert AmidiUnitLocator(runner=Amidi(CARD4, returncode=1)).find() is None
    assert AmidiUnitLocator(runner=Amidi(CARD4, error=FileNotFoundError("amidi"))).find() is None
    assert AmidiUnitLocator(runner=Amidi(CARD4, error=subprocess.TimeoutExpired("amidi", 5))).find() is None


def test_a_second_unit_is_not_offered_and_is_counted_as_ignored():
    # d5: only the first unit in port-name order is offered
    listing = HEADER + apc64_on(6) + apc64_on(3)
    assert parse_amidi_listing(listing) == UnitPresence("hw:3,0,0", "hw:3,0,1", "hw:3,0,3", ignored=1)


def test_the_stem_is_configurable_and_a_unit_without_a_daw_port_is_not_offered():
    renamed = HEADER + "IO  hw:7,0,0  Studio DAW (Studio)\nIO  hw:7,0,1  Studio Notes (Studio)\n"
    assert parse_amidi_listing(renamed, stem="Studio") == UnitPresence("hw:7,0,0", "hw:7,0,1", None)
    assert parse_amidi_listing(HEADER + "IO  hw:4,0,1  APC64 Notes (APC64)\n") is None
    assert parse_amidi_listing("") is None


def test_midi_node_events_rescan_and_notify_once_per_change_and_other_nodes_are_ignored():
    # T13, s5.c1–c3, inv16: unplug, replug on another card; one notification per change
    amidi = Amidi(CARD4, NO_APC64, CARD5, CARD5)
    locator = AmidiUnitLocator(runner=amidi, watch_factory=lambda *a: Watch())
    seen = []
    locator.subscribe(seen.append)
    locator.prime()                                                    # start-up scan: no notification
    assert seen == []
    calls = len(amidi.argv)
    locator.handle_events([InotifyEvent(IN_CREATE, "pcmC3D0p"), InotifyEvent(IN_DELETE, "controlC4")])
    assert len(amidi.argv) == calls and seen == []                      # s5.c3: not a MIDI node
    locator.handle_events([InotifyEvent(IN_DELETE, "midiC4D0")])
    assert seen == [None]
    locator.handle_events([InotifyEvent(IN_CREATE, "midiC5D0")])
    assert seen == [None, UnitPresence("hw:5,0,0", "hw:5,0,1", "hw:5,0,3")]
    locator.handle_events([InotifyEvent(IN_CREATE, "midiC5D0")])        # same presence: no second note
    assert len(seen) == 2


def test_the_watch_thread_reacts_to_node_events_and_the_fallback_rescan_catches_what_inotify_missed():
    watch = Watch()
    amidi = Amidi(CARD4)
    delivered = []

    def dispatch(fn, *args):        # the composition root passes loop.call_soon_threadsafe
        delivered.append(threading.current_thread().name)
        fn(*args)

    locator = AmidiUnitLocator(runner=amidi, watch_factory=lambda *a: watch, rescan_interval=0.05,
                               dispatch=dispatch)
    seen = []
    locator.subscribe(seen.append)
    locator.start()
    try:
        amidi.listings = [NO_APC64]
        watch.push(InotifyEvent(IN_DELETE, "midiC4D0"))
        assert wait_for(lambda: seen == [None])
        amidi.listings = [CARD5]                                         # no event at all: the 1 s rescan
        assert wait_for(lambda: seen == [None, UnitPresence("hw:5,0,0", "hw:5,0,1", "hw:5,0,3")])
        assert delivered and all(name == "apc64-unit-locator" for name in delivered)
    finally:
        locator.stop()
    assert watch.closed


def test_without_inotify_the_locator_polls():
    def no_inotify(*args):
        raise OSError("inotify unavailable")

    amidi = Amidi(CARD4)
    locator = AmidiUnitLocator(runner=amidi, watch_factory=no_inotify, rescan_interval=0.02)
    seen = []
    locator.subscribe(seen.append)
    locator.start()
    try:
        amidi.listings = [NO_APC64]
        assert wait_for(lambda: seen == [None])
    finally:
        locator.stop()


def test_the_real_inotify_reports_node_create_and_delete(tmp_path):
    # s81.c1 over a temp directory standing in for /dev/snd (no device is touched)
    watch = Inotify(tmp_path, IN_CREATE | IN_DELETE)
    try:
        (tmp_path / "midiC9D0").write_bytes(b"")
        (tmp_path / "midiC9D0").unlink()
        events = wait_for(watch.read)
        events += watch.read()
        assert [(e.mask & (IN_CREATE | IN_DELETE), e.name) for e in events] == \
               [(IN_CREATE, "midiC9D0"), (IN_DELETE, "midiC9D0")]
    finally:
        watch.close()
