"""The HostModule registry (contract §7.1, OCP): what registered modules add to the core.

Contract 1 registers none, so the outbound gate gets CONTRACT1_POLICY and the API no extra routes. Contract 2
(the layout lab) adds a module whose outbound_additions() names the reads it needs and whose outbound_scoped()
names the writes that pass only with its WriteCapability (inv2).

collect() also gathers (contract 2, T9) the module actions, layout sections and CLI commands, and the hooks
(ModuleHooks), in registration order. A module that has only contract 1's three methods gets every hook's
no-op default. Hooks run guarded: one module's failing hook is logged and never stops the host or the other
modules (s3.c2).
"""
import logging
from dataclasses import dataclass, field

from ..domain.layout import ModuleAction
from ..domain.outbound import OutboundPolicy, SysexCommand, WriteCapability
from .ports import HostModule, HostModuleBase

log = logging.getLogger(__name__)
_DEFAULTS = HostModuleBase()


def _hook(module, name):
    """The module's hook, or the no-op default when it has none."""
    found = getattr(module, name, None)
    return found if callable(found) else getattr(_DEFAULTS, name)


@dataclass(frozen=True)
class ModuleHooks:
    """The registered modules' hooks, called in registration order, each guarded."""
    modules: tuple = ()
    sections: tuple[tuple[str, ...], ...] = ()       # per module: the layout-section keys it owns

    def __bool__(self) -> bool:
        return bool(self.modules)

    def _each(self, hook: str, *args) -> None:
        for module in self.modules:
            try:
                _hook(module, hook)(*args)
            except Exception:
                log.exception("module %s: %s failed", getattr(module, "name", module), hook)

    def bind(self, host) -> None:
        self._each("bind", host)

    def on_held(self, unit) -> None:
        self._each("on_held", unit)

    def on_pad_mode(self, view) -> None:
        self._each("on_pad_mode", view)

    def on_release(self, reason) -> None:
        self._each("on_release", reason)

    def on_layout_loaded(self, layout) -> None:
        """Each module gets the layout and its own compiled section (the first of its keys present), or None."""
        compiled = getattr(layout, "sections", None) or {}
        for module, keys in zip(self.modules, self.sections):
            section = next((compiled[k] for k in keys if k in compiled), None)
            try:
                _hook(module, "on_layout_loaded")(layout, section)
            except Exception:
                log.exception("module %s: on_layout_loaded failed", getattr(module, "name", module))

    def led_filter(self, led):
        """Chained: each module sees what the previous one let through; None from any suppresses the LED."""
        for module in self.modules:
            if led is None:
                return None
            try:
                led = _hook(module, "led_filter")(led)
            except Exception:
                log.exception("module %s: led_filter failed", getattr(module, "name", module))
        return led

    def take_played(self, played) -> str | None:
        """The first module that takes a played message gives its reason; None: no module took it (§2.10)."""
        for module in self.modules:
            try:
                reason = _hook(module, "take_played")(played)
            except Exception:   # a failing module never swallows the playing: the router has it
                log.exception("module %s: take_played failed", getattr(module, "name", module))
                continue
            if reason:
                return str(reason)
        return None


@dataclass(frozen=True)
class ModuleCollection:
    policy_additions: frozenset[SysexCommand] = frozenset()
    routers: tuple = ()
    panels: tuple[tuple[str, str], ...] = ()     # (module name, static path)
    names: tuple[str, ...] = ()
    scoped: tuple[tuple[SysexCommand, WriteCapability], ...] = ()
    actions: dict = field(default_factory=dict)       # ModuleAction → handler(ControlEvent)
    sections: dict = field(default_factory=dict)      # layout top-level key → SectionCompiler
    cli_commands: tuple = ()                          # (module name, command), in registration order
    hooks: ModuleHooks = ModuleHooks()

    def policy(self, base: OutboundPolicy) -> OutboundPolicy:
        policy = base.with_additions(self.policy_additions)
        for command, capability in self.scoped:
            policy = policy.with_scoped({command}, capability)
        return policy

    def action(self, module_action: ModuleAction):
        return self.actions.get(module_action)


def collect(modules) -> ModuleCollection:
    """Union of every module's policy additions, scoped writes, routers, panels, actions, sections, CLI commands
    and hooks, in registration order."""
    additions: set[SysexCommand] = set()
    routers, panels, names, scoped, cli, owned_sections = [], [], [], [], [], []
    actions, sections = {}, {}
    hooked = []
    for module in modules:
        if not isinstance(module, HostModule):
            raise TypeError(f"{module!r} is not a HostModule")
        if module.name in names:
            raise ValueError(f"two modules are named {module.name!r}")
        names.append(module.name)
        additions |= set(module.outbound_additions())
        for command, capability in dict(_hook(module, "outbound_scoped")()).items():
            command = SysexCommand(command)
            if not isinstance(capability, WriteCapability):
                raise TypeError(f"module {module.name!r}: {command} needs a WriteCapability")
            if any(c is command for c, _ in scoped):
                raise ValueError(f"module {module.name!r}: {command} is already scoped to another module")
            scoped.append((command, capability))
        router, panel = module.router(), module.panel()
        if router is not None:
            routers.append(router)
        if panel is not None:
            panels.append((module.name, panel))
        for action, handler in dict(_hook(module, "actions")()).items():
            actions[ModuleAction(module.name, action)] = handler
        keys = []
        for key, compiler in dict(_hook(module, "layout_sections")()).items():
            if key in sections:
                raise ValueError(f"module {module.name!r}: layout section {key!r} is already registered")
            sections[key] = compiler
            keys.append(key)
        owned_sections.append(tuple(keys))
        cli += [(module.name, command) for command in _hook(module, "cli_commands")()]
        hooked.append(module)
    return ModuleCollection(frozenset(additions), tuple(routers), tuple(panels), tuple(names), tuple(scoped),
                            actions, sections, tuple(cli), ModuleHooks(tuple(hooked), tuple(owned_sections)))
