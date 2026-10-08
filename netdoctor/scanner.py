"""`netdoctor scan`: diagnose reachability of developer services.

For each service we run, in order: DNS → TCP → TLS → HTTP, stop at the first failure,
then classify the outcome (see :func:`classify`).
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from netdoctor.detect import (
    blocked_ips,
    explain_error,
    is_fake_ip,
    is_private_answer,
    match_signature,
)
from netdoctor.models import (
    Catalog,
    ScanSummary,
    Service,
    ServiceResult,
    Step,
    Verdict,
)
from netdoctor.net import DnsAnswer, HttpReply, ProbeError, TlsInfo

DEFAULT_SLOW_MS = 1500.0


class NetworkLike(Protocol):
    """What the scanner needs from a network implementation."""

    async def resolve(self, host: str, nameserver: str | None = None) -> DnsAnswer: ...
    async def tcp_connect(self, ip: str, port: int) -> float: ...
    async def tls_handshake(self, ip: str, port: int, sni: str) -> TlsInfo: ...
    async def http_get(
        self, url: str, *, ip: str | None = None, follow_redirects: bool = False
    ) -> HttpReply: ...


ProgressCallback = Callable[[ServiceResult], None]


async def probe_service(
    service: Service,
    net: NetworkLike,
    catalog: Catalog,
    *,
    nameserver: str | None = None,
    slow_ms: float = DEFAULT_SLOW_MS,
) -> ServiceResult:
    """Run the full probe chain against one service and classify it."""
    # 1. DNS
    try:
        ans = await net.resolve(service.host, nameserver)
    except ProbeError as exc:
        verdict = Verdict.TIMEOUT if exc.kind == "timeout" else Verdict.DNS_ERROR
        return ServiceResult(
            service,
            verdict,
            explain_error("dns", exc.kind),
            dns=Step(False, exc.ms, exc.kind, exc.message),
        )
    dns_step = Step(True, ans.ms, detail=", ".join(ans.ips))
    hijack = blocked_ips(ans.ips, catalog.block_ranges)
    if hijack:
        ip, rng = hijack[0]
        return ServiceResult(
            service,
            Verdict.FILTERED,
            f"DNS answered {ip} — {rng.description}.",
            ips=ans.ips,
            dns=dns_step,
        )
    if not ans.ips:
        return ServiceResult(
            service, Verdict.DNS_ERROR, "Resolver returned no IPv4 address.", dns=dns_step
        )
    ip = ans.ips[0]
    note = ""
    if is_private_answer(ip):
        note = f" (note: {service.host} resolved to private address {ip})"

    # 2. TCP
    try:
        tcp_ms = await net.tcp_connect(ip, service.port)
    except ProbeError as exc:
        verdict = Verdict.TIMEOUT if exc.kind == "timeout" else Verdict.TCP_ERROR
        return ServiceResult(
            service,
            verdict,
            explain_error("tcp", exc.kind) + note,
            ips=ans.ips,
            dns=dns_step,
            tcp=Step(False, exc.ms, exc.kind, exc.message),
        )
    tcp_step = Step(True, tcp_ms)

    # 3. TLS
    tls_step: Step | None = None
    if service.scheme == "https":
        try:
            info = await net.tls_handshake(ip, service.port, service.host)
        except ProbeError as exc:
            # TCP worked but TLS died: the classic SNI-filtering fingerprint.
            filtered = exc.kind in ("reset", "timeout", "cert")
            return ServiceResult(
                service,
                Verdict.FILTERED if filtered else Verdict.TLS_ERROR,
                explain_error("tls", exc.kind) + note,
                ips=ans.ips,
                dns=dns_step,
                tcp=tcp_step,
                tls=Step(False, exc.ms, exc.kind, exc.message),
            )
        tls_step = Step(True, info.ms, detail=" ".join(x for x in (info.version, info.issuer) if x))

    # 4. HTTP
    try:
        reply = await net.http_get(service.url, ip=ip)
    except ProbeError as exc:
        verdict = Verdict.TIMEOUT if exc.kind == "timeout" else Verdict.HTTP_ERROR
        return ServiceResult(
            service,
            verdict,
            explain_error("http", exc.kind) + note,
            ips=ans.ips,
            dns=dns_step,
            tcp=tcp_step,
            tls=tls_step,
            http=Step(False, exc.ms, exc.kind, exc.message),
        )
    http_step = Step(True, reply.ms, detail=f"HTTP {reply.status}")
    result = ServiceResult(
        service,
        Verdict.OK,
        "",
        ips=ans.ips,
        dns=dns_step,
        tcp=tcp_step,
        tls=tls_step,
        http=http_step,
        status=reply.status,
    )
    result.verdict, result.reason, result.signature = classify(
        service, reply, catalog, slow_ms=slow_ms, total_ms=result.total_ms
    )
    result.reason += note
    return result


def classify(
    service: Service,
    reply: HttpReply,
    catalog: Catalog,
    *,
    slow_ms: float = DEFAULT_SLOW_MS,
    total_ms: float | None = None,
) -> tuple[Verdict, str, str | None]:
    """Classify a completed HTTP exchange. Returns ``(verdict, reason, signature_id)``."""
    sig = match_signature(
        reply.status, reply.body, reply.headers, catalog.signatures, catalog.block_hosts
    )
    if sig is not None and sig.kind == "challenge":
        return (
            Verdict.OK,
            f"Reachable — bot-protection challenge (HTTP {reply.status}), not a sanction.",
            sig.id,
        )
    if sig is not None and sig.kind == "block":
        return Verdict.FILTERED, f"Filtering block page detected ({sig.name}).", sig.id
    if sig is not None:
        return Verdict.SANCTIONED, f"HTTP {reply.status}: {sig.name}.", sig.id
    if service.status_expected(reply.status):
        if total_ms is not None and total_ms > slow_ms:
            return Verdict.SLOW, f"Works but slow ({total_ms:.0f} ms).", None
        return Verdict.OK, service.note, None
    if reply.status in (403, 451):
        hint = " — service is known to geo-block Iran" if service.sanction_prone else ""
        return (
            Verdict.FORBIDDEN,
            f"HTTP {reply.status} without a known sanction marker{hint}.",
            None,
        )
    return Verdict.HTTP_ERROR, f"Unexpected HTTP {reply.status}.", None


async def scan(
    services: Sequence[Service],
    net: NetworkLike,
    catalog: Catalog,
    *,
    concurrency: int = 16,
    nameserver: str | None = None,
    slow_ms: float = DEFAULT_SLOW_MS,
    on_result: ProgressCallback | None = None,
) -> list[ServiceResult]:
    """Probe ``services`` concurrently; results keep catalog order."""
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(svc: Service) -> ServiceResult:
        async with sem:
            res = await probe_service(svc, net, catalog, nameserver=nameserver, slow_ms=slow_ms)
        if on_result is not None:
            on_result(res)
        return res

    jobs: list[Awaitable[ServiceResult]] = [one(s) for s in services]
    return list(await asyncio.gather(*jobs))


def summarize(results: Sequence[ServiceResult]) -> ScanSummary:
    """Build the overall verdict and actionable advice for a scan."""
    counts = Counter(r.verdict.value for r in results)
    total = len(results)
    healthy = sum(1 for r in results if r.verdict.healthy)
    sanctioned = [r.service.name for r in results if r.verdict is Verdict.SANCTIONED]
    forbidden = [r.service.name for r in results if r.verdict is Verdict.FORBIDDEN]
    filtered = [r.service.name for r in results if r.verdict is Verdict.FILTERED]
    dns_bad = [r.service.name for r in results if r.verdict is Verdict.DNS_ERROR]
    slow = [r.service.name for r in results if r.verdict is Verdict.SLOW]
    other = total - healthy - len(sanctioned) - len(forbidden) - len(filtered) - len(dns_bad)

    advice: list[str] = []
    if sanctioned or forbidden:
        names = ", ".join((sanctioned + forbidden)[:4])
        advice.append(
            f"Sanction/geo-blocks on {len(sanctioned) + len(forbidden)} service(s) ({names}). "
            "Compare anti-sanction resolvers with `netdoctor dns --deep`, then use mirrors: "
            "`netdoctor mirrors`."
        )
    if filtered:
        advice.append(
            f"Filtering detected on {len(filtered)} service(s) ({', '.join(filtered[:4])}). "
            "Prefer domestic mirrors (`netdoctor mirrors --write`) for package installs."
        )
    if dns_bad:
        advice.append("Some names did not resolve — benchmark resolvers with `netdoctor dns`.")
    if slow:
        advice.append(f"{len(slow)} service(s) are slow; a closer mirror may speed up installs.")
    if any(r.ips and is_fake_ip(r.ips[0]) for r in results):
        advice.append(
            "Your resolver returns fake-IP answers (198.18.0.0/15): a local proxy/VPN is "
            "intercepting DNS, so these results describe that proxy's path."
        )
    if other > 0:
        advice.append(f"{other} service(s) failed at TCP/TLS/HTTP level — see the reason column.")

    if healthy == total:
        level, headline = "good", f"Healthy — all {total} developer services are reachable."
    elif healthy >= total * 0.75:
        level, headline = "warn", f"Mostly fine — {healthy}/{total} services reachable."
    else:
        level, headline = "bad", f"Degraded — only {healthy}/{total} services reachable."
    return ScanSummary(
        total=total, counts=dict(counts), headline=headline, level=level, advice=advice
    )
