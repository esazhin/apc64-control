"""s1 (supplier) and s11 (collaboration): the network guard in front of the app (T29; A143–A147)."""
import asyncio
import json

from _apc64_host.domain.network import AllowedNetworks
from _apc64_host.presentation.network_guard import CROSS_SITE, NOT_HOME, NetworkGuard


class InnerApp:
    """The app double: records each forwarded scope and answers 200 'inner'."""

    def __init__(self):
        self.scopes = []

    async def __call__(self, scope, receive, send):
        self.scopes.append(scope)
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": [(b"x-inner", b"1")]})
            await send({"type": "http.response.body", "body": b"inner"})


def call(guard, client, *, host="192.168.1.10:5058", origin=None, kind="http", path="/api/layout"):
    headers = [(b"host", host.encode())] if host is not None else []
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    scope = {"type": kind, "path": path, "scheme": "http" if kind == "http" else "ws", "headers": headers,
             "client": (client, 50000) if client else None}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    asyncio.run(guard(scope, receive, send))
    return scope, sent


def make():
    inner = InnerApp()
    return inner, NetworkGuard(inner, AllowedNetworks.default(), local_names=("studio-pc",))


def status_of(sent):
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def body_of(sent):
    return json.loads(b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body"))


def test_home_network_clients_reach_the_app_unchanged():
    # A143 (phone 192.168.1.23), A146 (fd00::23), A147 (guest 192.168.1.40 seen as IPv4-mapped), loopback
    for client in ("192.168.1.23", "fd00::23", "::1", "::ffff:192.168.1.40", "127.0.0.1"):
        inner, guard = make()
        scope, sent = call(guard, client)
        assert inner.scopes == [scope], client          # s11.c1: the original scope is forwarded
        assert status_of(sent) == 200 and (b"x-inner", b"1") in sent[0]["headers"]   # s11.c2 unchanged


def test_a_public_client_is_refused_and_nothing_else_runs():
    # A144: 203.0.113.5 asks to switch layout
    inner, guard = make()
    _, sent = call(guard, "203.0.113.5")
    assert inner.scopes == []
    assert status_of(sent) == 403 and body_of(sent) == {"problem": NOT_HOME} == {"problem": "not on the home network"}


def test_a_foreign_origin_is_refused():
    # A145: a page from example.com in the user's own browser
    inner, guard = make()
    _, sent = call(guard, "192.168.1.23", origin="https://example.com")
    assert inner.scopes == []
    assert status_of(sent) == 403 and body_of(sent) == {"problem": CROSS_SITE} == {"problem": "cross-site request refused"}


def test_no_origin_passes_and_a_same_site_origin_passes():
    inner, guard = make()
    call(guard, "127.0.0.1", host="127.0.0.1:5058")                                    # the CLI
    call(guard, "192.168.1.23", host="192.168.1.10:5058", origin="http://192.168.1.10:5058")
    call(guard, "192.168.1.23", host="studio-pc.local:5058", origin="http://studio-pc.local:5058")
    call(guard, "::1", host="[::1]:5058", origin="http://[::1]:5058")
    call(guard, "127.0.0.1", host="localhost:5058", origin="http://localhost:5058")
    assert len(inner.scopes) == 5


def test_an_origin_on_another_port_or_a_rebound_name_is_refused():
    for host, origin in (("192.168.1.10:5058", "http://192.168.1.10:8080"),     # another local service
                         ("evil.example:5058", "http://evil.example:5058"),     # DNS rebinding: Host is foreign
                         ("192.168.1.10:5058", "null")):                        # file:// or sandboxed frame
        inner, guard = make()
        _, sent = call(guard, "192.168.1.23", host=host, origin=origin)
        assert inner.scopes == [] and status_of(sent) == 403, (host, origin)
        assert body_of(sent) == {"problem": CROSS_SITE}


def test_a_refused_websocket_handshake_is_closed_before_accept():
    inner, guard = make()
    _, sent = call(guard, "203.0.113.5", kind="websocket", path="/ws")
    assert inner.scopes == []
    assert sent == [{"type": "websocket.close", "code": 1008, "reason": NOT_HOME}]
    inner, guard = make()
    _, sent = call(guard, "192.168.1.23", kind="websocket", path="/ws", origin="https://example.com")
    assert sent[0]["reason"] == CROSS_SITE
    inner, guard = make()
    scope, _ = call(guard, "192.168.1.23", kind="websocket", path="/ws", origin="http://192.168.1.10:5058")
    assert inner.scopes == [scope]


def test_lifespan_and_configured_networks():
    inner, guard = make()
    asyncio.run(guard({"type": "lifespan"}, None, None))
    assert inner.scopes == [{"type": "lifespan"}]
    # a Tailscale phone is refused by default and allowed once its range is configured (a24)
    _, sent = call(guard, "100.64.1.2")
    assert status_of(sent) == 403
    inner2 = InnerApp()
    wider = NetworkGuard(inner2, AllowedNetworks.parse("192.168.0.0/16, 100.64.0.0/10"), local_names=("studio-pc",))
    call(wider, "100.64.1.2")
    assert len(inner2.scopes) == 1
