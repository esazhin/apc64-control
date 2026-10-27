"""The only network guard (contract inv23, §7.1, s1, s11): home-network clients and same-site requests, no login.

Every HTTP request and WebSocket handshake passes through NetworkGuard before the app sees it:

- the client address must be in the configured AllowedNetworks (loopback, RFC 1918, IPv6 loopback, link-local
  and unique-local by default; IPv4-mapped IPv6 is unwrapped) — else 403 {problem: 'not on the home network'};
- an Origin header, when present, must name the same host and port as the Host header — else 403
  {problem: 'cross-site request refused'}. A request without Origin (the CLI, curl, a plain page load) passes;
- the Host header must name this machine: an IP literal, 'localhost', or a name whose first label is this
  machine's host name (for a host 'studio-pc': 'studio-pc', 'studio-pc.local', 'studio-pc.lan'). A page from
  another site that re-points its own name at this machine (DNS rebinding) sends a Host and an Origin that agree
  but name that site, so it is refused the same way.

Allowed requests reach the app unchanged (s11.c2); refused ones run nothing else (s1.c3, s1.c4). A refused
WebSocket handshake is closed before it is accepted, which the server answers with HTTP 403.
"""
import ipaddress
import json
import logging
import socket
from urllib.parse import urlsplit

from ..domain.network import AllowedNetworks

log = logging.getLogger(__name__)

NOT_HOME = "not on the home network"
CROSS_SITE = "cross-site request refused"
_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def _header(scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or ():
        if key.lower() == name:
            return value.decode("latin-1").strip()
    return None


def _split_host(text: str, default_port: int | None) -> tuple[str, int | None]:
    """'host:port', '[v6]:port' or 'host' → (lower-case host without brackets, port)."""
    text = text.strip()
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    elif text.count(":") == 1:
        host, _, port = text.partition(":")
    else:
        host, port = text, ""
    try:
        number = int(port) if port else default_port
    except ValueError:
        number = -1
    return host.lower().rstrip("."), number


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return True
    except ValueError:
        return False


class NetworkGuard:
    """ASGI middleware: allowed client networks plus a same-site Origin/Host (s1)."""

    def __init__(self, app, networks: AllowedNetworks | None = None, local_names=None):
        self.app = app
        self.networks = networks or AllowedNetworks.default()
        names = local_names if local_names is not None else (socket.gethostname(),)
        self.local_names = {str(n).lower().split(".", 1)[0] for n in names if n} | {"localhost"}

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        problem = self.problem(scope)
        if problem is None:
            await self.app(scope, receive, send)
            return
        client = (scope.get("client") or ("?",))[0]
        log.warning("refused %s %s from %s: %s", scope["type"], scope.get("path"), client, problem)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": problem})
            return
        body = json.dumps({"problem": problem}).encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    # --- the decision (pure over the scope) -----------------------------------------------------------
    def problem(self, scope) -> str | None:
        client = scope.get("client")
        if not client or not self.networks.allows(str(client[0])):
            return NOT_HOME
        scheme = "https" if scope.get("scheme") in ("https", "wss") else "http"
        host_header = _header(scope, b"host")
        if host_header is None:
            return CROSS_SITE if _header(scope, b"origin") else None
        host, port = _split_host(host_header, _DEFAULT_PORTS[scheme])
        if not self._local(host):
            return CROSS_SITE
        origin = _header(scope, b"origin")
        if origin is None:
            return None
        parts = urlsplit(origin)
        if parts.scheme not in _DEFAULT_PORTS or not parts.netloc:
            return CROSS_SITE      # 'null' (file://, sandboxed frames) or garbage
        origin_host, origin_port = _split_host(parts.netloc.rsplit("@", 1)[-1], _DEFAULT_PORTS[parts.scheme])
        if (origin_host, origin_port) != (host, port):
            return CROSS_SITE
        return None

    def _local(self, host: str) -> bool:
        if not host:
            return False
        if _is_ip(host):
            return True
        return host.split(".", 1)[0] in self.local_names
