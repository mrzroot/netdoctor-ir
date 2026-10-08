"""`netdoctor dns`: benchmark DNS resolvers against developer domains."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from netdoctor.detect import blocked_ips, match_signature
from netdoctor.models import Catalog, Resolver, ResolverScore, Service
from netdoctor.net import ProbeError
from netdoctor.scanner import NetworkLike

#: Domains every developer in Iran cares about; used unless --all-domains is passed.
DEFAULT_HOSTS: tuple[str, ...] = (
    "pypi.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
    "registry-1.docker.io",
    "auth.docker.io",
    "proxy.golang.org",
    "github.com",
    "raw.githubusercontent.com",
    "fonts.googleapis.com",
    "dl.google.com",
    "repo1.maven.org",
    "gitlab.com",
)


def _prefixes(ips: Iterable[str]) -> set[str]:
    """/16 prefixes of IPv4 addresses — tolerant of CDN round-robin within a block."""
    return {".".join(ip.split(".")[:2]) for ip in ips}


@dataclass
class _AddrStats:
    ok: int = 0
    lat: list[float] = field(default_factory=list)


async def reference_answers(
    hosts: Sequence[str], net: NetworkLike, nameserver: str | None
) -> dict[str, set[str]]:
    """Resolve ``hosts`` through a trusted reference resolver (None = system resolver)."""

    async def one(host: str) -> tuple[str, set[str]]:
        try:
            ans = await net.resolve(host, nameserver)
        except ProbeError:
            return host, set()
        return host, set(ans.ips)

    return dict(await asyncio.gather(*(one(h) for h in hosts)))


async def benchmark(
    resolvers: Sequence[Resolver],
    hosts: Sequence[str],
    net: NetworkLike,
    catalog: Catalog,
    *,
    concurrency: int = 32,
    reference: dict[str, set[str]] | None = None,
    deep_services: Sequence[Service] | None = None,
    on_done: Callable[[ResolverScore], None] | None = None,
) -> list[ResolverScore]:
    """Query every host through every address of every resolver and rank resolvers.

    Args:
        reference: answers from a trusted resolver; used to count "differs" (domains for
            which no returned address shares a /16 with the reference's answers — what
            anti-sanction resolvers deliberately do, though geo-aware CDNs can cause it too).
        deep_services: if given, also fetch these services through each resolver's
            answers and count how many are *not* sanction-blocked ("unlocks").
    """
    sem = asyncio.Semaphore(max(1, concurrency))

    async def bench(res: Resolver) -> ResolverScore:
        score = ResolverScore(resolver=res)
        per_addr: dict[str, _AddrStats] = defaultdict(_AddrStats)

        async def query(addr: str, host: str) -> None:
            async with sem:
                try:
                    ans = await net.resolve(host, addr)
                except ProbeError as exc:
                    score.queries += 1
                    if exc.kind == "timeout":
                        score.timeouts += 1
                    else:
                        score.errors += 1
                    return
            score.queries += 1
            score.answered += 1
            score.latencies.append(ans.ms)
            per_addr[addr].ok += 1
            per_addr[addr].lat.append(ans.ms)
            if blocked_ips(ans.ips, catalog.block_ranges):
                score.hijacked += 1
            elif (
                reference is not None
                and reference.get(host)
                and not _prefixes(ans.ips) & _prefixes(reference[host])
            ):
                score.differs += 1

        await asyncio.gather(*(query(a, h) for a in res.addresses for h in hosts))
        if per_addr:
            score.best_address = max(
                per_addr.items(),
                key=lambda kv: (kv[1].ok, -sorted(kv[1].lat)[len(kv[1].lat) // 2]),
            )[0]
        if deep_services and score.best_address:
            score.unlocks, score.unlock_total = await _unlock_check(
                score.best_address, deep_services, net, catalog, sem
            )
        if on_done is not None:
            on_done(score)
        return score

    scores = await asyncio.gather(*(bench(r) for r in resolvers))
    return rank(scores)


async def _unlock_check(
    nameserver: str,
    services: Sequence[Service],
    net: NetworkLike,
    catalog: Catalog,
    sem: asyncio.Semaphore,
) -> tuple[int, int]:
    """Count services that answer normally when resolved through ``nameserver``."""

    async def one(svc: Service) -> bool:
        async with sem:
            try:
                ans = await net.resolve(svc.host, nameserver)
                if not ans.ips or blocked_ips(ans.ips, catalog.block_ranges):
                    return False
                reply = await net.http_get(svc.url, ip=ans.ips[0])
            except ProbeError:
                return False
        sig = match_signature(
            reply.status, reply.body, reply.headers, catalog.signatures, catalog.block_hosts
        )
        return sig is None and svc.status_expected(reply.status)

    results = await asyncio.gather(*(one(s) for s in services))
    return sum(results), len(results)


def rank(scores: Sequence[ResolverScore]) -> list[ResolverScore]:
    """Order by score (desc), then median latency (asc), then catalog name."""
    return sorted(
        scores,
        key=lambda s: (-s.score, s.median_ms if s.median_ms is not None else 1e9, s.resolver.name),
    )


def explain(score: ResolverScore) -> str:
    """One-line human note for a benchmark row."""
    r = score.resolver
    if not score.answered:
        if r.iran_only:
            return "No answers — this resolver only serves Iranian networks."
        return "No answers — unreachable from this network."
    bits: list[str] = []
    if score.hijacked:
        bits.append(f"{score.hijacked} hijacked answer(s)")
    if score.timeouts:
        bits.append(f"{score.timeouts} timeout(s)")
    if score.differs:
        bits.append(f"{score.differs} rewritten/CDN-differing answer(s)")
    if score.unlocks is not None and score.unlock_total:
        bits.append(f"unblocked {score.unlocks}/{score.unlock_total} sanction-prone services")
    return "; ".join(bits) or "Clean answers."
