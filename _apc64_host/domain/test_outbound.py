from _apc64_host.domain.outbound import (
    CONTRACT1_POLICY, DeviceLogEntry, DeviceLogOutcome, OutboundPolicy, SysexCommand,
)


def test_contract1_policy_refuses_project_and_global_reads_and_writes():
    for command in (SysexCommand.PROJECT_READ, SysexCommand.PROJECT_WRITE, SysexCommand.GLOBAL_READ,
                    SysexCommand.GLOBAL_WRITE, SysexCommand.UNKNOWN_SYSEX):
        assert not CONTRACT1_POLICY.allows(command)


def test_contract1_policy_allows_identity_handshake_oled_and_leds():
    for command in (SysexCommand.IDENTITY_REQUEST, SysexCommand.OLED_TEXT, SysexCommand.PAD_MODE,
                    SysexCommand.DRUM_FLAG, SysexCommand.DAW_MODE, SysexCommand.CHANNEL_MESSAGE):
        assert CONTRACT1_POLICY.allows(command)


def test_a_module_can_widen_the_policy_without_editing_it():
    wider = CONTRACT1_POLICY.with_additions({SysexCommand.PROJECT_WRITE})
    assert wider.allows(SysexCommand.PROJECT_WRITE) and not CONTRACT1_POLICY.allows(SysexCommand.PROJECT_WRITE)
    assert isinstance(wider, OutboundPolicy)


def test_a_refused_frame_is_a_hazard_named_for_the_activity_list():
    entry = DeviceLogEntry(1.0, b"\xf0\x47\x00\x53\x14", DeviceLogOutcome.REFUSED, SysexCommand.PROJECT_WRITE)
    assert entry.hazard and entry.refusal_text() == "refused: project write (0x14)"
