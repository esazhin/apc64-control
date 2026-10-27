"""Contract 2 (T8, a10, inv2): issuer-scoped allowances in the outbound policy. Contract 1's policy and its
tests are unchanged; these cases are additive."""
import copy

import pytest

from _apc64_host.domain.outbound import CONTRACT1_POLICY, OutboundPolicy, SysexCommand, WriteCapability

WRITES = (SysexCommand.PROJECT_WRITE, SysexCommand.GLOBAL_WRITE)


def lab_policy(token):
    return CONTRACT1_POLICY.with_additions({SysexCommand.PROJECT_READ, SysexCommand.GLOBAL_READ}) \
        .with_scoped(WRITES, token)


def test_a_scoped_write_passes_only_with_its_own_token():   # a10, inv2
    token = WriteCapability()
    policy = lab_policy(token)
    for command in WRITES:
        assert policy.allows(command, token)
        assert not policy.allows(command)
        assert not policy.allows(command, WriteCapability())       # a look-alike is not the token
        assert not policy.allows(command, object())


def test_reads_and_contract1_commands_pass_for_everyone():
    policy = lab_policy(WriteCapability())
    assert policy.allows(SysexCommand.PROJECT_READ) and policy.allows(SysexCommand.GLOBAL_READ)
    assert policy.allows(SysexCommand.OLED_TEXT) and policy.allows(SysexCommand.CHANNEL_MESSAGE)
    assert not policy.allows(SysexCommand.UNKNOWN_SYSEX)


def test_adding_a_scoped_command_to_everyone_does_not_open_it():
    token = WriteCapability()
    policy = lab_policy(token).with_additions({SysexCommand.PROJECT_WRITE})
    assert not policy.allows(SysexCommand.PROJECT_WRITE) and policy.allows(SysexCommand.PROJECT_WRITE, token)


def test_the_token_is_one_object_that_copies_as_itself():
    token = WriteCapability()
    assert copy.copy(token) is token and copy.deepcopy(token) is token
    assert token != WriteCapability()
    with pytest.raises(TypeError):
        CONTRACT1_POLICY.with_scoped(WRITES, "token")


def test_without_a_lab_the_contract1_policy_is_as_built():   # a29: contract 1 keeps its meaning
    assert CONTRACT1_POLICY.scoped == () and CONTRACT1_POLICY.scoped_commands == frozenset()
    assert CONTRACT1_POLICY == OutboundPolicy(CONTRACT1_POLICY.allowed)
    for command in (SysexCommand.PROJECT_READ, *WRITES, SysexCommand.GLOBAL_READ):
        assert not CONTRACT1_POLICY.allows(command) and not CONTRACT1_POLICY.allows(command, WriteCapability())
