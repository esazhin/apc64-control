"""Which clients may use the host: loopback and private ranges, no login (contract inv23, d155–d158)."""
import ipaddress
from dataclasses import dataclass

from .issues import DomainInvariantError

DEFAULT_NETWORKS = (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
    "::1/128", "fe80::/10", "fc00::/7",
)


@dataclass(frozen=True)
class ClientAddress:
    """A client's IP address; IPv4-mapped IPv6 (::ffff:a.b.c.d) is unwrapped and a zone id dropped."""
    address: ipaddress.IPv4Address | ipaddress.IPv6Address

    @classmethod
    def parse(cls, text: str) -> "ClientAddress":
        raw = str(text).strip().strip("[]").split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            raise DomainInvariantError("client", f"'{text}' is not an IP address", "pass the peer address") from None
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return cls(address)

    def __str__(self) -> str:
        return str(self.address)


@dataclass(frozen=True)
class AllowedNetworks:
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]

    @classmethod
    def default(cls) -> "AllowedNetworks":
        return cls.parse(",".join(DEFAULT_NETWORKS))

    @classmethod
    def parse(cls, text: str) -> "AllowedNetworks":
        """Comma- or space-separated CIDR ranges, e.g. '192.168.0.0/16, fd00::/8, 100.64.0.0/10'."""
        networks = []
        for item in str(text).replace(",", " ").split():
            try:
                networks.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                raise DomainInvariantError("allowed networks", f"'{item}' is not a network",
                                           "write CIDR ranges such as 192.168.0.0/16 or fd00::/8") from None
        if not networks:
            raise DomainInvariantError("allowed networks", "no network is allowed",
                                       "list at least one range, e.g. 127.0.0.0/8")
        return cls(tuple(networks))

    def allows(self, client: ClientAddress | str) -> bool:
        if not isinstance(client, ClientAddress):
            try:
                client = ClientAddress.parse(client)
            except DomainInvariantError:
                return False
        return any(client.address.version == n.version and client.address in n for n in self.networks)

    def __str__(self) -> str:
        return ", ".join(str(n) for n in self.networks)
