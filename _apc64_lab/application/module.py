"""LabModule: the lab as a HostModule (contract §7.1; s2 expectation side, s3 supplier, s4 supplier; inv2, inv11,
inv12; a9, a10).

It adds the reads the lab needs as plain additions and its writes only as scoped ones: 0x14/0x18 pass the gate
with the guarded writer's one WriteCapability, never through outbound_additions() (inv2 hardening; contract 1's
plain additions could open any command, a build decision). The module itself never holds the
capability: it asks the writer for its scoped writes. check_scoped_writes() refuses a module shaped otherwise,
at construction and wherever the lab is composed.

Hooks delegate to the services and never block, except on_release (the session's release may wait briefly).
Shift + encoder stays the host's browser: the 'lab:' section binds only the base-layer encoder and Tempo (inv12).
"""
from _apc64_host.application.ports import HostModuleBase
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.outbound import SysexCommand, WriteCapability

from ..domain.lab_section import INTERVAL_CYCLE, LAB_MODULE, SECTION, WINDOW_SHIFT
from .guarded_writer import GuardedWriter
from .ports import HostLink

READS = frozenset({SysexCommand.PROJECT_READ, SysexCommand.GLOBAL_READ})
WRITES = frozenset({SysexCommand.PROJECT_WRITE, SysexCommand.GLOBAL_WRITE})


def check_scoped_writes(module) -> None:
    """inv2: a lab module opens 0x14/0x18 only as scoped writes, both to one WriteCapability."""
    plain = WRITES & frozenset(module.outbound_additions())
    if plain:
        raise ValueError(f"module {module.name!r} opens {', '.join(sorted(plain))} through plain additions; "
                         "declare writes in outbound_scoped() with the guarded writer's capability")
    scoped = dict(module.outbound_scoped())
    tokens = {id(token) for token in scoped.values()}
    if set(scoped) != WRITES or len(tokens) != 1 or not all(isinstance(t, WriteCapability) for t in scoped.values()):
        raise ValueError(f"module {module.name!r} must scope exactly project and global writes to one capability")


class LabModule(HostModuleBase):
    name = LAB_MODULE

    def __init__(self, link: HostLink, writer: GuardedWriter, session, compiler, tracker=None, *,
                 router=None, panel: str | None = None, cli_commands: tuple = (), on_bind: tuple = ()):
        self._link, self._writer, self.session, self.compiler = link, writer, session, compiler
        self.tracker = tracker
        self._router, self._panel, self._cli = router, panel, tuple(cli_commands)
        self._on_bind = tuple(on_bind)          # composition callbacks given the host ports (the hub)
        check_scoped_writes(self)

    # --- what the module adds to the core ---------------------------------------------------------------
    def outbound_additions(self):
        return READS

    def outbound_scoped(self):
        return self._writer.scoped_writes()

    def router(self):
        return self._router

    def panel(self):
        return self._panel

    def cli_commands(self):
        return self._cli

    def actions(self):
        return {WINDOW_SHIFT: lambda event: self.session.on_action(WINDOW_SHIFT, event),
                INTERVAL_CYCLE: lambda event: self.session.on_action(INTERVAL_CYCLE, event)}

    def layout_sections(self):
        return {SECTION: self.compiler}

    # --- the host's events ------------------------------------------------------------------------------
    def bind(self, host) -> None:
        self._link.bind(host)
        if self.tracker is not None:
            self.tracker.start()
        for callback in self._on_bind:
            callback(host)

    def on_held(self, unit) -> None:
        self.session.on_held(unit)

    def on_layout_loaded(self, layout, section) -> None:
        self.session.on_layout_loaded(layout, section)

    def on_pad_mode(self, view) -> None:
        self.session.on_view(view)

    def on_release(self, reason) -> None:
        self.session.end(reason)

    def led_filter(self, led):
        """No pad LED is drawn while a generated layout plays in Custom view (§2.7 a4: cleanliness only)."""
        if isinstance(getattr(led, "control", None), PadPos) and self.session.led_suppressed():
            return None
        return led
