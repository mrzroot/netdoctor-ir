"""Network layer tests: HTTP via respx mocks, TCP/TLS against local loopback servers."""

import asyncio
import ssl

import dns.exception
import dns.resolver
import httpx
import pytest
import respx

from netdoctor import net as netmod
from netdoctor.net import MAX_BODY, Network, ProbeError, classify_exception


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (ProbeError("custom"), "custom"),
        (asyncio.TimeoutError(), "timeout"),
        (httpx.ReadTimeout("t"), "timeout"),
        (dns.resolver.NXDOMAIN(), "nxdomain"),
        (dns.resolver.NoAnswer(), "no-answer"),
        (dns.exception.Timeout(), "timeout"),
        (ssl.SSLCertVerificationError("bad"), "cert"),
        (ssl.SSLError("x"), "tls"),
        (ConnectionRefusedError(), "refused"),
        (ConnectionResetError(), "reset"),
        (httpx.ConnectError("certificate verify failed"), "cert"),
        (httpx.ConnectError("Connection reset by peer"), "reset"),
        (httpx.ConnectError("Connection refused"), "refused"),
        (httpx.ConnectError("other"), "connect"),
        (httpx.RemoteProtocolError("x"), "reset"),
        (OSError("x"), "network"),
        (ValueError("x"), "error"),
    ],
)
def test_classify_exception(exc, kind):
    assert classify_exception(exc) == kind


class _Rec:
    def __init__(self, text):
        self._t = text

    def to_text(self):
        return self._t


class FakeResolver:
    instances: list["FakeResolver"] = []
    behaviour: object = ["1.2.3.4", "5.6.7.8"]

    def __init__(self, configure=True):
        self.configure = configure
        self.nameservers: list[str] = []
        FakeResolver.instances.append(self)

    async def resolve(self, host, rdtype):
        assert rdtype == "A"
        if isinstance(FakeResolver.behaviour, Exception):
            raise FakeResolver.behaviour
        return [_Rec(x) for x in FakeResolver.behaviour]


@pytest.fixture
def fake_resolver(monkeypatch):
    FakeResolver.instances = []
    FakeResolver.behaviour = ["1.2.3.4", "5.6.7.8"]
    monkeypatch.setattr(netmod.dns.asyncresolver, "Resolver", FakeResolver)
    return FakeResolver


async def test_resolve_system_and_custom(fake_resolver):
    n = Network(timeout=2)
    ans = await n.resolve("pypi.org")
    assert ans.ips == ["1.2.3.4", "5.6.7.8"] and ans.ms >= 0
    assert fake_resolver.instances[-1].configure is True
    await n.resolve("pypi.org", "9.9.9.9")
    assert fake_resolver.instances[-1].nameservers == ["9.9.9.9"]
    n2 = Network(nameservers=["1.1.1.1"])
    await n2.resolve("pypi.org")
    assert fake_resolver.instances[-1].nameservers == ["1.1.1.1"]


async def test_resolve_errors(fake_resolver):
    fake_resolver.behaviour = dns.resolver.NXDOMAIN()
    with pytest.raises(ProbeError) as ei:
        await Network().resolve("nope.invalid")
    assert ei.value.kind == "nxdomain" and ei.value.ms is not None


async def _server(handler):
    srv = await asyncio.start_server(handler, "127.0.0.1", 0)
    return srv, srv.sockets[0].getsockname()[1]


async def test_tcp_connect_ok_and_refused():
    async def handler(reader, writer):
        writer.close()

    srv, port = await _server(handler)
    async with srv:
        ms = await Network(timeout=2).tcp_connect("127.0.0.1", port)
        assert ms >= 0
    with pytest.raises(ProbeError) as ei:
        await Network(timeout=2).tcp_connect("127.0.0.1", port)  # server closed now
    assert ei.value.kind in ("refused", "network")


async def test_tls_handshake_against_plain_server_fails():
    async def handler(reader, writer):
        await reader.read(10)
        writer.write(b"HTTP/1.0 400 nope\r\n\r\n")
        await writer.drain()
        writer.close()

    srv, port = await _server(handler)
    async with srv:
        with pytest.raises(ProbeError) as ei:
            await Network(timeout=2).tls_handshake("127.0.0.1", port, "example.org")
    assert ei.value.kind in ("tls", "reset", "network", "error")


async def test_tls_handshake_timeout():
    async def handler(reader, writer):
        await asyncio.sleep(0.5)
        writer.close()

    srv, port = await _server(handler)
    async with srv:
        with pytest.raises(ProbeError) as ei:
            await Network(timeout=0.2).tls_handshake("127.0.0.1", port, "example.org")
    assert ei.value.kind == "timeout"


@respx.mock
async def test_http_get_unpinned_follows_redirects():
    respx.get("https://example.org/a").mock(
        return_value=httpx.Response(302, headers={"Location": "https://example.org/b"})
    )
    respx.get("https://example.org/b").mock(return_value=httpx.Response(200, text="hello"))
    async with Network(timeout=2) as n:
        r = await n.http_get("https://example.org/a", follow_redirects=True)
        assert r.status == 200 and r.body == "hello" and r.url.endswith("/b")
        r2 = await n.http_get("https://example.org/a")
        assert r2.status == 302 and r2.headers["location"] == "https://example.org/b"


@respx.mock
async def test_http_get_pinned_keeps_host_and_sni():
    route = respx.get("https://93.184.216.34/simple/").mock(
        return_value=httpx.Response(403, text="x" * (MAX_BODY * 2))
    )
    async with Network(timeout=2) as n:
        r = await n.http_get("https://pypi.org/simple/", ip="93.184.216.34")
    req = route.calls.last.request
    assert req.headers["host"] == "pypi.org"
    assert req.extensions["sni_hostname"] == "pypi.org"
    assert r.status == 403 and len(r.body) == MAX_BODY


@respx.mock
async def test_http_get_pinned_plain_http_has_no_sni():
    route = respx.get("http://1.2.3.4/ubuntu/").mock(return_value=httpx.Response(200))
    async with Network(timeout=2) as n:
        await n.http_get("http://archive.ubuntu.com/ubuntu/", ip="1.2.3.4")
    assert "sni_hostname" not in route.calls.last.request.extensions


@respx.mock
async def test_http_get_errors():
    respx.get("https://example.org/t").mock(side_effect=httpx.ConnectTimeout("slow"))
    respx.get("https://1.1.1.1/t").mock(side_effect=httpx.ConnectError("Connection refused"))
    async with Network(timeout=2) as n:
        with pytest.raises(ProbeError) as ei:
            await n.http_get("https://example.org/t")
        assert ei.value.kind == "timeout"
        with pytest.raises(ProbeError) as ei:
            await n.http_get("https://example.org/t", ip="1.1.1.1")
        assert ei.value.kind == "refused"
