import pytest

from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.oled import OledText
from _apc64_host.domain.outbound import SysexCommand
from _apc64_host.protocol.conftest import FIXTURES, capture
from _apc64_host.protocol.sysex import (
    IDENTITY_REQUEST, akai_frame, command_of, daw_off, daw_on, encode_view_report, handshake_frames,
    identity_reply, oled_frames, pack7, parse_akai, parse_identity, parse_oled, unpack7, view_report,
)


def hexes(*frames):
    return [" ".join(f"{b:02X}" for b in f) for f in frames]


def test_the_handshake_and_daw_mode_frames_are_byte_exact_to_the_spec():
    assert hexes(*handshake_frames()) == ["F0 47 00 53 1B 00 01 00 F7", "F0 47 00 53 19 00 01 00 F7",
                                          "F0 7E 7F 06 01 F7"]
    assert hexes(daw_on(), daw_off()) == ["F0 47 00 53 1C 00 01 01 F7", "F0 47 00 53 1C 00 01 00 F7"]


def test_oled_rows_are_padded_to_14_characters_in_the_probes_format():
    row0, row1 = oled_frames(OledText("Jam", "P1 Drums | B1"))
    assert row0 == bytes([0xF0, 0x47, 0x00, 0x53, 0x10, 0x00, 16, 0]) + b"Jam" + b" " * 11 + b"\x00\xf7"
    assert parse_oled(row1) == (1, "P1 Drums | B1")
    assert parse_oled(oled_frames(OledText.blank())[0]) == (0, "")


def test_the_identity_reply_of_this_unit_parses_to_an_apc64_on_known_firmware():
    port, reply = capture("daw-mode-views-velocity-aftertouch-2026-10-23.log")[0]
    identity = parse_identity(reply)
    assert port == "DAW" and identity.is_apc64 and str(identity.firmware) == "1.2.1.6"
    assert identity.serial == "000000000000000" and identity.firmware_warning is None
    assert identity_reply() == reply


def test_other_firmware_is_warned_about_and_other_products_are_not_an_apc64():
    assert parse_identity(identity_reply(firmware=(1, 2, 2, 0))).firmware_warning == "untested firmware 1.2.2.0"
    other = parse_identity(identity_reply(product=0x51))
    assert not other.is_apc64 and other.refusal == "not an APC64 (product 0x51)"
    assert parse_identity(daw_on()) is None and parse_identity(b"\x90\x00\x7f") is None


def test_pad_mode_reports_become_unit_views():
    reports = [view_report(raw) for _, raw in capture("daw-mode-views-velocity-aftertouch-2026-10-23.log")
               if raw[:5] == bytes.fromhex("F047005319")]
    assert reports[0] is UnitView.NOTE
    for view in UnitView:
        assert view_report(encode_view_report(view)) is view
    assert view_report(akai_frame(0x19, b"\x04")) is None and view_report(daw_on()) is None


@pytest.mark.parametrize("frame, command", [
    (akai_frame(0x10, b"\x00abc\x00"), SysexCommand.OLED_TEXT),
    (akai_frame(0x13, b"\x00"), SysexCommand.PROJECT_READ),
    (akai_frame(0x14, b"\x00" * 10), SysexCommand.PROJECT_WRITE),
    (akai_frame(0x17), SysexCommand.GLOBAL_READ),
    (akai_frame(0x18, b"\x00" * 64), SysexCommand.GLOBAL_WRITE),
    (akai_frame(0x19, b"\x00"), SysexCommand.PAD_MODE),
    (akai_frame(0x1B, b"\x00"), SysexCommand.DRUM_FLAG),
    (akai_frame(0x1C, b"\x01"), SysexCommand.DAW_MODE),
    (IDENTITY_REQUEST, SysexCommand.IDENTITY_REQUEST),
    (bytes([0x96, 0x00, 0x05]), SysexCommand.CHANNEL_MESSAGE),
    (bytes([0xB0, 0x70, 0x03]), SysexCommand.CHANNEL_MESSAGE),
    (bytes([0xE0, 0x00, 0x40]), SysexCommand.CHANNEL_MESSAGE),
])
def test_command_of_classifies_each_kind_of_outbound_frame(frame, command):
    assert command_of(frame) is command


@pytest.mark.parametrize("frame", [
    b"",
    bytes([0x96, 0x00]),                                            # short
    bytes([0x96, 0x00, 0x05]) + akai_frame(0x14, b"\x00"),          # a write smuggled behind a note
    akai_frame(0x10, b"\x00") + akai_frame(0x14, b"\x00"),          # two frames in one
    bytes([0xF0, 0x47, 0x00, 0x53, 0x14, 0x00, 0x05, 0x00, 0xF7]),  # length field does not match
    bytes([0xF0, 0x00, 0x20, 0x29, 0x02, 0xF7]),                    # another manufacturer
    akai_frame(0x42, b"\x00"),                                      # unknown Akai command
    bytes([0xF8]),
])
def test_anything_but_exactly_one_known_message_is_unknown_and_refusable(frame):
    assert command_of(frame) is SysexCommand.UNKNOWN_SYSEX


def test_the_recorded_project_and_global_dumps_classify_as_writes():
    project = (FIXTURES / "apc64-factory-project.syx").read_bytes()
    settings = (FIXTURES / "apc64-global-settings-2026-10-22.syx").read_bytes()
    assert command_of(project) is SysexCommand.PROJECT_WRITE
    assert command_of(settings) is SysexCommand.GLOBAL_WRITE


def test_seven_bit_packing_round_trips_the_factory_project():
    project = (FIXTURES / "apc64-factory-project.syx").read_bytes()
    command, data = parse_akai(project)
    raw = unpack7(data[1:])
    assert command == 0x14 and len(raw) == 880
    assert pack7(raw) == data[1:]
