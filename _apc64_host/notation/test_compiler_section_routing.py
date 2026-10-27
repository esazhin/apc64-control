"""Contract 2 (§2.7 q2): a module section may imply a default routing rule and its device. The layout's
own routing line and device declaration win; without such a section the compile results are contract 1's."""
from _apc64_host.domain.layout import (
    AftertouchPolicy, DeviceDecl, RoutingRule, SectionResult, UnitPortRole,
)
from _apc64_host.notation.compiler import compile_text

CUSTOM = UnitPortRole.CUSTOM
DEFAULT_RULE = RoutingRule(CUSTOM, "lab-default", 2, AftertouchPolicy.PASS)
DEFAULT_DEVICE = DeviceDecl("lab-default", "MPC Live III MIDI 1")


class Implies:
    def __init__(self, issues=()):
        self.issues = tuple(issues)

    def compile(self, section, file, existing):
        return SectionResult("value", {}, self.issues, routing={CUSTOM: DEFAULT_RULE},
                             devices={"lab-default": DEFAULT_DEVICE})


def test_an_implied_rule_joins_a_layout_without_one():
    layout = compile_text("name: G\nlab:\n  x: 1\n", "g.yaml", sections={"lab": Implies()}).layout
    assert layout.routing == {CUSTOM: DEFAULT_RULE} and layout.devices["lab-default"] == DEFAULT_DEVICE


def test_the_layouts_own_rule_and_device_win():
    own = ("name: G\ndevices: {synth: Synth 1, lab-default: Other port}\nrouting:\n  notes: synth ch 1\n"
           "lab:\n  x: 1\n")
    layout = compile_text(own, "g.yaml", sections={"lab": Implies()}).layout
    assert layout.routing[CUSTOM] == DEFAULT_RULE                       # Custom was not routed by the layout …
    assert str(layout.devices["lab-default"].pattern) == "Other port"   # … but its own declaration of the name wins
    routed = own.replace("notes: synth ch 1", "custom: synth ch 4")
    layout = compile_text(routed, "g.yaml", sections={"lab": Implies()}).layout
    assert layout.routing[CUSTOM].device == "synth" and int(layout.routing[CUSTOM].channel) == 4


def test_a_section_without_routing_changes_nothing():
    class Plain:
        def compile(self, section, file, existing):
            return SectionResult("value")
    text = "name: G\ndevices: {mpc: MPC}\nrouting:\n  custom: mpc ch 1\nlab:\n  x: 1\n"
    with_plain = compile_text(text, "g.yaml", sections={"lab": Plain()}).layout
    assert with_plain.routing[CUSTOM].device == "mpc" and set(with_plain.devices) == {"mpc"}
