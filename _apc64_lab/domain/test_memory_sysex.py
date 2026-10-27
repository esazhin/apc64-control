"""Golden round-trips of the captured dumps through the lab codec (contract a19, s7 supplier, T4)."""
from _apc64_host.domain.effects import UnitView
from _apc64_host.domain.outbound import SysexCommand
from _apc64_host.protocol import sysex as host_sysex
from _apc64_lab.domain.memory import Slot
from _apc64_lab.domain.memory_sysex import (
    Malformed, PROJECT_FRAME_SIZE, dump_slot, global_read_frame, global_write_frame, pack7, parse_global_dump,
    parse_project_dump, project_read_frame, project_write_frame, unpack7, view_request_frame,
)
from _apc64_lab.domain.records import GlobalSettings, ProjectRecord

from .conftest import snapshot_frames


def test_the_factory_project_dump_round_trips_byte_for_byte(factory_frame):   # a19
    assert len(factory_frame) == PROJECT_FRAME_SIZE
    slot, record = parse_project_dump(factory_frame)
    assert slot == 0 and len(record.to_raw()) == 880
    assert project_write_frame(slot, record) == factory_frame


def test_every_captured_slot_0_to_24_round_trips():   # a19, s7 'every slot 0–24 frame'
    frames = snapshot_frames()
    assert len(frames) == 25
    for expected_slot, frame in enumerate(frames):
        slot, record = parse_project_dump(frame)
        assert slot == expected_slot and dump_slot(frame) == expected_slot
        assert project_write_frame(slot, record) == frame


def test_the_global_settings_dump_round_trips_byte_for_byte(global_frame):   # a19
    settings = parse_global_dump(global_frame)
    assert isinstance(settings, GlobalSettings)
    assert global_write_frame(settings) == global_frame


def test_the_lab_packing_matches_the_hosts(factory_frame):
    raw = parse_project_dump(factory_frame)[1].to_raw()
    assert pack7(raw) == host_sysex.pack7(raw) and unpack7(pack7(raw)) == raw
    odd = bytes(range(256)) * 3 + bytes(112)
    assert unpack7(pack7(odd)) == odd


def test_request_frames_are_the_documented_bytes():   # s10.c1, s10.c7
    assert project_read_frame(Slot(7)).hex(" ") == "f0 47 00 53 13 00 01 07 f7"
    assert global_read_frame().hex(" ") == "f0 47 00 53 17 00 00 f7"
    assert view_request_frame(UnitView.CUSTOM).hex(" ") == "f0 47 00 53 19 00 01 09 f7"


def test_the_gate_classifies_every_lab_frame(factory_frame, global_frame):
    record = parse_project_dump(factory_frame)[1]
    settings = parse_global_dump(global_frame)
    assert host_sysex.command_of(project_read_frame(Slot(3))) is SysexCommand.PROJECT_READ
    assert host_sysex.command_of(project_write_frame(Slot(3), record)) is SysexCommand.PROJECT_WRITE
    assert host_sysex.command_of(global_read_frame()) is SysexCommand.GLOBAL_READ
    assert host_sysex.command_of(global_write_frame(settings)) is SysexCommand.GLOBAL_WRITE
    assert host_sysex.command_of(view_request_frame()) is SysexCommand.PAD_MODE


def test_a_short_dump_is_malformed_with_its_unpacked_length():   # A51 (codec half), d66
    raw = bytes(700)
    body = bytes([7]) + pack7(raw)
    frame = bytes([0xF0, 0x47, 0x00, 0x53, 0x14, len(body) >> 7, len(body) & 0x7F]) + body + b"\xf7"
    malformed = parse_project_dump(frame)
    assert malformed == Malformed(700, 880)
    assert malformed.text("slot 7") == "slot 7 read returned 700 bytes, expected 880"


def test_a_truncated_frame_or_another_command_is_malformed(factory_frame, global_frame):
    assert isinstance(parse_project_dump(factory_frame[:500] + b"\xf7"), Malformed)
    assert isinstance(parse_project_dump(global_frame), Malformed)
    assert isinstance(parse_global_dump(factory_frame), Malformed)
    assert dump_slot(global_frame) is None


def test_odd_rgb_values_survive_the_codec():   # a3 (byte-exact read-back of 1, 127, 128, 255)
    record = ProjectRecord(bytes([1, 127, 128, 255] * 220))
    assert parse_project_dump(project_write_frame(Slot(0), record))[1] == record
