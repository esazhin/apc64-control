"""ExpressiveRouter: notes played in the unit's own Note/Chord/Step/Drum/Custom views, routed per layout.

Velocity is never touched (d139). Aftertouch is passed, turned into channel pressure (the highest current
poly aftertouch among held notes, d141) or dropped. Transpose and remap apply only when the rule asks
(remap first, then transpose; d145). A held-note table makes every note-off and aftertouch reuse its
note-on's target and transform, even if the rule changed in between (d137). Routing is by note number
only; replica pad positions never feed it (contract §7.1).

Contract 2 (s2.c9, d47): end_notes() ends held notes at a window shift or layout switch. Each held note gets one
note-off at the target it went to and a NOTE_ENDED play event ('ended by window shift'); the unit's later
release of that note (and any aftertouch before it) is absorbed: nothing is sent or published for it. The
Custom port carries notes, not pads, so the release is matched by (port, channel, note): the unit is taken to
release a pad with the note it pressed it with.
"""
from dataclasses import dataclass

from .effects import (
    ENDED_BY_WINDOW_SHIFT, NOTE_ENDED, Activity, ActivityEntry, ActivityResult, Effect, Origin, Play, PlayEvent,
    PlayedMidi, PlayedNote, Send, UnitView,
)
from .layout import AftertouchPolicy, DeviceName, Layout, PortPattern, RoutingRule, UnitPortRole
from .midi import (
    ChannelPressure, ControlChange, NoteOff, NoteOn, PitchBend, PolyAftertouch, ProgramChange,
)

NOT_ROUTED = "expressive pads not routed in this layout"


@dataclass(frozen=True)
class _Held:
    """Where one sounding note went: target, channel, outgoing note (None when dropped) and AT policy."""
    device: DeviceName | None
    port: PortPattern | None
    channel: int | None
    out: int | None
    aftertouch: AftertouchPolicy


class ExpressiveRouter:
    def __init__(self):
        self._rules: dict[UnitPortRole, RoutingRule] = {}
        self._ports: dict[DeviceName, PortPattern] = {}
        self._held: dict[tuple, list[_Held]] = {}
        self._pressure: dict[tuple, dict[int, int]] = {}   # (device, channel) -> out note -> pressure
        self._pressure_sent: dict[tuple, int] = {}
        self._sounding: dict[tuple, PlayedNote] = {}
        self._absorb: dict[tuple, int] = {}      # (role, channel, note) → releases still to absorb (contract 2)

    def set_layout(self, layout: Layout | None):
        """New rules apply to new notes; held notes keep the transform they started with."""
        self._rules = dict(layout.routing) if layout else {}
        self._ports = {d.name: d.pattern for d in layout.devices.values()} if layout else {}

    def routed(self, role: UnitPortRole) -> bool:
        return role in self._rules

    def sounding(self) -> tuple[PlayedNote, ...]:
        """The notes currently held on the unit's own views, for the replica's played-notes row."""
        return tuple(self._sounding.values())

    def handle(self, played: PlayedMidi, view: UnitView | None = None) -> list[Effect]:
        message, role = played.message, played.role
        effects: list[Effect] = []
        if isinstance(message, NoteOn) and message.velocity > 0:
            self._note_on(role, message, view, effects)
        elif isinstance(message, (NoteOn, NoteOff)):   # a velocity-0 note-on is a note-off (d135)
            self._note_off(role, message.channel, message.note, view, effects)
        elif isinstance(message, PolyAftertouch):
            self._aftertouch(role, message, view, effects)
        else:
            self._other(role, message, view, effects)
        return effects

    # --- ending held notes (contract 2 NoteEnder) ---------------------------------------------------------
    def end_notes(self, notes, role: UnitPortRole = UnitPortRole.CUSTOM, view: UnitView | None = None) -> list[Effect]:
        effects: list[Effect] = []
        wanted = {int(n) for n in notes}
        for key in [k for k in self._held if k[0] is role and k[2] in wanted]:
            note = key[2]
            for held in reversed(self._held.pop(key)):
                self._absorb[key] = self._absorb.get(key, 0) + 1
                sent = ()
                if held.device is not None and held.out is not None:
                    off = NoteOff(held.channel, held.out)
                    effects.append(Send(held.device, held.port, off, Origin(note=note, role=role, kind="note")))
                    sent = (off.describe(),)
                    if held.aftertouch is AftertouchPolicy.CHANNEL_PRESSURE:
                        self._pressure.get((held.device, held.channel), {}).pop(held.out, None)
                        self._send_pressure(held, role, note, effects)
                effects.append(Play(PlayEvent(NOTE_ENDED, view=view, note=note, sent=sent,
                                              reason=ENDED_BY_WINDOW_SHIFT)))
            self._sounding.pop((role, note), None)
        return effects

    def _absorbed(self, key) -> bool:
        """A release of a note end_notes() already ended: used up, nothing sent (d47)."""
        left = self._absorb.get(key, 0)
        if not left:
            return False
        if left == 1:
            del self._absorb[key]
        else:
            self._absorb[key] = left - 1
        return True

    # --- notes ------------------------------------------------------------------------------------------
    def _note_on(self, role, message: NoteOn, view, effects):
        note, velocity = int(message.note), int(message.velocity)
        rule = self._rules.get(role)
        key = (role, int(message.channel), note)
        if rule is None:
            self._held.setdefault(key, []).append(_Held(None, None, None, None, AftertouchPolicy.DROP))
            self._sounding[(role, note)] = PlayedNote(role, note, velocity, 0, routed=False)
            effects.append(Play(PlayEvent("note_on", view=view, note=note, velocity=velocity, reason=NOT_ROUTED)))
            return
        out = rule.remap_of(note) + rule.transpose
        port = self._ports[rule.device]
        self._sounding[(role, note)] = PlayedNote(role, note, velocity, 0, routed=0 <= out <= 127)
        if not 0 <= out <= 127:
            self._held.setdefault(key, []).append(_Held(None, None, None, None, rule.aftertouch))
            reason = f"note {out} out of range"
            effects.append(Activity(ActivityEntry(f"note {note}", ActivityResult.DROPPED, reason=reason, note=note)))
            effects.append(Play(PlayEvent("note_on", view=view, note=note, velocity=velocity, reason=reason)))
            return
        self._held.setdefault(key, []).append(_Held(rule.device, port, int(rule.channel), out, rule.aftertouch))
        sent = NoteOn(rule.channel, out, velocity)
        effects.append(Send(rule.device, port, sent, Origin(note=note, role=role, kind="note")))
        effects.append(Play(PlayEvent("note_on", view=view, note=note, velocity=velocity, sent=(sent.describe(),))))

    def _note_off(self, role, channel, note, view, effects):
        note = int(note)
        if self._absorb and self._absorbed((role, int(channel), note)):
            return
        stack = self._held.get((role, int(channel), note))
        held = stack.pop() if stack else None
        if stack == []:
            del self._held[(role, int(channel), note)]
        self._sounding.pop((role, note), None)
        if held is None:   # its note-on was never seen (played before the hold): route with today's rule
            rule = self._rules.get(role)
            if rule is None:
                effects.append(Play(PlayEvent("note_off", view=view, note=note, reason=NOT_ROUTED)))
                return
            out = rule.remap_of(note) + rule.transpose
            held = _Held(rule.device, self._ports[rule.device], int(rule.channel),
                         out if 0 <= out <= 127 else None, rule.aftertouch)
        if held.out is None:
            effects.append(Play(PlayEvent("note_off", view=view, note=note,
                                          reason=NOT_ROUTED if held.device is None else "not sent")))
            return
        sent = NoteOff(held.channel, held.out)
        effects.append(Send(held.device, held.port, sent, Origin(note=note, role=role, kind="note")))
        effects.append(Play(PlayEvent("note_off", view=view, note=note, sent=(sent.describe(),))))
        if held.aftertouch is AftertouchPolicy.CHANNEL_PRESSURE:
            self._pressure.get((held.device, held.channel), {}).pop(held.out, None)
            self._send_pressure(held, role, note, effects)

    def _aftertouch(self, role, message: PolyAftertouch, view, effects):
        note, pressure = int(message.note), int(message.pressure)
        if (role, int(message.channel), note) in self._absorb and (role, int(message.channel), note) not in self._held:
            return   # the pad of an ended note is still pressed: its aftertouch goes nowhere (d47)
        stack = self._held.get((role, int(message.channel), note))
        if (role, note) in self._sounding:
            playing = self._sounding[(role, note)]
            self._sounding[(role, note)] = PlayedNote(role, note, playing.velocity, pressure, playing.routed)
        held = stack[-1] if stack else None
        reason = _unsent_reason(held)
        if reason is not None:
            effects.append(Play(PlayEvent("aftertouch", view=view, note=note, aftertouch=pressure, reason=reason)))
            return
        if held.aftertouch is AftertouchPolicy.PASS:
            sent = PolyAftertouch(held.channel, held.out, pressure)
            effects.append(Send(held.device, held.port, sent, Origin(note=note, role=role, kind="aftertouch")))
            effects.append(Play(PlayEvent("aftertouch", view=view, note=note, aftertouch=pressure,
                                          sent=(sent.describe(),))))
            return
        self._pressure.setdefault((held.device, held.channel), {})[held.out] = pressure
        sent = self._send_pressure(held, role, note, effects)
        effects.append(Play(PlayEvent("aftertouch", view=view, note=note, aftertouch=pressure,
                                      sent=(sent.describe(),) if sent else ())))

    def _send_pressure(self, held: _Held, role, note, effects) -> ChannelPressure | None:
        """Channel pressure = the highest poly aftertouch among held notes; sent only when it changes."""
        key = (held.device, held.channel)
        level = max(self._pressure.get(key, {}).values(), default=0)
        if self._pressure_sent.get(key, 0) == level:
            return None
        self._pressure_sent[key] = level
        sent = ChannelPressure(held.channel, level)
        effects.append(Send(held.device, held.port, sent, Origin(note=note, role=role, kind="aftertouch")))
        return sent

    # --- everything else (Custom-view strip CCs, d132) --------------------------------------------------
    def _other(self, role, message, view, effects):
        rule = self._rules.get(role)
        if rule is None:
            effects.append(Play(PlayEvent("cc", view=view, reason=NOT_ROUTED)))
            return
        channel = rule.channel
        match message:
            case ControlChange():
                sent = ControlChange(channel, message.control, message.value)
            case PitchBend():
                sent = PitchBend(channel, message.value)
            case ProgramChange():
                sent = ProgramChange(channel, message.program)
            case ChannelPressure() if rule.aftertouch is not AftertouchPolicy.DROP:
                sent = ChannelPressure(channel, message.pressure)
            case _:
                return
        port = self._ports[rule.device]
        effects.append(Send(rule.device, port, sent, Origin(role=role, kind="cc")))
        effects.append(Play(PlayEvent("cc", view=view, value=getattr(message, "value", None),
                                      sent=(sent.describe(),))))


def _unsent_reason(held: _Held | None) -> str | None:
    """Why an aftertouch value goes nowhere, or None when it is to be sent."""
    if held is None or held.device is None:
        return NOT_ROUTED
    if held.out is None:
        return "not sent"
    if held.aftertouch is AftertouchPolicy.DROP:
        return "aftertouch dropped"
    return None
