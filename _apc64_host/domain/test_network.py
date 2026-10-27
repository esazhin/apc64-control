import pytest

from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.network import AllowedNetworks, ClientAddress


def test_home_network_clients_are_allowed_and_public_ones_are_not():
    allowed = AllowedNetworks.default()
    for client in ("127.0.0.1", "::1", "192.168.1.23", "10.1.2.3", "172.20.0.5", "fd00::23", "fe80::1%eth0",
                   "::ffff:192.168.1.40"):
        assert allowed.allows(client), client
    for client in ("203.0.113.5", "8.8.8.8", "2001:db8::1", "100.64.0.1", "not an address"):
        assert not allowed.allows(client), client


def test_ipv4_mapped_addresses_are_unwrapped():
    assert str(ClientAddress.parse("::ffff:192.168.1.40")) == "192.168.1.40"
    with pytest.raises(DomainInvariantError):
        ClientAddress.parse("nope")


def test_allowed_networks_parse_from_config_text():
    allowed = AllowedNetworks.parse("192.168.0.0/16, 100.64.0.0/10")
    assert allowed.allows("100.64.0.1") and not allowed.allows("127.0.0.1")
    with pytest.raises(DomainInvariantError) as raised:
        AllowedNetworks.parse("192.168.0.0/16, home")
    assert raised.value.field == "allowed networks"
    with pytest.raises(DomainInvariantError):
        AllowedNetworks.parse(" ")
