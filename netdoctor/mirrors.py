"""`netdoctor mirrors`: health-check package mirrors and pick the best per ecosystem."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from netdoctor.detect import match_signature
from netdoctor.models import Catalog, Mirror, MirrorResult, Verdict
from netdoctor.net import ProbeError
from netdoctor.scanner import NetworkLike

DEFAULT_SLOW_MS = 2000.0


@dataclass(frozen=True)
class EcosystemProbe:
    """How to check that a mirror of an ecosystem really serves content."""

    path: str
    markers: tuple[str, ...]
    ok_statuses: tuple[int, ...] = (200,)
    label: str = ""


PROBES: dict[str, EcosystemProbe] = {
    "pypi": EcosystemProbe("/pip/", ("pip-",), label="simple index for 'pip'"),
    "npm": EcosystemProbe("/is-number", ('"is-number"',), label="metadata for 'is-number'"),
    "docker": EcosystemProbe("/v2/", (), ok_statuses=(200, 401), label="registry /v2/ API"),
    "go": EcosystemProbe(
        "/golang.org/x/text/@v/list", ("v0.",), label="versions of golang.org/x/text"
    ),
    "maven": EcosystemProbe(
        "/junit/junit/maven-metadata.xml", ("<metadata",), label="junit maven-metadata.xml"
    ),
}


def probe_url(mirror: Mirror) -> str:
    """URL fetched to verify ``mirror``."""
    return mirror.url.rstrip("/") + PROBES[mirror.ecosystem].path


def _error_verdict(exc: ProbeError) -> Verdict:
    msg = exc.message.lower()
    if exc.kind == "timeout":
        return Verdict.TIMEOUT
    if exc.kind in ("cert", "tls"):
        return Verdict.TLS_ERROR
    if any(s in msg for s in ("name or service", "nodename", "getaddrinfo", "no address")):
        return Verdict.DNS_ERROR
    if exc.kind in ("reset", "refused", "connect", "network"):
        return Verdict.TCP_ERROR
    return Verdict.HTTP_ERROR


async def check_mirror(
    mirror: Mirror, net: NetworkLike, catalog: Catalog, *, slow_ms: float = DEFAULT_SLOW_MS
) -> MirrorResult:
    """Fetch a known artefact from ``mirror`` and validate the response."""
    probe = PROBES[mirror.ecosystem]
    try:
        reply = await net.http_get(probe_url(mirror), follow_redirects=True)
    except ProbeError as exc:
        short = exc.message.splitlines()[0][:120] if exc.message else exc.kind
        return MirrorResult(mirror, _error_verdict(exc), short, ms=exc.ms)
    sig = match_signature(
        reply.status, reply.body, reply.headers, catalog.signatures, catalog.block_hosts
    )
    if sig is not None and sig.kind == "challenge":
        return MirrorResult(
            mirror,
            Verdict.HTTP_ERROR,
            "Bot-protection challenge — package tools cannot pass it",
            reply.status,
            reply.ms,
        )
    if sig is not None:
        verdict = Verdict.FILTERED if sig.kind == "block" else Verdict.SANCTIONED
        return MirrorResult(mirror, verdict, sig.name, reply.status, reply.ms)
    if reply.status not in probe.ok_statuses:
        verdict = Verdict.FORBIDDEN if reply.status in (401, 403, 451) else Verdict.HTTP_ERROR
        return MirrorResult(
            mirror, verdict, f"HTTP {reply.status} for {probe.label}", reply.status, reply.ms
        )
    body = reply.body.lower()
    if probe.markers and not any(m.lower() in body for m in probe.markers):
        return MirrorResult(
            mirror,
            Verdict.HTTP_ERROR,
            f"HTTP {reply.status} but unexpected content for {probe.label}",
            reply.status,
            reply.ms,
        )
    if reply.ms > slow_ms:
        return MirrorResult(
            mirror, Verdict.SLOW, f"Serves {probe.label}, slowly", reply.status, reply.ms
        )
    return MirrorResult(mirror, Verdict.OK, f"Serves {probe.label}", reply.status, reply.ms)


async def check_mirrors(
    mirrors: Sequence[Mirror],
    net: NetworkLike,
    catalog: Catalog,
    *,
    concurrency: int = 16,
    slow_ms: float = DEFAULT_SLOW_MS,
    on_result: Callable[[MirrorResult], None] | None = None,
) -> list[MirrorResult]:
    """Check mirrors concurrently; results keep catalog order."""
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(m: Mirror) -> MirrorResult:
        async with sem:
            res = await check_mirror(m, net, catalog, slow_ms=slow_ms)
        if on_result is not None:
            on_result(res)
        return res

    return list(await asyncio.gather(*(one(m) for m in mirrors)))


def best_per_ecosystem(results: Sequence[MirrorResult]) -> dict[str, MirrorResult]:
    """Pick the fastest healthy mirror per ecosystem (OK beats SLOW)."""
    best: dict[str, MirrorResult] = {}
    for r in results:
        if not r.verdict.healthy:
            continue
        cur = best.get(r.mirror.ecosystem)
        key = (r.verdict is not Verdict.OK, r.ms or 1e9)
        if cur is None or key < (cur.verdict is not Verdict.OK, cur.ms or 1e9):
            best[r.mirror.ecosystem] = r
    return best
