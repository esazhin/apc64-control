"""The lab-wide default note target for generated layouts (contract §2.7 q2).

One default target (an output port, a channel and an aftertouch rule, the host's routing rule) is set once in the
configuration; any generated layout may override it with its own host routing line ('routing: custom: …'). With
neither, the notes played on a generated layout are only shown, and the lab state says so.

    APC64_LAB_TARGET=MPC Live III MIDI 1 ch 2 aftertouch pass
"""
import re
from dataclasses import dataclass

from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.layout import (
    AftertouchPolicy, DeviceDecl, DeviceName, PortPattern, RoutingRule, UnitPortRole,
)
from _apc64_host.domain.midi import Channel

DEFAULT_DEVICE = "lab-default"
NOT_ROUTED_TEXT = "notes are only shown: no default target and no layout target"
_PHRASE = re.compile(r"^(?P<port>.+?)\s+(?:ch|channel)\s*(?P<channel>\d+)"
                     r"(?:\s+aftertouch\s+(?P<aftertouch>pass|pressure|drop))?\s*$", re.IGNORECASE)
_FIX = "write '<port> ch <1–16> [aftertouch pass|pressure|drop]', e.g. 'MPC Live III MIDI 1 ch 2 aftertouch pass'"


@dataclass(frozen=True)
class NoteTarget:
    """Where Custom-view notes of a generated layout go when the layout names no target of its own."""
    port: str
    channel: int = 1
    aftertouch: AftertouchPolicy = AftertouchPolicy.PASS
    device: str = DEFAULT_DEVICE

    def __post_init__(self):
        object.__setattr__(self, "port", str(PortPattern(self.port)))
        try:
            object.__setattr__(self, "channel", int(Channel(self.channel)))
        except (DomainInvariantError, ValueError, TypeError):
            raise DomainInvariantError("target", f"channel {self.channel}", "channels are 1–16", joiner=": ") from None
        object.__setattr__(self, "aftertouch", AftertouchPolicy(self.aftertouch))
        self.declaration()   # refuses an APC64 port (the host never sends to the unit's own ports)

    @classmethod
    def parse(cls, text: str) -> "NoteTarget":
        match = _PHRASE.match(" ".join(str(text or "").split()))
        if match is None:
            raise DomainInvariantError("target", f"'{text}' is not a note target", _FIX)
        return cls(match["port"], int(match["channel"]),
                   AftertouchPolicy((match["aftertouch"] or "pass").lower()))

    def declaration(self) -> DeviceDecl:
        return DeviceDecl(DeviceName(self.device), PortPattern(self.port))

    def rule(self) -> RoutingRule:
        return RoutingRule(UnitPortRole.CUSTOM, DeviceName(self.device), Channel(self.channel), self.aftertouch)

    def text(self) -> str:
        return f"{self.port} ch {self.channel} aftertouch {self.aftertouch}"
