"""Contract 2 T9: HostModule hooks with no-op defaults, and collect() of actions, sections, CLI commands and
hooks in registration order (inv14). Contract 1's own registry tests stay in test_modules.py."""
import pytest

from _apc64_host.application.modules import collect
from _apc64_host.application.ports import (
    HostModuleBase, HostPorts, LayoutLoader, ModuleDisplay, NoteEnder, SectionTweaks, SysexTap, TopicPublisher,
)
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.effects import Led, UnitView
from _apc64_host.domain.layout import ControlEvent, ModuleAction
from _apc64_host.domain.leds import LedState
from _apc64_host.domain.outbound import CONTRACT1_POLICY, SysexCommand, WriteCapability
from _apc64_host.domain.palette import parse_colour
from _apc64_host.domain.unit_status import ReleaseReason


class Recording(HostModuleBase):
    def __init__(self, name, calls, *, section=None, raises=None, suppress=False):
        self.name, self.calls, self._section, self._raises, self._suppress = name, calls, section, raises, suppress

    def actions(self):
        return {"go": lambda event: self.calls.append((self.name, "go", event))}

    def layout_sections(self):
        return {self._section: f"{self.name}-compiler"} if self._section else {}

    def cli_commands(self):
        return (f"{self.name}-cmd",)

    def _record(self, hook, *args):
        if hook == self._raises:
            raise RuntimeError(f"{self.name} broke")
        self.calls.append((self.name, hook) + args)

    def bind(self, host):
        self._record("bind", host)

    def on_held(self, unit):
        self._record("on_held", unit)

    def on_layout_loaded(self, layout, section):
        self._record("on_layout_loaded", section)

    def on_pad_mode(self, view):
        self._record("on_pad_mode", view)

    def on_release(self, reason):
        self._record("on_release", reason)

    def led_filter(self, led):
        self._record("led_filter", led.control)
        return None if self._suppress else led


class Contract1Style:
    """Only contract 1's three methods: it must still register, with every hook a no-op."""
    name = "plain"

    def outbound_additions(self):
        return frozenset()

    def router(self):
        return None

    def panel(self):
        return None


class Layout:
    def __init__(self, sections):
        self.sections = sections


LED = Led(PadPos(1, 1), LedState(parse_colour("red")))


def test_two_modules_collect_actions_sections_cli_and_hooks_in_registration_order():
    calls = []
    first, second = Recording("lab", calls, section="lab"), Recording("other", calls, section="extra")
    collection = collect([first, Contract1Style(), second])
    assert collection.names == ("lab", "plain", "other")
    assert list(collection.actions) == [ModuleAction("lab", "go"), ModuleAction("other", "go")]
    assert collection.sections == {"lab": "lab-compiler", "extra": "other-compiler"}
    assert collection.cli_commands == (("lab", "lab-cmd"), ("other", "other-cmd"))
    collection.action(ModuleAction("other", "go"))(ControlEvent.turn(3))
    assert calls == [("other", "go", ControlEvent(3, False))]
    del calls[:]
    hooks = collection.hooks
    hooks.bind(HostPorts())
    hooks.on_held("unit")
    hooks.on_layout_loaded(Layout({"lab": "compiled lab", "extra": "compiled extra"}))
    hooks.on_pad_mode(UnitView.CUSTOM)
    hooks.on_release(ReleaseReason.STOP)
    assert hooks.led_filter(LED) is LED
    assert calls == [
        ("lab", "bind", HostPorts()), ("other", "bind", HostPorts()),
        ("lab", "on_held", "unit"), ("other", "on_held", "unit"),
        ("lab", "on_layout_loaded", "compiled lab"), ("other", "on_layout_loaded", "compiled extra"),
        ("lab", "on_pad_mode", UnitView.CUSTOM), ("other", "on_pad_mode", UnitView.CUSTOM),
        ("lab", "on_release", ReleaseReason.STOP), ("other", "on_release", ReleaseReason.STOP),
        ("lab", "led_filter", PadPos(1, 1)), ("other", "led_filter", PadPos(1, 1)),
    ]


def test_a_contract1_style_module_collects_with_no_op_hooks():
    collection = collect([Contract1Style()])
    assert collection.actions == {} and collection.sections == {} and collection.cli_commands == ()
    hooks = collection.hooks
    hooks.bind(HostPorts())
    hooks.on_held(None)
    hooks.on_layout_loaded(None)            # a layout without sections, or none at all
    hooks.on_pad_mode(UnitView.NOTE)
    hooks.on_release(ReleaseReason.RELEASE)
    assert hooks.led_filter(LED) is LED
    assert collection.policy(CONTRACT1_POLICY) == CONTRACT1_POLICY
    assert not collect([]).hooks


def test_a_module_without_its_section_in_the_layout_gets_none():
    calls = []
    collect([Recording("lab", calls, section="lab")]).hooks.on_layout_loaded(Layout({}))
    assert calls == [("lab", "on_layout_loaded", None)]


def test_a_failing_hook_is_logged_and_the_other_modules_still_run(caplog):
    calls = []
    hooks = collect([Recording("lab", calls, raises="on_release"), Recording("other", calls)]).hooks
    hooks.on_release(ReleaseReason.UNPLUG)
    assert calls == [("other", "on_release", ReleaseReason.UNPLUG)]
    assert "module lab: on_release failed" in caplog.text


def test_led_filter_chains_and_a_none_suppresses_the_led():
    calls = []
    hooks = collect([Recording("lab", calls, suppress=True), Recording("other", calls)]).hooks
    assert hooks.led_filter(LED) is None
    assert calls == [("lab", "led_filter", PadPos(1, 1))]     # the next module never sees a suppressed LED


def test_scoped_writes_join_the_policy_only_for_their_capability():
    token = WriteCapability()

    class Lab(HostModuleBase):
        name = "lab"

        def outbound_additions(self):
            return frozenset({SysexCommand.PROJECT_READ, SysexCommand.GLOBAL_READ})

        def outbound_scoped(self):
            return {SysexCommand.PROJECT_WRITE: token, SysexCommand.GLOBAL_WRITE: token}

    policy = collect([Lab()]).policy(CONTRACT1_POLICY)
    assert policy == CONTRACT1_POLICY.with_additions({SysexCommand.PROJECT_READ, SysexCommand.GLOBAL_READ}) \
        .with_scoped({SysexCommand.PROJECT_WRITE}, token).with_scoped({SysexCommand.GLOBAL_WRITE}, token)
    assert policy.allows(SysexCommand.PROJECT_WRITE, token) and not policy.allows(SysexCommand.PROJECT_WRITE)
    assert policy.allows(SysexCommand.PROJECT_READ)


def test_bad_registrations_are_refused():
    class Twice(HostModuleBase):
        def __init__(self, name, sections=None, scoped=None):
            self.name, self._sections, self._scoped = name, sections or {}, scoped or {}

        def layout_sections(self):
            return self._sections

        def outbound_scoped(self):
            return self._scoped

    with pytest.raises(ValueError, match="layout section 'lab' is already registered"):
        collect([Twice("a", {"lab": 1}), Twice("b", {"lab": 2})])
    with pytest.raises(ValueError, match="already scoped"):
        collect([Twice("a", scoped={SysexCommand.PROJECT_WRITE: WriteCapability()}),
                 Twice("b", scoped={SysexCommand.PROJECT_WRITE: WriteCapability()})])
    with pytest.raises(TypeError, match="needs a WriteCapability"):
        collect([Twice("a", scoped={SysexCommand.PROJECT_WRITE: "token"})])


def test_the_port_protocols_describe_the_seams():
    class Display:
        def set_resting_oled(self, text): ...
        def warn(self, text): ...

    assert isinstance(Display(), ModuleDisplay)
    assert not isinstance(object(), NoteEnder)
    for protocol in (NoteEnder, LayoutLoader, SectionTweaks, SysexTap, TopicPublisher):
        assert not isinstance(Display(), protocol)
