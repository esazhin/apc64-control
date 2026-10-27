import pytest

from _apc64_host.application.modules import ModuleCollection, collect
from _apc64_host.domain.outbound import CONTRACT1_POLICY, SysexCommand


class FakeLab:
    name = "layout-lab"

    def __init__(self, route="lab-router", panel="lab/panel.js"):
        self._route, self._panel = route, panel

    def outbound_additions(self):
        return frozenset({SysexCommand.PROJECT_WRITE})

    def router(self):
        return self._route

    def panel(self):
        return self._panel


def test_no_modules_add_nothing_and_leave_the_contract1_policy():
    collection = collect([])
    assert collection == ModuleCollection()
    assert collection.policy_additions == frozenset() and collection.routers == ()
    assert collection.policy(CONTRACT1_POLICY) == CONTRACT1_POLICY


def test_a_module_adds_exactly_its_command_route_and_panel():
    collection = collect([FakeLab()])
    assert collection.policy_additions == {SysexCommand.PROJECT_WRITE}
    assert collection.routers == ("lab-router",) and collection.panels == (("layout-lab", "lab/panel.js"),)
    assert collection.policy(CONTRACT1_POLICY).allows(SysexCommand.PROJECT_WRITE)
    assert not CONTRACT1_POLICY.allows(SysexCommand.PROJECT_WRITE)


def test_modules_without_routes_or_panels_and_bad_registrations():
    assert collect([FakeLab(route=None, panel=None)]).routers == ()
    with pytest.raises(ValueError):
        collect([FakeLab(), FakeLab()])
    with pytest.raises(TypeError):
        collect([object()])
