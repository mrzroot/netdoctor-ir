"""Shared fixtures: a fully scripted fake network so no test touches the internet."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

from netdoctor.catalog import load_catalog
from netdoctor.models import Catalog, Service
from netdoctor.net import DnsAnswer, HttpReply, ProbeError, TlsInfo


@dataclass
class FakeNetwork:
    """Scriptable stand-in for :class:`netdoctor.net.Network`.

    ``dns`` maps ``host`` or ``(host, nameserver)`` to a list of IPs or a ProbeError.
    ``tcp``/``tls`` map an IP (or host for tls) to latency or a ProbeError.
    ``http`` maps a URL to an HttpReply, a ProbeError, or a callable(url, ip) -> either.
    Unlisted things succeed with sensible defaults.
    """

    dns: dict[Any, Any] = field(default_factory=dict)
    tcp: dict[str, Any] = field(default_factory=dict)
    tls: dict[str, Any] = field(default_factory=dict)
    http: dict[str, Any] = field(default_factory=dict)
    default_http: HttpReply = field(default_factory=lambda: HttpReply(200, 20.0, {}, "ok"))
    calls: list[tuple[str, Any]] = field(default_factory=list)

    async def __aenter__(self) -> FakeNetwork:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def resolve(self, host: str, nameserver: str | None = None) -> DnsAnswer:
        self.calls.append(("dns", (host, nameserver)))
        value = self.dns.get((host, nameserver), self.dns.get(host, ["93.184.216.34"]))
        if isinstance(value, ProbeError):
            raise value
        if isinstance(value, tuple):
            ips, ms = value
            return DnsAnswer(list(ips), ms)
        return DnsAnswer(list(value), 5.0)

    async def tcp_connect(self, ip: str, port: int) -> float:
        self.calls.append(("tcp", (ip, port)))
        value = self.tcp.get(ip, 10.0)
        if isinstance(value, ProbeError):
            raise value
        return float(value)

    async def tls_handshake(self, ip: str, port: int, sni: str) -> TlsInfo:
        self.calls.append(("tls", (ip, sni)))
        value = self.tls.get(sni, self.tls.get(ip, 15.0))
        if isinstance(value, ProbeError):
            raise value
        return TlsInfo(float(value), "TLSv1.3", "Test CA")

    async def http_get(
        self, url: str, *, ip: str | None = None, follow_redirects: bool = False
    ) -> HttpReply:
        self.calls.append(("http", (url, ip)))
        value: Any = self.http.get(url, self.default_http)
        if callable(value) and not isinstance(value, HttpReply):
            value = value(url, ip)
        if isinstance(value, ProbeError):
            raise value
        return value


@pytest.fixture
def catalog() -> Catalog:
    return load_catalog()


@pytest.fixture
def fake_net() -> FakeNetwork:
    return FakeNetwork()


@pytest.fixture
def svc() -> Callable[..., Service]:
    def make(**kw: Any) -> Service:
        base: dict[str, Any] = {
            "id": "demo",
            "name": "Demo",
            "category": "python",
            "host": "demo.example",
            "path": "/x",
        }
        base.update(kw)
        return Service(**base)

    return make


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep backups, pip/npm/go config of every test inside tmp_path."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("NETDOCTOR_HOME", str(tmp_path / "nd"))
    monkeypatch.setenv("PIP_CONFIG_FILE", str(home / "pip.conf"))
    monkeypatch.setenv("NPM_CONFIG_USERCONFIG", str(home / ".npmrc"))
    monkeypatch.setenv("GOENV", str(home / "go.env"))
    monkeypatch.delenv("NETDOCTOR_CATALOG_DIR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")  # Rich pins TERM=dumb consoles to 80 cols
    return home
