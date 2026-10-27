"""A simulated APC64 for hermetic runs (contract §7, T18): UnitPort, UnitLocator and HolderLookup in one fake
that speaks only what the fixtures show.

Unit → host: the identity reply of fixtures/*.log line 1 (answering the identity request, nothing else is
answered: the captures show no reply to the handshake, DAW mode on/off, LEDs or OLED), surface input in the
exact wire form of the captures (surface_map.encode_input), view reports, Notes/Custom played MIDI, and whole
captures replayed in order. Host → unit: every written frame is recorded and classified with command_of; the
fake tracks DAW mode, the OLED rows and the LEDs, and lists any project/global read or write as a hazard.

Scriptable faults: a holder per role (busy), no permission, unplug/replug (on_gone once per open connection,
presence changes, DAW mode lost), a silent unit (no identity reply), another product or firmware.

Contract 2 (T12): the unit's memory. Slots 0–24 (880 raw bytes each; slot 0 is the live edit buffer) and the
56-byte global block start as the captured snapshot (fixtures/apc64-snapshot-2026-10-22.hex and
apc64-global-settings-2026-10-22.syx). A 0x13 read of slot 0–24 is answered with the 1015-byte 0x14 dump, slots
25+ stay silent; a 0x14 write stores the slot (slot 0 also marks the project unsaved); 0x17/0x18 read and write
the global block. Memory faults: no reply, a short dump, a read-back mismatch, an unplug mid-write, replies cut
into chunks with other messages between them. On-unit actions for the "the user switches or saves projects
mid-session" path (§2.7 a5/q9): load_project(n) and save_project(n), each with its Project-view report.
A pad-mode request (0x19) is answered with a view report only when report_view_requests is set (contract 1's
handshake asks for Session view and the captures show no answer).

The fake is the UnitPort and the UnitLocator; `holder_lookup` is its HolderLookup.
Delivery is synchronous by default (the caller's thread); threaded=True gives each connection a reader
thread like the rawmidi adapter, preserving order per connection.
"""
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..application.ports import PortBusy, PortGone, PortNoPermission
from ..domain.controls import ControlId, Strip
from ..domain.effects import EncoderTurn, Press, Release, StripMove, SurfaceInput, UnitView, ViewReport
from ..domain.layout import UnitPortRole
from ..domain.midi import MidiMessage
from ..domain.outbound import HAZARD_TEXT, SysexCommand
from ..domain.unit_status import Holder, UnitPresence
from ..protocol import midi_codec, sysex
from ..protocol.surface_map import STRIP_COLOUR_CC, STRIP_MODE_CC, encode_input
from .alsa_rawmidi import InputOnlyPort

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
PORT_ROLES = {"DAW": UnitPortRole.DAW, "Notes": UnitPortRole.NOTES, "Custom": UnitPortRole.CUSTOM}
SUBDEVICE = {UnitPortRole.DAW: 0, UnitPortRole.NOTES: 1, UnitPortRole.CUSTOM: 3}
HAZARDS = frozenset(HAZARD_TEXT) - {SysexCommand.UNKNOWN_SYSEX}


def load_capture(name: str) -> list[tuple[str, bytes]]:
    """A fixture capture as (port, bytes) per line: '<seconds> <PORT> <hex bytes…>'; comments skipped."""
    lines = []
    for line in (FIXTURES / name).read_text().splitlines():
        parts = line.split()
        if len(parts) < 3 or line.lstrip().startswith("#"):
            continue
        lines.append((parts[1], bytes(int(h, 16) for h in parts[2:])))
    return lines


PROJECT_SIZE, GLOBAL_SIZE, SLOT_COUNT = 880, 56, 25


def fixture_slots() -> list[bytes]:
    """Slots 0–24 as raw 880-byte records, from the captured full snapshot."""
    slots = []
    for line in (FIXTURES / "apc64-snapshot-2026-10-22.hex").read_text().splitlines():
        if line.startswith("F0 47 00 53 14"):
            frame = bytes.fromhex(line)
            slots.append(sysex.unpack7(frame[8:-1]))
    if len(slots) != SLOT_COUNT or any(len(raw) != PROJECT_SIZE for raw in slots):
        raise ValueError("the snapshot fixture does not hold 25 whole slots")
    return slots


def fixture_globals() -> bytes:
    """The global-settings block as 56 raw bytes, from the captured dump."""
    frame = (FIXTURES / "apc64-global-settings-2026-10-22.syx").read_bytes()
    raw = sysex.unpack7(frame[7:-1])
    if len(raw) != GLOBAL_SIZE:
        raise ValueError("the global-settings fixture is not a whole block")
    return raw


def project_dump(slot: int, raw: bytes) -> bytes:
    """F0 47 00 53 14 07 6F <slot> <packed> F7 (the read reply, and the write)."""
    return sysex.akai_frame(sysex.PROJECT_WRITE, bytes([slot]) + sysex.pack7(raw))


def global_dump(raw: bytes) -> bytes:
    return sysex.akai_frame(sysex.GLOBAL_WRITE, sysex.pack7(raw))


@dataclass
class MemoryFaults:
    """Scriptable memory faults (contract §3.5: no reply, short dump, read-back mismatch, unplug mid-write)."""
    no_reply: bool = False                                      # no read is answered
    silent_slots: set = field(default_factory=set)              # these slots' reads are not answered
    silent_globals: bool = False
    short_dump: int | None = None                               # replies carry only this many raw bytes
    mismatch: dict = field(default_factory=dict)                # slot → (offset, value) the unit stores instead
    unplug_on_write: int | None = None                          # the unit goes away while this slot is written
    chunks: int = 1                                             # replies arrive cut into this many chunks …
    between: bytes = b""                                        # … with these bytes between the chunks


def fixture_identity_reply() -> bytes:
    """The identity reply as the captured unit sent it, its serial masked (fixtures/daw-mode-views-…-2026-10-23.log
    line 1)."""
    return load_capture("daw-mode-views-velocity-aftertouch-2026-10-23.log")[0][1]


class SimulatedConnection:
    """One held subdevice of the simulated unit (UnitConnection)."""

    def __init__(self, unit: "SimulatedApc64", role: UnitPortRole, address: str, threaded: bool):
        self.unit, self.role, self.address = unit, role, address
        self.closed = False
        self.gone = False
        self._on_bytes: Callable[[bytes], None] | None = None
        self._on_gone: Callable[[], None] | None = None
        self._backlog: list[bytes] = []
        self._queue: queue.Queue | None = queue.Queue() if threaded else None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def listen(self, on_bytes: Callable[[bytes], None], on_gone: Callable[[], None]) -> None:
        if self._on_bytes is not None:
            raise RuntimeError(f"{self.role} already has a listener")
        with self._lock:
            self._on_bytes, self._on_gone = on_bytes, on_gone
            backlog, self._backlog = self._backlog, []
        if self._queue is not None:
            self._thread = threading.Thread(target=self._pump, name=f"apc64-sim-{self.role}", daemon=True)
            self._thread.start()
        for chunk in backlog:
            self._deliver(chunk)

    def write(self, data: bytes) -> None:
        if self.role is not UnitPortRole.DAW:
            raise InputOnlyPort(f"{self.role} is input-only and is never written")
        if self.closed or self.gone:
            raise PortGone(f"{self.address}: {'gone' if self.gone else 'closed'}")
        try:
            self.unit._received(bytes(data))
        except _UnpluggedMidWrite as cut:
            self.unit._cut_off()
            raise PortGone(f"{self.address}: unplugged while slot {cut.slot} was written") from None

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.unit._closed(self)
        if self._queue is not None:
            self._queue.put(None)
            if self._thread is not None and self._thread is not threading.current_thread():
                self._thread.join(timeout=2.0)

    # --- unit side ----------------------------------------------------------------------------------------
    def _deliver(self, chunk: bytes) -> None:
        if self.closed or self.gone:
            return
        with self._lock:
            if self._on_bytes is None:   # nothing listens yet: the bytes wait, as in a kernel buffer
                self._backlog.append(chunk)
                return
        if self._queue is not None:
            self._queue.put(("bytes", chunk))
        else:
            self._on_bytes(chunk)

    def _lose(self) -> None:
        if self.gone or self.closed:
            return
        self.gone = True
        if self._on_gone is None:
            return
        if self._queue is not None:
            self._queue.put(("gone", None))
        else:
            self._on_gone()

    def _report_lost(self) -> None:
        """on_gone for a connection already marked gone (an unplug mid-write)."""
        if self.closed or self._on_gone is None:
            return
        if self._queue is not None:
            self._queue.put(("gone", None))
        else:
            self._on_gone()

    def _pump(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            kind, chunk = item
            if kind == "gone":
                self._on_gone()
                return
            if not self.closed:
                self._on_bytes(chunk)


class SimulatedApc64:
    def __init__(self, card: int = 4, present: bool = True, product: int = sysex.APC64_PRODUCT,
                 firmware: tuple[int, int, int, int] = (1, 2, 1, 6), silent: bool = False,
                 threaded: bool = False):
        self.card = card
        self.present = present
        self.product, self.firmware, self.silent = product, firmware, silent
        self.threaded = threaded
        self.holders: dict[UnitPortRole, Holder | None] = {role: None for role in UnitPortRole}
        self.busy_roles: set[UnitPortRole] = set()
        self.no_permission = False
        self.connections: dict[UnitPortRole, SimulatedConnection] = {}
        self.opened: list[tuple[UnitPortRole, str]] = []
        self.written: list[bytes] = []
        self.commands: list[SysexCommand] = []
        self.hazards: list[bytes] = []
        self.daw_mode = False
        self.oled: dict[int, str] = {}
        self.leds: dict[tuple[int, int], int] = {}      # (status kind, note or CC) → last value written
        self.bends: dict[int, int] = {}                  # strip channel → last 14-bit position
        # memory (contract 2)
        self.slots: list[bytes] = fixture_slots()
        self.global_block: bytes = fixture_globals()
        self.faults = MemoryFaults()
        self.memory_log: list[tuple[str, int | None]] = []   # ('read'|'write'|'read_globals'|…, slot)
        self.loaded_project: int = 1                     # the project slot 0 was loaded from
        self.unsaved = False                             # slot 0 differs from the loaded project's slot
        self.current_view = UnitView.SESSION
        self.report_view_requests = False
        self.deferred: list[Callable[[], None]] = []     # what an unplug mid-write still has to tell the host
        self._presence_subscribers: list[Callable[[UnitPresence | None], None]] = []
        self._holder_subscribers: list[Callable[[UnitPortRole, Holder | None], None]] = []
        self._lock = threading.RLock()

    # --- UnitLocator ---------------------------------------------------------------------------------------
    def find(self) -> UnitPresence | None:
        if not self.present:
            return None
        return UnitPresence(*(self.address(role) for role in UnitPortRole))

    def address(self, role: UnitPortRole) -> str:
        return f"hw:{self.card},0,{SUBDEVICE[UnitPortRole(role)]}"

    def subscribe(self, callback: Callable[[UnitPresence | None], None]) -> None:
        self._presence_subscribers.append(callback)

    @property
    def holder_lookup(self) -> "SimulatedHolders":
        """The HolderLookup side (its subscribe takes (role, holder) callbacks)."""
        return SimulatedHolders(self)

    # --- HolderLookup --------------------------------------------------------------------------------------
    def holder_of(self, role: UnitPortRole) -> Holder | None:
        return self.holders.get(UnitPortRole(role))

    # --- UnitPort ------------------------------------------------------------------------------------------
    def open(self, role: UnitPortRole, address: str) -> SimulatedConnection:
        role = UnitPortRole(role)
        with self._lock:
            if not self.present or address != self.address(role):
                raise PortGone(f"{address}: no such device")
            if self.no_permission:
                raise PortNoPermission(f"{address}: permission denied")
            if role in self.busy_roles:
                raise PortBusy(self.holders.get(role))
            if role in self.connections:
                raise PortBusy(None)          # held already (by us): the kernel answers EBUSY
            connection = SimulatedConnection(self, role, address, self.threaded)
            self.connections[role] = connection
            self.opened.append((role, address))
            return connection

    def _closed(self, connection: SimulatedConnection) -> None:
        with self._lock:
            if self.connections.get(connection.role) is connection:
                del self.connections[connection.role]

    # --- faults ---------------------------------------------------------------------------------------------
    def hold(self, role: UnitPortRole, holder: str | None) -> None:
        """Another program takes (holder name, or None for an unnamed holder) a subdevice: opens are busy."""
        role = UnitPortRole(role)
        self.busy_roles.add(role)
        self._set_holder(role, Holder(holder) if holder else None)

    def free(self, role: UnitPortRole) -> None:
        role = UnitPortRole(role)
        self.busy_roles.discard(role)
        self._set_holder(role, None)

    def _set_holder(self, role: UnitPortRole, holder: Holder | None) -> None:
        changed = self.holders.get(role) != holder
        self.holders[role] = holder
        if changed:
            for callback in list(self._holder_subscribers):
                callback(role, holder)

    def unplug(self) -> None:
        with self._lock:
            self.present = False
            self.daw_mode = False
            lost = list(self.connections.values())
            self.connections.clear()          # the device is gone: a replugged unit starts free
        for connection in lost:
            connection._lose()
        self._notify_presence()

    def _cut_off(self) -> None:
        """Unplugged mid-write: every connection is dead now; the host hears of it at complete_unplug()."""
        with self._lock:
            self.present = False
            self.daw_mode = False
            lost = list(self.connections.values())
            self.connections.clear()
        for connection in lost:
            connection.gone = True
        self.deferred.append(lambda: [c._report_lost() for c in lost])
        self.deferred.append(self._notify_presence)

    def plug(self, card: int | None = None) -> None:
        """The unit comes back (possibly on another card), out of DAW mode (PROTOCOL-SPEC §4.7: assumed lost)."""
        with self._lock:
            if card is not None:
                self.card = card
            self.present = True
            self.daw_mode = False
        self._notify_presence()

    def _notify_presence(self) -> None:
        presence = self.find()
        for callback in list(self._presence_subscribers):
            callback(presence)

    # --- unit → host ---------------------------------------------------------------------------------------
    def emit(self, role: UnitPortRole, data: bytes) -> None:
        with self._lock:
            connection = self.connections.get(UnitPortRole(role))
        if connection is not None:
            connection._deliver(bytes(data))

    def send_input(self, event: SurfaceInput) -> None:
        self.emit(UnitPortRole.DAW, encode_input(event))

    def press(self, control: ControlId, velocity: int = 127) -> None:
        self.send_input(Press(control, velocity))

    def release(self, control: ControlId) -> None:
        self.send_input(Release(control))

    def move(self, strip: Strip, value: int) -> None:
        self.send_input(StripMove(strip, value))

    def turn(self, steps: int) -> None:
        self.send_input(EncoderTurn(steps))

    def view(self, view: UnitView) -> None:
        """The unit changes view (its pad-mode report)."""
        self.current_view = UnitView(view)
        self.send_input(ViewReport(view))

    # --- memory, from the unit's side (contract 2) ----------------------------------------------------------
    def slot(self, n: int) -> bytes:
        return self.slots[n]

    def set_slot(self, n: int, raw: bytes) -> None:
        raw = bytes(raw)
        if len(raw) != PROJECT_SIZE:
            raise ValueError(f"a slot holds {PROJECT_SIZE} bytes, not {len(raw)}")
        self.slots[n] = raw

    def set_globals(self, raw: bytes) -> None:
        raw = bytes(raw)
        if len(raw) != GLOBAL_SIZE:
            raise ValueError(f"the global block holds {GLOBAL_SIZE} bytes, not {len(raw)}")
        self.global_block = raw

    def load_project(self, n: int, report: bool = True, back_to: UnitView | None = None) -> None:
        """The user loads project n on the unit: Project view (mode 8 report), slot 0 becomes project n, and the
        unit optionally goes back to a view (§2.7 a5/q9)."""
        if not 1 <= n <= 24:
            raise ValueError("projects are 1–24")
        if report:
            self.view(UnitView.PROJECT)
        self.slots[0] = self.slots[n]
        self.loaded_project, self.unsaved = n, False
        self.memory_log.append(("load_on_unit", n))
        if back_to is not None:
            self.view(back_to)

    def save_project(self, n: int | None = None, report: bool = True, back_to: UnitView | None = None) -> None:
        """The user saves slot 0 on the unit, to the loaded project or to project n, the host not knowing (§2.7)."""
        n = self.loaded_project if n is None else n
        if not 1 <= n <= 24:
            raise ValueError("projects are 1–24")
        if report:
            self.view(UnitView.PROJECT)
        self.slots[n] = self.slots[0]
        self.loaded_project, self.unsaved = n, False
        self.memory_log.append(("save_on_unit", n))
        if back_to is not None:
            self.view(back_to)

    def mismatch_on_write(self, slot: int, offset: int, value: int) -> None:
        """The next writes of `slot` store `value` at raw byte `offset` instead of what was sent (A4)."""
        self.faults.mismatch[slot] = (offset, value)

    def complete_unplug(self) -> None:
        """Tells the host what an unplug mid-write left pending (the port gone, the unit absent)."""
        pending, self.deferred = self.deferred, []
        for fn in pending:
            fn()

    def _reply(self, frame: bytes) -> None:
        chunks = max(1, self.faults.chunks)
        if chunks == 1:
            self.emit(UnitPortRole.DAW, frame)
            return
        size = -(-len(frame) // chunks)
        pieces = [frame[i:i + size] for i in range(0, len(frame), size)]
        for i, piece in enumerate(pieces):
            if i:
                self.emit(UnitPortRole.DAW, self.faults.between)
            self.emit(UnitPortRole.DAW, piece)

    def _shorten(self, raw: bytes) -> bytes:
        return raw if self.faults.short_dump is None else raw[:self.faults.short_dump]

    def _memory(self, command: SysexCommand, frame: bytes) -> None:
        parsed = sysex.parse_akai(frame)
        data = parsed[1] if parsed else b""
        faults = self.faults
        if command is SysexCommand.PROJECT_READ:
            slot = data[0] if data else None
            self.memory_log.append(("read", slot))
            if slot is None or slot >= SLOT_COUNT or faults.no_reply or slot in faults.silent_slots:
                return   # slots 25+ do not answer (PROTOCOL-SPEC §8.1)
            self._reply(project_dump(slot, self._shorten(self.slots[slot])))
        elif command is SysexCommand.PROJECT_WRITE:
            slot = data[0] if data else None
            raw = sysex.unpack7(data[1:]) if data else b""
            self.memory_log.append(("write", slot))
            if slot is None or slot >= SLOT_COUNT or len(raw) != PROJECT_SIZE:
                self.memory_log.append(("malformed_write", slot))
                return
            if faults.unplug_on_write == slot:
                raise _UnpluggedMidWrite(slot)
            if slot in faults.mismatch:
                offset, value = faults.mismatch[slot]
                raw = raw[:offset] + bytes([value]) + raw[offset + 1:]
            self.slots[slot] = raw
            if slot == 0:
                self.unsaved = True
        elif command is SysexCommand.GLOBAL_READ:
            self.memory_log.append(("read_globals", None))
            if faults.no_reply or faults.silent_globals:
                return
            self._reply(global_dump(self._shorten(self.global_block)))
        elif command is SysexCommand.GLOBAL_WRITE:
            raw = sysex.unpack7(data)
            self.memory_log.append(("write_globals", None))
            if len(raw) != GLOBAL_SIZE:
                self.memory_log.append(("malformed_write", None))
                return
            self.global_block = raw

    def play(self, role: UnitPortRole, message: MidiMessage) -> None:
        self.emit(role, midi_codec.encode(message))

    def replay(self, name: str, include_identity: bool = False) -> int:
        """Emits a capture's lines in order on their ports; the identity reply (an answer) is skipped."""
        count = 0
        for port, data in load_capture(name):
            if not include_identity and sysex.parse_identity(data) is not None:
                continue
            if port in PORT_ROLES:
                self.emit(PORT_ROLES[port], data)
                count += 1
        return count

    def identity_reply(self) -> bytes:
        if self.product == sysex.APC64_PRODUCT and self.firmware == (1, 2, 1, 6):
            return fixture_identity_reply()
        return sysex.identity_reply(firmware=self.firmware, product=self.product)

    # --- host → unit ---------------------------------------------------------------------------------------------
    def _received(self, frame: bytes) -> None:
        command = sysex.command_of(frame)
        with self._lock:
            self.written.append(frame)
            self.commands.append(command)
            if command in HAZARDS:
                self.hazards.append(frame)
            elif command is SysexCommand.DAW_MODE:
                self.daw_mode = frame == sysex.daw_on()
            elif command is SysexCommand.OLED_TEXT:
                row = sysex.parse_oled(frame)
                if row is not None:
                    self.oled[row[0]] = row[1]
            elif command is SysexCommand.CHANNEL_MESSAGE:
                kind = frame[0] & 0xF0
                if kind == 0xE0:
                    self.bends[frame[0] & 0x0F] = frame[1] | (frame[2] << 7)
                elif len(frame) == 3:
                    self.leds[(kind, frame[1])] = frame[2]
        if command is SysexCommand.IDENTITY_REQUEST and not self.silent:
            self.emit(UnitPortRole.DAW, self.identity_reply())
        elif command in HAZARDS:
            self._memory(command, frame)
        elif command is SysexCommand.PAD_MODE and self.report_view_requests:
            view = sysex.view_report(frame)    # the request has the report's shape: 19 00 01 <m>
            if view is not None:
                self.view(view)

    def frames(self, command: SysexCommand) -> list[bytes]:
        return [f for f, c in zip(self.written, self.commands) if c is command]

    def dark(self) -> bool:
        """Every LED written so far is off and both OLED rows are blank (what release leaves, inv14). A strip's
        colour CC lights nothing while its mode CC is 0 (bar off), so it does not count then."""
        leds = dict(self.leds)
        for i in range(8):
            if leds.get((0xB0, STRIP_MODE_CC + i), 0) == 0:
                leds.pop((0xB0, STRIP_COLOUR_CC + i), None)
        return all(value == 0 for value in leds.values()) and all(not row for row in self.oled.values())


class _UnpluggedMidWrite(Exception):
    def __init__(self, slot):
        self.slot = slot


class SimulatedHolders:
    """HolderLookup over the simulated unit: who holds each subdevice, and changes."""

    def __init__(self, unit: SimulatedApc64):
        self._unit = unit

    def holder_of(self, role: UnitPortRole) -> Holder | None:
        return self._unit.holder_of(role)

    def subscribe(self, callback: Callable[[UnitPortRole, Holder | None], None]) -> None:
        self._unit._holder_subscribers.append(callback)
