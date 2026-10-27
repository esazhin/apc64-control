"""compile_text against the acceptance values of contract §4.2 (T7)."""
from _apc64_host.domain.controls import PadPos, Strip, TrackButton, Transport, TransportName
from _apc64_host.domain.issues import Severity
from _apc64_host.domain.layout import (
    AftertouchPolicy, BindingMode, Layer, MessageKind, PressVelocity, UnitPortRole,
)
from _apc64_host.notation.compiler import PORTS_NOT_CHECKED, compile_text

JAM = """name: Jam
devices: {mpc: MPC Live III MIDI 1}
pages:
  1 Drums:
    pads r1c1-r2c8: notes from 36 on mpc ch 10
banks:
  1 Mix:
    strips 1-8: cc 20-27 on mpc ch 1
"""
PORTS = ["MPC Live III MIDI 1", "USB MIDI Interface MIDI 1", "Bitwig Studio In"]


def messages(result):
    return [issue.message() for issue in result.issues]


def numbered(*lines, start=1):
    """A layout whose interesting lines sit at known line numbers: filler comments pad the gaps."""
    out, n = [], start
    for target, text in lines:
        while n < target:
            out.append("    # …")
            n += 1
        out.append(text)
        n += 1
    return "\n".join(out) + "\n"


def test_the_eight_line_jam_layout_is_valid_with_its_counts():   # A34, d182
    assert len(JAM.splitlines()) == 8
    result = compile_text(JAM, "jam.yaml", PORTS)
    assert result.valid and result.issues == ()
    assert result.summary() == "valid: 1 page, 1 bank, 16 pads, 8 strips bound"
    layout = result.layout
    assert layout.id == "jam" and layout.display_name == "Jam"
    pad = layout.page(1).binding(Layer.BASE, PadPos(2, 8)).actions[0]
    assert (pad.kind, pad.number, pad.channel, pad.value) == (MessageKind.NOTE, 51, 10, PressVelocity())
    assert layout.bank(1).binding(Layer.BASE, Strip(8)).position.number == 27


def test_without_a_port_list_the_ports_are_not_checked():   # s29
    result = compile_text(JAM, "jam.yaml")
    assert result.valid and not result.ports_checked
    assert result.summary() == f"valid: 1 page, 1 bank, 16 pads, 8 strips bound ({PORTS_NOT_CHECKED})"


def test_a_device_naming_an_apc64_port_is_refused():   # A33
    text = "name: Apc\ndevices:\n  apc: APC64 Notes (APC64)\npages:\n  1:\n    pad r1c1: note 36\n"
    assert messages(compile_text(text, "apc.yaml")) == [
        "apc.yaml line 3: device apc targets an APC64 port; the host never sends to the APC64's own ports, "
        "choose another port"]


def test_page_9_is_refused_with_the_scene_button_count():   # A36
    text = numbered((1, "name: Jam"), (2, "devices: {mpc: MPC}"), (3, "pages:"), (4, "  1 Drums:"),
                    (5, "    pad r1c1: note 36"), (40, "  9 Extra:"), (41, "    pad r1c1: note 40"))
    assert messages(compile_text(text, "jam.yaml")) == [
        "jam.yaml line 40, page 9: the APC64 has 8 scene buttons, so pages are 1–8"]


def test_a_missing_colon_names_the_line_the_control_and_the_fix():   # A38
    text = numbered((1, "name: Jam"), (2, "devices: {mpc: MPC}"), (3, "pages:"), (4, "  1 Drums:"),
                    (12, "    pads r1c1-r1c8 notes 36"))
    assert messages(compile_text(text, "jam.yaml")) == [
        "jam.yaml line 12, pads r1c1-r1c8: expected ':' after the control name; write \"pads r1c1-r1c8: notes 36\""]


def test_all_errors_come_at_once_in_line_order():   # A39, d113
    text = numbered((1, "name: Jam"), (2, "devices: {mpc: MPC}"), (3, "pages:"), (4, "  1 Drums:"),
                    (8, "    pad r9c1: note 36"), (14, "    pad r1c1: note 36 on mcp"))
    assert messages(compile_text(text, "jam.yaml")) == [
        "jam.yaml line 8, pad r9c1: no such pad, pads are r1c1–r8c8",
        "jam.yaml line 14: unknown device mcp, declared devices: mpc"]


def test_two_ranges_on_one_control_are_refused_naming_both_lines():   # A40, d74
    text = numbered((1, "name: Jam"), (2, "devices: {mpc: MPC}"), (3, "pages:"), (4, "  1 Drums:"),
                    (10, "    pads r1c1-r1c8: notes from 36"), (11, "    pads r1c5-r2c4: cc from 1"))
    assert messages(compile_text(text, "jam.yaml")) == [
        "jam.yaml line 11: lines 10 and 11 both bind pads r1c5–r1c8 on page 1 base layer; keep one"]


def test_a_single_entry_overrides_the_range_covering_it():   # A41, d73
    text = JAM.replace("    pads r1c1-r2c8: notes from 36 on mpc ch 10",
                       "    pads r1c1-r1c8: notes from 36\n    pad r1c3: cc 64")
    page = compile_text(text, "jam.yaml").layout.page(1)
    assert page.binding(Layer.BASE, PadPos(1, 3)).actions[0].kind is MessageKind.CC
    assert page.binding(Layer.BASE, PadPos(1, 3)).actions[0].number == 64
    assert page.binding(Layer.BASE, PadPos(1, 4)).actions[0].number == 39


def test_the_same_issue_renders_identically_every_time():   # A57, d115
    text = numbered((1, "name: Jam"), (2, "devices: {mpc: MPC}"), (3, "pages:"), (4, "  1 Drums:"),
                    (7, "    pad r1c1: note 36 on nope"))
    assert messages(compile_text(text, "jam.yaml")) == messages(compile_text(text, "jam.yaml")) == [
        "jam.yaml line 7: unknown device nope, declared devices: mpc"]


def test_an_ambiguous_port_part_lists_both_ports():   # A84, d59
    text = JAM.replace("{mpc: MPC Live III MIDI 1}", "{mpc: MIDI 1}")
    assert messages(compile_text(text, "jam.yaml", PORTS)) == [
        'jam.yaml line 2, device mpc: "MIDI 1" matches MPC Live III MIDI 1 and USB MIDI Interface MIDI 1; '
        "write the full name"]
    assert compile_text(text.replace("MIDI 1}", "MPC Live}"), "jam.yaml", PORTS).valid


def test_a_device_with_no_port_now_still_loads_with_a_warning():   # d58
    result = compile_text(JAM, "jam.yaml", ["Bitwig Studio In"])
    assert result.valid
    assert [w.message() for w in result.warnings] == [
        'jam.yaml line 2, device mpc: no port matches "MPC Live III MIDI 1" now; '
        "its bindings show (missing) until the port appears"]


def test_two_device_names_may_mean_one_port():   # A85, d60
    text = """name: Kit
devices:
  drums: MPC Live III MIDI 1
  keys: MPC Live III MIDI 1
pages:
  1:
    pad r1c1: note 36 on drums ch 10
    pad r1c2: note 60 on keys ch 1
"""
    result = compile_text(text, "kit.yaml", PORTS)
    assert result.valid and set(result.layout.devices) == {"drums", "keys"}


def test_a_strip_toggle_is_refused():   # A49, d93
    text = numbered((1, "name: Jam"), (2, "devices: {mpc: MPC}"), (3, "banks:"), (4, "  1 Mix:"),
                    (22, "    strip 1: cc 20 toggle"))
    assert messages(compile_text(text, "jam.yaml")) == [
        'jam.yaml line 22, strip 1: a strip position cannot be a toggle; remove "toggle"']


def test_a_long_page_name_is_valid_with_a_warning():   # A43, d114
    text = JAM.replace("  1 Drums:", "  1 Drums:\n    pad r8c8: note 99\n  2 Drums and Percussion Kit:")
    result = compile_text(text, "jam.yaml")
    assert result.valid
    assert [(w.severity, w.message()) for w in result.warnings] == [
        (Severity.WARNING, 'jam.yaml line 6, page 2: page name longer than 14 characters, OLED shows "Drums and Perc"')]


def test_a_mismatched_range_count_says_how_to_write_it():
    text = JAM.replace("cc 20-27", "cc 20-26")
    assert messages(compile_text(text, "jam.yaml")) == [
        "jam.yaml line 8, strips 1-8: cc 20-26 is 7 values for 8 controls; write cc 20-27 or cc from 20"]


def test_navigation_controls_and_strips_in_pages_are_refused():
    for line, problem in (("    scene 1: note 36", "scene 1 selects page 1 and cannot be bound"),
                          ("    strip 1: cc 20", "strips are bound in banks"),
                          ("    shift: {encoder: cc 30}", "Shift + encoder browses layouts and cannot be bound")):
        text = JAM.replace("    pads r1c1-r2c8: notes from 36 on mpc ch 10", line)
        assert [i.problem for i in compile_text(text, "jam.yaml").issues] == [problem], line


def test_unknown_top_level_keys_point_to_the_right_place():
    text = JAM + "pad r1c1: note 36\n"
    issue = compile_text(text, "jam.yaml").issues[0]
    assert issue.problem == "unknown key 'pad r1c1'" and "under a page" in issue.fix
    assert "did you mean 'pages:'" in compile_text(JAM + "page: {}\n", "jam.yaml").issues[0].fix


def test_a_full_layout_with_every_form_compiles():
    text = """# A layout with every form
name: Studio
device: mpc
devices:
  mpc: {port: MPC Live III MIDI 1, ch: 10}
  bitwig: Bitwig Studio In
pages:
  1 Drums:
    pads r1c1-r2c8: notes from C1 colour red
    pad r1c3: note 38 velocity 100 label "Snare"
    track 1: cc 20 on bitwig ch 1 toggle feedback colour green
    tracks 2-4: cc 21-23 on bitwig ch 1
    play: [cc 118 on bitwig ch 1, program 5]
    encoder: cc 30
    encoder press: note 99
    shift:
      pad r1c1: note 48
      play: cc 119 on bitwig ch 1
  page 2:
    name: Keys
    pad r1c1: {send: note 50, colour: blue, mode: toggle}
banks:
  1 Mix:
    strips 1-8: cc from 20 on bitwig ch 1
  bank 5 FX:
    strip 3: pitchbend on bitwig ch 2 touch note 60 bipolar
routing:
  notes: mpc ch 2 aftertouch pressure transpose 12 remap 36>38
  custom: {device: mpc, ch: 3}
"""
    result = compile_text(text, "studio.yaml", PORTS)
    assert result.issues == () and result.valid, messages(result)
    layout = result.layout
    page1, page2 = layout.page(1), layout.page(2)
    assert page1.binding(Layer.BASE, PadPos(1, 1)).actions[0].channel == 10
    assert page1.binding(Layer.BASE, PadPos(1, 3)).label == "Snare"
    track = page1.binding(Layer.BASE, TrackButton(1))
    assert track.mode is BindingMode.TOGGLE and track.feedback.number == 20 and track.feedback.device == "bitwig"
    assert [a.kind for a in page1.binding(Layer.BASE, Transport(TransportName.PLAY)).actions] == [
        MessageKind.CC, MessageKind.PROGRAM]
    assert page1.encoder.actions[0].number == 30
    assert page1.binding(Layer.SHIFT, PadPos(1, 1)).actions[0].number == 48
    assert page2.name == "Keys" and page2.binding(Layer.BASE, PadPos(1, 1)).toggle
    assert layout.bank(5).name == "FX" and layout.bank(5).binding(Layer.BASE, Strip(3)).touch.number == 60
    notes = layout.routing[UnitPortRole.NOTES]
    assert (notes.channel, notes.aftertouch, notes.transpose, notes.remap) == (
        2, AftertouchPolicy.CHANNEL_PRESSURE, 12, ((36, 38),))
    assert layout.routing[UnitPortRole.CUSTOM].channel == 3
    assert result.counts.encoders == 1 and result.counts.routes == 2


def test_the_source_map_records_ranges_singles_and_blocks():
    text = JAM.replace("    pads r1c1-r2c8: notes from 36 on mpc ch 10",
                       "    pads r1c1-r1c8: notes from 36  # bass line\n    pad r1c3: cc 64")
    sources = compile_text(text, "jam.yaml").sources
    key = ("page", 1, Layer.BASE, PadPos(1, 3))
    assert sources.singles[key].line == 6 and sources.winners[key].line == 6
    assert sources.from_ranges[key].actions[0].number == 38
    block = sources.blocks[("page", 1, Layer.BASE)]
    assert (block.line, block.entry_column, block.end_line, block.flow) == (4, 4, 6, False)


def test_fifty_full_layouts_compile():   # A35 (notation side)
    controls = ["pads r1c1-r8c8: notes from 0", "tracks 1-8: cc from 0", "trackctls 1-8: cc from 8"]
    shift = ["pads r1c1-r8c8: cc from 0", "tracks 1-8: cc from 64", "trackctls 1-8: cc from 72"]
    pages = "".join(f"  {p} P{p}:\n" + "".join(f"    {c}\n" for c in controls) + "    shift:\n"
                    + "".join(f"      {c}\n" for c in shift) for p in range(1, 9))
    banks = "".join(f"  {b} B{b}:\n    strips 1-8: cc from {b * 10}\n    shift:\n      strips 1-8: cc from 100\n"
                    for b in range(1, 7))
    for k in range(50):
        text = f"name: Layout {k}\ndevices: {{mpc: MPC}}\npages:\n{pages}banks:\n{banks}"
        result = compile_text(text, f"layout-{k}.yaml")
        assert result.valid and result.counts.pads == 1024 and result.counts.strips == 96
