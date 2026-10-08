"""Pure functions that turn raw probe observations into explanations.

Nothing here performs I/O, which keeps the heuristics fully unit-testable.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping
from urllib.parse import urlparse

from netdoctor.models import BlockRange, Signature

#: RFC 2544 "benchmark" range — used by fake-IP proxies (Clash, sing-box, ...).
FAKE_IP_NETS = (ipaddress.ip_network("198.18.0.0/15"),)
_PRIVATE_LIKE = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
)


def blocked_ips(ips: Iterable[str], ranges: Iterable[BlockRange]) -> list[tuple[str, BlockRange]]:
    """Return ``(ip, range)`` pairs for every IP that falls in a known block range."""
    nets = [(ipaddress.ip_network(r.cidr, strict=False), r) for r in ranges]
    hits: list[tuple[str, BlockRange]] = []
    for ip in ips:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        for net, rng in nets:
            if addr.version == net.version and addr in net:
                hits.append((ip, rng))
                break
    return hits


def is_fake_ip(ip: str) -> bool:
    """True if ``ip`` comes from a fake-IP proxy range (198.18.0.0/15)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in FAKE_IP_NETS if addr.version == n.version)


def is_private_answer(ip: str) -> bool:
    """True if a public name resolved to a private/CGNAT address (suspicious)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in _PRIVATE_LIKE if addr.version == n.version)


def match_signature(
    status: int,
    body: str,
    headers: Mapping[str, str],
    signatures: Iterable[Signature],
    block_hosts: Iterable[str] = (),
) -> Signature | None:
    """Find the first signature that explains an HTTP response.

    Matches are case-insensitive against the body, ``Location`` and ``Server`` headers
    (plus the token ``cf-mitigated`` when Cloudflare flags a bot challenge).
    A redirect to a known block host (e.g. ``peyvandha.ir``) is always a block page.
    """
    location = headers.get("location", "")
    mitigated = "cf-mitigated" if headers.get("cf-mitigated", "").lower() == "challenge" else ""
    haystack = " ".join((body, location, headers.get("server", ""), mitigated)).lower()
    host = (urlparse(location).hostname or "").lower() if location else ""
    for bh in block_hosts:
        if host == bh or host.endswith("." + bh):
            return Signature(
                id="block-redirect", name=f"Redirect to {bh}", kind="block", patterns=(bh,)
            )
    for sig in signatures:
        if sig.statuses and status not in sig.statuses:
            continue
        if any(p in haystack for p in sig.patterns):
            return sig
    return None


def explain_error(stage: str, kind: str) -> str:
    """Human explanation for a failed probe stage."""
    table = {
        ("dns", "nxdomain"): "Name does not exist according to your resolver.",
        ("dns", "timeout"): "DNS query timed out — resolver unreachable or dropping queries.",
        ("dns", "no-answer"): "Resolver returned no IPv4 address.",
        ("tcp", "timeout"): "TCP connection timed out — IP may be blackholed.",
        ("tcp", "refused"): "TCP connection refused.",
        ("tcp", "reset"): "TCP connection reset.",
        ("tls", "reset"): "TLS handshake reset after TCP connect — typical of SNI filtering.",
        ("tls", "timeout"): "TLS handshake stalled after TCP connect — typical of SNI filtering.",
        ("tls", "cert"): "Certificate did not verify — possible TLS interception.",
        ("tls", "tls"): "TLS handshake failed.",
        ("http", "timeout"): "HTTP request timed out.",
        ("http", "reset"): "HTTP connection reset mid-request.",
    }
    return table.get((stage, kind), f"{stage.upper()} failed ({kind}).")
