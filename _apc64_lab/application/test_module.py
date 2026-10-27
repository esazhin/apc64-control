"""T29: LabModule as a HostModule (s2 collaboration, s3 and s4 suppliers; inv2, inv11, inv12).

With service doubles: hooks and actions reach SessionService (activate, shift, view, end with the reason) and
led_filter drops pad LEDs only while a session plays in Custom view. With the real services: the module
registers with collect() and gives a gate policy where only the writer's token passes 0x14/0x18; the real section
compiler binds encoder and Tempo, and refuses an explicit encoder binding; only GuardedWriter holds the
capability in the whole object graph; a module opening a write through plain additions is refused."""
import types

import pytest

from _apc64_host.application.modules import collect
from _apc64_host.domain.controls import Encoder, FunctionButton, FunctionName, PadPos
from _apc64_host.domain.effects import Led, UnitView
from _apc64_host.domain.layout import ControlEvent, ModuleAction
from _apc64_host.domain.leds import LED_OFF
from _apc64_host.domain.outbound import CONTRACT1_POLICY, SysexCommand, WriteCapability
from _apc64_host.domain.unit_status import ReleaseReason
from _apc64_host.notation.compiler import compile_text
from _apc64_lab.application.conftest import EngineDouble, FakeBackups, FakeLibrary, FakeMemory, Wall, host_ports
from _apc64_lab.application.global_settings import GlobalSettingsService
from _apc64_lab.application.guarded_writer import GuardedWriter
from _apc64_lab.application.harmony_tracker import HarmonyTracker
from _apc64_lab.application.module import LabModule, check_scoped_writes
from _apc64_lab.application.ports import HostLink
from _apc64_lab.application.project_memory import ProjectMemory
from _apc64_lab.application.registry import DefinitionIndex, GeneratorRegistry
from _apc64_lab.application.section_compiler import LabSectionCompiler
from _apc64_lab.application.session_service import SessionService
from _apc64_lab.domain.lab_section import INTERVAL_CYCLE, WINDOW_SHIFT

TEMPO = FunctionButton(FunctionName.TEMPO)


class SessionDouble:
    def __init__(self):
        self.calls, self.suppressed = [], False

    def on_held(self, unit):
        self.calls.append(("held", unit))

    def on_layout_loaded(self, layout, section):
        self.calls.append(("loaded", getattr(layout, "id", layout), section))

    def on_view(self, view):
        self.calls.append(("view", view))

    def on_action(self, action, event):
        self.calls.append(("action", action, event))

    def end(self, reason):
        self.calls.append(("end", reason))

    def led_suppressed(self):
        return self.suppressed


def built(session=None):
    link = HostLink()
    capability = WriteCapability("lab guarded writer")
    memory, backups = FakeMemory(), FakeBackups()
    writer = GuardedWriter(memory, backups, capability, link, Wall())
    registry = GeneratorRegistry().load()
    index = DefinitionIndex()
    compiler = LabSectionCompiler(registry.generators, registry.schemes, None, index.record)
    tracker = HarmonyTracker(link=link)
    if session is None:
        session = SessionService(writer, backups, registry, link, control=memory, held_notes=tracker.held_notes,
                                 index=index, threaded=False)
    module = LabModule(link, writer, session, compiler, tracker)
    module.services = types.SimpleNamespace(
        projects=ProjectMemory(writer, backups, FakeLibrary(), registry, index, session),
        globals=GlobalSettingsService(writer))
    return module, capability


def test_hooks_and_actions_reach_the_session():   # T29, s2.c1, s3 supplier
    session = SessionDouble()
    module, _ = built(session)
    layout = compile_text("name: Tonnetz C\nlab:\n  generator: tonnetz\n  base: 48\n", "tonnetz-c.yaml",
                          sections=module.layout_sections()).layout
    module.on_layout_loaded(layout, layout.section("lab"))
    module.actions()[WINDOW_SHIFT](ControlEvent(steps=1))
    module.actions()[INTERVAL_CYCLE](ControlEvent(press=True))
    module.on_pad_mode(UnitView.CUSTOM)
    module.on_release(ReleaseReason.UNPLUG)
    assert session.calls == [("loaded", "tonnetz-c", layout.section("lab")),
                             ("action", WINDOW_SHIFT, ControlEvent(steps=1)),
                             ("action", INTERVAL_CYCLE, ControlEvent(press=True)),
                             ("view", UnitView.CUSTOM), ("end", ReleaseReason.UNPLUG)]


def test_pad_leds_are_dropped_only_while_a_session_plays_in_custom_view():   # s2.c8, §2.7 a4
    session = SessionDouble()
    module, _ = built(session)
    pad, tempo = Led(PadPos(1, 1), LED_OFF), Led(TEMPO, LED_OFF)
    assert module.led_filter(pad) is pad
    session.suppressed = True
    assert module.led_filter(pad) is None and module.led_filter(tempo) is tempo


def test_led_suppression_follows_the_real_session():
    module, _ = built()
    assert not module.session.led_suppressed()
    module.session.on_held(object())
    module.session.on_view(UnitView.CUSTOM)
    layout = compile_text("name: T\nlab:\n  generator: tonnetz\n  base: 48\n", "t.yaml",
                          sections=module.layout_sections()).layout
    module.on_layout_loaded(layout, layout.section("lab"))
    module.session.drain()
    assert module.session.led_suppressed()


def test_the_module_registers_and_only_the_token_opens_writes():   # inv2, a10, a29 twin
    module, capability = built()
    collection = collect([module])
    policy = collection.policy(CONTRACT1_POLICY)
    for write in (SysexCommand.PROJECT_WRITE, SysexCommand.GLOBAL_WRITE):
        assert not policy.allows(write) and not policy.allows(write, WriteCapability("look-alike"))
        assert policy.allows(write, capability)
    assert policy.allows(SysexCommand.PROJECT_READ) and policy.allows(SysexCommand.GLOBAL_READ)
    assert set(collection.actions) == {ModuleAction("lab", WINDOW_SHIFT), ModuleAction("lab", INTERVAL_CYCLE)}
    assert set(collection.sections) == {"lab"}


def test_the_real_section_compiler_binds_encoder_and_tempo_and_refuses_a_clash():   # s4 supplier
    module, _ = built()
    sections = module.layout_sections()
    layout = compile_text("name: T\nlab:\n  generator: tonnetz\n", "t.yaml", sections=sections).layout
    assert layout.page(1).encoder.module_action == ModuleAction("lab", WINDOW_SHIFT)
    clash = compile_text("name: T\ndevices: {mpc: MPC}\npages:\n  1:\n    encoder: cc 30 to mpc\n"
                         "lab:\n  generator: tonnetz\n", "t.yaml", sections=sections)
    assert not clash.valid and any("encoder" in i.message() for i in clash.issues)


def test_only_the_guarded_writer_holds_the_capability():   # §7.1, inv2 (the object graph, after bind)
    module, capability = built()
    module.bind(host_ports(EngineDouble()))
    holders = _holders(module, capability)
    assert holders and {type(h).__name__ for h in holders} == {"GuardedWriter"}


def test_a_module_opening_a_write_through_plain_additions_is_refused():   # inv2 hardening
    module, _ = built()

    class Leaky(type(module)):
        def outbound_additions(self):
            return frozenset({SysexCommand.PROJECT_READ, SysexCommand.PROJECT_WRITE})
    with pytest.raises(ValueError, match="through plain additions"):
        Leaky(module._link, module._writer, module.session, module.compiler)

    class Unscoped(type(module)):
        def outbound_scoped(self):
            return {SysexCommand.PROJECT_WRITE: WriteCapability("a"), SysexCommand.GLOBAL_WRITE: WriteCapability("b")}
    with pytest.raises(ValueError, match="one capability"):
        check_scoped_writes(Unscoped.__new__(Unscoped))


def _holders(root, target):
    """Every object in the graph reachable from `root` that keeps `target` as an attribute or item."""
    seen, found, todo = set(), [], [root]
    while todo:
        obj = todo.pop()
        if id(obj) in seen or obj is None or isinstance(obj, (str, bytes, int, float, bool, type)):
            continue
        seen.add(id(obj))
        children = []
        if isinstance(obj, dict):
            children = list(obj.keys()) + list(obj.values())
        elif isinstance(obj, (list, tuple, set, frozenset)):
            children = list(obj)
        else:
            if hasattr(obj, "__self__"):
                children.append(obj.__self__)
            closure = getattr(obj, "__closure__", None) or ()
            children += [cell.cell_contents for cell in closure if _filled(cell)]
            attrs = getattr(obj, "__dict__", None)
            if attrs is None and hasattr(obj, "__slots__"):
                attrs = {s: getattr(obj, s, None) for s in obj.__slots__}
            if attrs and (type(obj).__module__.startswith("_apc64") or isinstance(obj, types.SimpleNamespace)):
                children += list(attrs.values())
                if any(value is target for value in attrs.values()) and obj is not target:
                    found.append(obj)
        todo += [c for c in children if c is not target]
    return found


def _filled(cell):
    try:
        cell.cell_contents
        return True
    except ValueError:
        return False
