"""A held simulated APC64 for the lab's adapter and scenario tests: the simulator (with lab memory) behind the real
outbound gate (with the lab's scoped policy) and the real DeviceSession and its SysEx tap. Hermetic: no ALSA, no /dev/snd."""
from _apc64_host.application.modules import collect
from _apc64_host.application.outbound_gate import OutboundGate
from _apc64_host.application.ports import HostPorts
from _apc64_host.application.test_session import AGENT, Engine, Rig
from _apc64_host.domain.outbound import CONTRACT1_POLICY, SysexCommand, WriteCapability
from _apc64_host.infrastructure.simulated_apc64 import SimulatedApc64
from _apc64_host.protocol import sysex
from _apc64_lab.application.ports import HostLink
from _apc64_lab.infrastructure.unit_memory import UnitMemoryAdapter


class ViewEngine(Engine):
    """The session's engine double, plus what the real engine does for modules: on_held once per take and
    on_pad_mode for each view report on the DAW port."""

    def __init__(self):
        super().__init__()
        self.hooks = None

    def on_held(self, unit):
        self.calls.append("held")
        self.unit = unit
        unit.daw.listen(self._daw, lambda: self.calls.append("daw gone"))
        if self.hooks is not None:
            self.hooks.on_held(unit)

    def _daw(self, chunk):
        view = sysex.view_report(chunk)
        if view is not None and self.hooks is not None:
            self.hooks.on_pad_mode(view)


def lab_policy(capability):
    return CONTRACT1_POLICY.with_additions({SysexCommand.PROJECT_READ, SysexCommand.GLOBAL_READ}) \
        .with_scoped({SysexCommand.PROJECT_WRITE, SysexCommand.GLOBAL_WRITE}, capability)


class HeldUnit:
    """sim + gate + session; `link` is the HostLink a lab adapter reads its gate and tap from."""

    def __init__(self, sim=None, capability=None, modules=None):
        self.capability = capability or WriteCapability("lab guarded writer")
        self.engine = ViewEngine()
        self.rig = Rig(sim=sim or SimulatedApc64(), gate=OutboundGate(lab_policy(self.capability)), engine=self.engine)
        self.sim, self.gate, self.session = self.rig.sim, self.rig.gate, self.rig.session
        self.link = HostLink(HostPorts(sysex=self.session.sysex_tap, gate=self.gate, clock=self.rig.clock))
        self.memory = UnitMemoryAdapter(self.link, timeout=0.05)
        if modules:
            self.use(modules)

    def use(self, modules):
        collection = collect(modules)
        self.session._modules = collection.hooks          # as DeviceSession(modules=…) is given it
        self.engine.hooks = collection.hooks
        return collection

    async def take(self):
        if not getattr(self, "_started", False):
            self.session.start()
            self._started = True
        answer = await self.session.take(AGENT)
        assert answer.result.value == "taken"
        return self
