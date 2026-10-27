"""What may be sent to the APC64: the SysEx command kinds and the injected outbound policy (contract inv15).

CONTRACT1_POLICY allows identity, the DAW-mode handshake, OLED text and channel messages (LEDs) only.
Project and global reads and writes (0x13/0x14/0x17/0x18) and any unknown SysEx are refused by the gate.
Contract 2 widens the policy by registering a HostModule, never by editing this table: its reads are plain
additions, and its writes are issuer-scoped to the one WriteCapability its guarded writer holds.
"""
from dataclasses import dataclass
from enum import StrEnum


class SysexCommand(StrEnum):
    IDENTITY_REQUEST = "identity_request"   # F0 7E 7F 06 01 F7
    OLED_TEXT = "oled_text"                 # 0x10
    PROJECT_READ = "project_read"           # 0x13
    PROJECT_WRITE = "project_write"         # 0x14
    GLOBAL_READ = "global_read"             # 0x17
    GLOBAL_WRITE = "global_write"           # 0x18
    PAD_MODE = "pad_mode"                   # 0x19 (host request; the unit's report uses the same id)
    DRUM_FLAG = "drum_flag"                 # 0x1B
    DAW_MODE = "daw_mode"                   # 0x1C
    CHANNEL_MESSAGE = "channel_message"     # not SysEx: note-on/CC/pitch-bend LED output
    UNKNOWN_SYSEX = "unknown_sysex"


HAZARD_TEXT = {
    SysexCommand.PROJECT_READ: "project read (0x13)",
    SysexCommand.PROJECT_WRITE: "project write (0x14)",
    SysexCommand.GLOBAL_READ: "global-settings read (0x17)",
    SysexCommand.GLOBAL_WRITE: "global-settings write (0x18)",
    SysexCommand.UNKNOWN_SYSEX: "unknown SysEx",
}


class WriteCapability:
    """The token that lets a frame of an issuer-scoped command through the gate (contract 2, inv2, a10).

    Equality is identity: only the one instance the composition root hands to the lab's guarded writer
    passes, never a copy or a look-alike. It carries no data and grants nothing by itself."""
    __slots__ = ("holder",)

    def __init__(self, holder: str = "guarded writer"):
        self.holder = holder

    def __repr__(self) -> str:
        return f"WriteCapability({self.holder!r})"

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


@dataclass(frozen=True)
class OutboundPolicy:
    """Which commands may be sent. `allowed` pass for every caller. `scoped` commands pass only for the
    issuer holding their WriteCapability; a scoped command is never opened to everyone, even if it is also
    added to `allowed` (contract 2: the lab's 0x14/0x18 writes)."""
    allowed: frozenset[SysexCommand]
    scoped: tuple[tuple[SysexCommand, WriteCapability], ...] = ()

    def allows(self, command: SysexCommand, issuer: WriteCapability | None = None) -> bool:
        holders = [capability for scoped, capability in self.scoped if scoped is command]
        if holders:
            return issuer is not None and any(issuer is capability for capability in holders)
        return command in self.allowed

    def with_additions(self, additions) -> "OutboundPolicy":
        return OutboundPolicy(self.allowed | frozenset(additions), self.scoped)

    def with_scoped(self, commands, capability: WriteCapability) -> "OutboundPolicy":
        """These commands pass only with `capability` from now on."""
        if not isinstance(capability, WriteCapability):
            raise TypeError("a scoped allowance needs a WriteCapability")
        return OutboundPolicy(self.allowed, self.scoped + tuple((SysexCommand(c), capability) for c in commands))

    @property
    def scoped_commands(self) -> frozenset[SysexCommand]:
        return frozenset(command for command, _ in self.scoped)


CONTRACT1_POLICY = OutboundPolicy(frozenset({
    SysexCommand.IDENTITY_REQUEST, SysexCommand.OLED_TEXT, SysexCommand.PAD_MODE, SysexCommand.DRUM_FLAG,
    SysexCommand.DAW_MODE, SysexCommand.CHANNEL_MESSAGE,
}))


class DeviceLogOutcome(StrEnum):
    SENT = "sent"
    REFUSED = "refused"


@dataclass(frozen=True)
class DeviceLogEntry:
    """One frame offered to the unit; a refused one is a hazard (contract d176)."""
    at: float
    frame: bytes
    outcome: DeviceLogOutcome
    command: SysexCommand

    @property
    def hazard(self) -> bool:
        return self.outcome is DeviceLogOutcome.REFUSED

    def refusal_text(self) -> str:
        return f"refused: {HAZARD_TEXT.get(self.command, str(self.command))}"

    def subject(self) -> str:
        """What the frame would have done: 'project write slot 3', 'global-settings write', 'oled_text'."""
        what = _SUBJECT.get(self.command)
        if what is None:
            return HAZARD_TEXT.get(self.command, str(self.command))
        if self.command in (SysexCommand.PROJECT_READ, SysexCommand.PROJECT_WRITE) and len(self.frame) > 8:
            what += f" slot {self.frame[7]}"     # F0 47 00 53 <cmd> <len> <len> <slot> …
        return what

    def hazard_line(self) -> str:
        """The gate's log line for a refused frame (contract 2 T10): 'HAZARD refused: project write slot 3'."""
        return f"HAZARD refused: {self.subject()}"


_SUBJECT = {
    SysexCommand.PROJECT_READ: "project read", SysexCommand.PROJECT_WRITE: "project write",
    SysexCommand.GLOBAL_READ: "global-settings read", SysexCommand.GLOBAL_WRITE: "global-settings write",
}
