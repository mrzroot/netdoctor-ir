"""Thin async network layer.

All real I/O goes through :class:`Network`, which makes the rest of netdoctor easy to
test: the test-suite swaps in a fake implementation of the same methods.
"""

from __future__ import annotations

import asyncio
import ssl
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import dns.asyncresolver
import dns.exception
import dns.resolver
import httpx

from netdoctor import __version__

USER_AGENT = f"netdoctor-ir/{__version__} (+https://github.com/mrzroot/netdoctor-ir)"
MAX_BODY = 64 * 1024


class ProbeError(Exception):
    """A probe failed. ``kind`` is a short machine-readable category."""

    def __init__(self, kind: str, message: str = "", ms: float | None = None) -> None:
        super().__init__(message or kind)
        self.kind = kind
        self.message = message or kind
        self.ms = ms


@dataclass
class DnsAnswer:
    """IPv4 addresses returned for a name, plus query latency."""

    ips: list[str]
    ms: float


@dataclass
class TlsInfo:
    """Result of a TLS handshake."""

    ms: float
    version: str = ""
    issuer: str = ""


@dataclass
class HttpReply:
    """A (truncated) HTTP response."""

    status: int
    ms: float
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""
    url: str = ""


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 1)


def classify_exception(exc: BaseException) -> str:
    """Map low-level exceptions to stable error kinds used throughout netdoctor."""
    if isinstance(exc, ProbeError):
        return exc.kind
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(exc, dns.resolver.NXDOMAIN):
        return "nxdomain"
    if isinstance(exc, (dns.resolver.NoAnswer, dns.resolver.NoNameservers)):
        return "no-answer"
    if isinstance(exc, dns.exception.Timeout):
        return "timeout"
    if isinstance(exc, ssl.SSLCertVerificationError):
        return "cert"
    if isinstance(exc, ssl.SSLError):
        return "tls"
    if isinstance(exc, ConnectionRefusedError):
        return "refused"
    if isinstance(exc, ConnectionResetError):
        return "reset"
    if isinstance(exc, httpx.ConnectError):
        text = str(exc).lower()
        if "certificate" in text:
            return "cert"
        if "reset" in text:
            return "reset"
        if "refused" in text:
            return "refused"
        return "connect"
    if isinstance(exc, (httpx.RemoteProtocolError, httpx.ReadError)):
        return "reset"
    if isinstance(exc, OSError):
        return "network"
    return "error"


class Network:
    """Real network implementation backed by asyncio, dnspython and httpx.

    Args:
        timeout: per-operation timeout in seconds.
        nameservers: resolve names with these DNS servers instead of the system resolver.
    """

    def __init__(self, timeout: float = 5.0, nameservers: Sequence[str] | None = None) -> None:
        self.timeout = timeout
        self.nameservers = list(nameservers or [])
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle -----------------------------------------------------------------
    async def __aenter__(self) -> Network:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close pooled HTTP connections."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            follow_redirects=False,
        )

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = self._new_client()
        return self._client

    # -- DNS -----------------------------------------------------------------------
    def _resolver(self, nameserver: str | None) -> dns.asyncresolver.Resolver:
        if nameserver or self.nameservers:
            res = dns.asyncresolver.Resolver(configure=False)
            res.nameservers = [nameserver] if nameserver else list(self.nameservers)
        else:
            res = dns.asyncresolver.Resolver()
        res.lifetime = self.timeout
        res.timeout = self.timeout
        return res

    async def resolve(self, host: str, nameserver: str | None = None) -> DnsAnswer:
        """Resolve ``host`` to IPv4 addresses (A records)."""
        start = time.perf_counter()
        try:
            answer = await self._resolver(nameserver).resolve(host, "A")
        except Exception as exc:
            raise ProbeError(
                classify_exception(exc), str(exc) or type(exc).__name__, _ms(start)
            ) from exc
        ips = [r.to_text() for r in answer]
        return DnsAnswer(ips=ips, ms=_ms(start))

    # -- TCP / TLS -----------------------------------------------------------------
    async def tcp_connect(self, ip: str, port: int) -> float:
        """Open (and close) a TCP connection; return connect latency in ms."""
        start = time.perf_counter()
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), self.timeout)
        except Exception as exc:
            raise ProbeError(
                classify_exception(exc), str(exc) or type(exc).__name__, _ms(start)
            ) from exc
        ms = _ms(start)
        writer.transport.abort()  # no graceful shutdown needed; never wait on the peer
        return ms

    async def tls_handshake(self, ip: str, port: int, sni: str) -> TlsInfo:
        """Perform a verified TLS handshake with ``sni`` against ``ip``."""
        ctx = ssl.create_default_context()
        start = time.perf_counter()
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port, ssl=ctx, server_hostname=sni), self.timeout
            )
        except Exception as exc:
            raise ProbeError(
                classify_exception(exc), str(exc) or type(exc).__name__, _ms(start)
            ) from exc
        ms = _ms(start)
        sslobj = writer.get_extra_info("ssl_object")
        version = sslobj.version() if sslobj else ""
        issuer = ""
        cert = writer.get_extra_info("peercert") or {}
        for rdn in cert.get("issuer", ()):
            for key, value in rdn:
                if key == "organizationName":
                    issuer = value
        # Abort instead of close(): some servers never answer TLS close_notify, and
        # wait_closed() would then hang far beyond our timeout.
        writer.transport.abort()
        return TlsInfo(ms=ms, version=version or "", issuer=issuer)

    # -- HTTP ----------------------------------------------------------------------
    async def http_get(
        self,
        url: str,
        *,
        ip: str | None = None,
        follow_redirects: bool = False,
    ) -> HttpReply:
        """GET ``url`` and return status, headers and up to 64 KiB of body.

        When ``ip`` is given the connection goes to that address while keeping the
        original Host header and TLS SNI, so a custom resolver's answer can be tested.
        """
        parsed = httpx.URL(url)
        headers: dict[str, str] = {}
        extensions: dict[str, str] = {}
        target = parsed
        if ip:
            target = parsed.copy_with(host=ip)
            headers["Host"] = parsed.netloc.decode("ascii")
            if parsed.scheme == "https":
                extensions["sni_hostname"] = parsed.host
        # Connections are pooled per IP, and many hosts share one IP (CDNs, proxies), so an
        # IP-pinned request gets its own client: never reuse a TLS session made for
        # another SNI.
        client = self._new_client() if ip else self._http()
        start = time.perf_counter()
        try:
            request = client.build_request("GET", target, headers=headers, extensions=extensions)
            response = await client.send(request, stream=True, follow_redirects=follow_redirects)
            try:
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_BODY:
                        break
            finally:
                await response.aclose()
                if ip:
                    await client.aclose()
        except Exception as exc:
            if ip:
                await client.aclose()
            raise ProbeError(
                classify_exception(exc), str(exc) or type(exc).__name__, _ms(start)
            ) from exc
        body = b"".join(chunks)[:MAX_BODY].decode("utf-8", errors="replace")
        return HttpReply(
            status=response.status_code,
            ms=_ms(start),
            headers={k.lower(): v for k, v in response.headers.items()},
            body=body,
            url=str(response.url),
        )
