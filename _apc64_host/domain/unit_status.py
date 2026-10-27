"""Who holds the APC64, as a pure state machine over what the session observes (contract d1–d36).

The session observes presence, holders, consent, open results and releases; transition() gives the next
status, and each status carries the text the page and CLI show. 'declined' is the status after a No:
the port stays free and the page says 'Not held' until the next appearance or a later yes.
"""
from dataclasses import dataclass, replace
from enum import StrEnum


class ConsentSource(StrEnum):
    BANNER = "banner"
    NOTIFICATION = "notification"
    LAN_BROWSER = "lan_browser"
    AGENT = "agent"
    AUTO_ACCEPT = "auto_accept"


@dataclass(frozen=True)
class Holder:
    name: str


class OpenFailure(StrEnum):
    BUSY = "busy"
    NO_PERMISSION = "no_permission"
    GONE = "gone"
    NOT_AN_APC64 = "not_an_apc64"
    NO_REPLY = "no_reply"


class ReleaseReason(StrEnum):
    RELEASE = "release"
    STOP = "stop"
    UNPLUG = "unplug"
    FAULT = "fault"


@dataclass(frozen=True)
class _Status:
    notices: tuple[str, ...] = ()
    STATUS = ""

    @property
    def status(self) -> str:
        return self.STATUS

    @property
    def held(self) -> bool:
        return False


@dataclass(frozen=True)
class Absent(_Status):
    STATUS = "absent"

    @property
    def text(self) -> str:
        return "APC64 not connected"


@dataclass(frozen=True)
class Asking(_Status):
    STATUS = "asking"

    @property
    def text(self) -> str:
        return "Take control of APC64?"


@dataclass(frozen=True)
class Declined(_Status):
    STATUS = "declined"

    @property
    def text(self) -> str:
        return "Not held"


@dataclass(frozen=True)
class Busy(_Status):
    holder: Holder | None = None
    STATUS = "busy"

    @property
    def text(self) -> str:
        return f"Busy: held by {self.holder.name}" if self.holder else "Busy: held by another program"


@dataclass(frozen=True)
class NoPermission(_Status):
    STATUS = "no_permission"

    @property
    def text(self) -> str:
        return "No permission to open APC64"


@dataclass(frozen=True)
class Held(_Status):
    by: ConsentSource = ConsentSource.BANNER
    firmware_warning: str | None = None
    STATUS = "held"

    @property
    def held(self) -> bool:
        return True

    @property
    def text(self) -> str:
        return {ConsentSource.AUTO_ACCEPT: "Held (taken automatically)",
                ConsentSource.AGENT: "Held (taken by command-line tool)"}.get(self.by, "Held")


@dataclass(frozen=True)
class Unplugged(_Status):
    STATUS = "unplugged"

    @property
    def text(self) -> str:
        return "APC64 unplugged: released"


@dataclass(frozen=True)
class MaybeStuck(_Status):
    STATUS = "maybe_stuck"

    @property
    def text(self) -> str:
        return "APC64 may still be in DAW mode: Take to reset, or replug it"


UnitStatus = Absent | Asking | Declined | Busy | NoPermission | Held | Unplugged | MaybeStuck


# --- observations ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Presence:
    present: bool
    ignored: int = 0   # further APC64 units seen and not offered (contract d5)


@dataclass(frozen=True)
class StaleMarker:
    """The holding marker survived a previous run: the unit may still be in DAW mode (d6)."""


@dataclass(frozen=True)
class HolderChanged:
    holder: Holder | None


@dataclass(frozen=True)
class Consent:
    source: ConsentSource


@dataclass(frozen=True)
class Decline:
    pass


@dataclass(frozen=True)
class OpenFailed:
    failure: OpenFailure
    holder: Holder | None = None
    detail: str | None = None


@dataclass(frozen=True)
class Opened:
    by: ConsentSource
    firmware_warning: str | None = None
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Released:
    reason: ReleaseReason


Observation = Presence | StaleMarker | HolderChanged | Consent | Decline | OpenFailed | Opened | Released

_NOT_HELD = (Asking, Declined, Busy, NoPermission, MaybeStuck)


def _ignored_notice(count: int) -> tuple[str, ...]:
    return ("second APC64 ignored",) if count else ()


def transition(status: UnitStatus, observation: Observation) -> UnitStatus:
    """The next status. Consent alone changes nothing: the session acts on it and reports Opened/OpenFailed."""
    match observation:
        case Presence(present=False):
            return Unplugged() if isinstance(status, (Held, Unplugged)) else Absent()
        case Presence(present=True, ignored=ignored):
            if isinstance(status, (Absent, Unplugged)):
                return Asking(_ignored_notice(ignored))
            kept = tuple(n for n in status.notices if n != "second APC64 ignored")
            return replace(status, notices=kept + _ignored_notice(ignored))
        case StaleMarker():
            return MaybeStuck(status.notices) if isinstance(status, Asking) else status
        case HolderChanged(holder=holder):
            if isinstance(status, Busy) and holder is None:
                return Asking()
            if isinstance(status, (Asking, MaybeStuck, NoPermission, Busy)) and holder is not None:
                return Busy(holder=holder)
            return status
        case Consent():
            return status
        case Decline():
            return Declined() if isinstance(status, _NOT_HELD) else status
        case OpenFailed(failure=failure, holder=holder, detail=detail):
            if failure is OpenFailure.BUSY:
                return Busy(holder=holder)
            if failure is OpenFailure.NO_PERMISSION:
                return NoPermission()
            if failure is OpenFailure.GONE:
                return Absent()
            if failure is OpenFailure.NO_REPLY:
                return Asking(("No APC64 identity reply",))
            return Asking((detail or "the device on the APC64 port is not an APC64",))
        case Opened(by=by, firmware_warning=warning, notices=notices):
            return Held(notices, by=by, firmware_warning=warning)
        case Released(reason=reason):
            if not isinstance(status, Held):
                return status
            if reason is ReleaseReason.UNPLUG:
                return Unplugged()
            if reason is ReleaseReason.FAULT:
                return Asking(("Released after an internal error",))
            return Asking()
    raise TypeError(f"not an observation: {observation!r}")


@dataclass(frozen=True)
class UnitPresence:
    """Where the APC64's subdevices are right now, found by port name (contract inv17): role → 'hw:<c>,0,<s>'."""
    daw: str
    notes: str | None = None
    custom: str | None = None
    ignored: int = 0   # further APC64 units seen and not offered (contract d5)

    def address(self, role: str) -> str | None:
        return {"daw": self.daw, "notes": self.notes, "custom": self.custom}[str(role)]
