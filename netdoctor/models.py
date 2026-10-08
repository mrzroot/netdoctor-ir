"""Core data model: catalog entries and probe results.

Everything here is a plain, typed dataclass so results are easy to test, render and
serialise (see :func:`to_dict`).
"""

from __future__ import annotations

import dataclasses
import enum
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------- catalog


class Verification(str, enum.Enum):
    """How much we trust a catalog entry."""

    OFFICIAL = "official"
    """Run by the upstream project itself (pypi.org, registry.npmjs.org, ...)."""

    DOCUMENTED = "documented"
    """The operator publicly documents this endpoint/address on its own site."""

    COMMUNITY = "community-reported"
    """Collected from community lists; not independently verified by maintainers."""


class ResolverKind(str, enum.Enum):
    """Category of a DNS resolver."""

    PUBLIC = "public"
    ANTI_SANCTION = "anti-sanction"
    ISP = "isp"


@dataclass(frozen=True)
class Service:
    """A developer-facing service we probe (e.g. PyPI, Docker Hub)."""

    id: str
    name: str
    category: str
    host: str
    path: str = "/"
    port: int = 443
    scheme: str = "https"
    expect: tuple[int, ...] = ()
    sanction_prone: bool = False
    note: str = ""

    @property
    def url(self) -> str:
        """Canonical URL used for the HTTP probe."""
        default = 443 if self.scheme == "https" else 80
        netloc = self.host if self.port == default else f"{self.host}:{self.port}"
        return f"{self.scheme}://{netloc}{self.path}"

    def status_expected(self, status: int) -> bool:
        """Return True if ``status`` counts as healthy for this service."""
        if self.expect:
            return status in self.expect
        return 200 <= status < 400


@dataclass(frozen=True)
class Resolver:
    """A DNS resolver from the catalog."""

    id: str
    name: str
    kind: ResolverKind
    addresses: tuple[str, ...]
    website: str = ""
    name_fa: str = ""
    doh: str = ""
    iran_only: bool = False
    verification: Verification = Verification.COMMUNITY
    note: str = ""

    @property
    def primary(self) -> str:
        """First (primary) resolver address."""
        return self.addresses[0]


@dataclass(frozen=True)
class Mirror:
    """A package/registry mirror from the catalog."""

    id: str
    name: str
    provider: str
    ecosystem: str
    url: str
    country: str = "IR"
    verification: Verification = Verification.COMMUNITY
    source: str = ""
    note: str = ""


@dataclass(frozen=True)
class Signature:
    """A fingerprint of a sanction page or a filtering block page."""

    id: str
    name: str
    kind: str  # "sanction" | "block" | "challenge"
    patterns: tuple[str, ...]
    statuses: tuple[int, ...] = ()


@dataclass(frozen=True)
class BlockRange:
    """An IP range that a censoring resolver answers with instead of the real address."""

    cidr: str
    description: str


@dataclass(frozen=True)
class Catalog:
    """All data catalogs bundled in ``netdoctor/data`` (or loaded from an override dir)."""

    services: tuple[Service, ...]
    resolvers: tuple[Resolver, ...]
    mirrors: tuple[Mirror, ...]
    signatures: tuple[Signature, ...]
    block_ranges: tuple[BlockRange, ...]
    block_hosts: tuple[str, ...] = ()

    def mirrors_for(self, ecosystem: str) -> list[Mirror]:
        """Mirrors of one ecosystem, catalog order."""
        return [m for m in self.mirrors if m.ecosystem == ecosystem]

    @property
    def ecosystems(self) -> list[str]:
        """Distinct mirror ecosystems, catalog order."""
        seen: dict[str, None] = {}
        for m in self.mirrors:
            seen.setdefault(m.ecosystem, None)
        return list(seen)


# --------------------------------------------------------------------------- results


class Verdict(str, enum.Enum):
    """Final classification of a probe."""

    OK = "ok"
    SLOW = "slow"
    SANCTIONED = "sanctioned"
    FILTERED = "filtered"
    FORBIDDEN = "forbidden"
    DNS_ERROR = "dns-error"
    TCP_ERROR = "tcp-error"
    TLS_ERROR = "tls-error"
    HTTP_ERROR = "http-error"
    TIMEOUT = "timeout"

    @property
    def healthy(self) -> bool:
        """True for verdicts that mean "works"."""
        return self in (Verdict.OK, Verdict.SLOW)


@dataclass
class Step:
    """Outcome of one probe stage (DNS, TCP, TLS or HTTP)."""

    ok: bool
    ms: float | None = None
    error: str | None = None
    detail: str = ""


@dataclass
class ServiceResult:
    """Full diagnosis of one :class:`Service`."""

    service: Service
    verdict: Verdict
    reason: str
    ips: list[str] = field(default_factory=list)
    dns: Step | None = None
    tcp: Step | None = None
    tls: Step | None = None
    http: Step | None = None
    status: int | None = None
    signature: str | None = None

    @property
    def total_ms(self) -> float | None:
        """Sum of the latency of all completed stages."""
        parts = [s.ms for s in (self.dns, self.tcp, self.tls, self.http) if s and s.ms]
        return round(sum(parts), 1) if parts else None


@dataclass
class ScanSummary:
    """Aggregate verdict for a whole scan."""

    total: int
    counts: dict[str, int]
    headline: str
    level: str  # "good" | "warn" | "bad"
    advice: list[str] = field(default_factory=list)


@dataclass
class ResolverScore:
    """Benchmark outcome of one resolver."""

    resolver: Resolver
    queries: int = 0
    answered: int = 0
    timeouts: int = 0
    errors: int = 0
    hijacked: int = 0
    differs: int = 0
    latencies: list[float] = field(default_factory=list)
    unlocks: int | None = None
    unlock_total: int | None = None
    best_address: str | None = None

    @property
    def success_rate(self) -> float:
        """Share of queries answered with a non-hijacked address."""
        if not self.queries:
            return 0.0
        return max(0, self.answered - self.hijacked) / self.queries

    @property
    def median_ms(self) -> float | None:
        """Median query latency."""
        return _percentile(self.latencies, 50)

    @property
    def p95_ms(self) -> float | None:
        """95th percentile query latency."""
        return _percentile(self.latencies, 95)

    @property
    def score(self) -> float:
        """Ranking score in 0..100 (higher is better).

        Base: ``100 * success_rate`` minus a latency penalty of up to 30 points
        (1 point per 20 ms of median latency). When a ``--deep`` check ran, the score
        becomes ``0.7 * base + 30 * (unblocked / tested)`` so a resolver that actually
        un-sanctions services outranks a merely fast one.
        """
        if not self.answered:
            return 0.0
        penalty = min(30.0, (self.median_ms or 0.0) / 20.0)
        base = max(0.0, 100.0 * self.success_rate - penalty)
        if self.unlocks is not None and self.unlock_total:
            base = 0.7 * base + 30.0 * self.unlocks / self.unlock_total
        return round(min(100.0, base), 1)


@dataclass
class MirrorResult:
    """Health check outcome of one :class:`Mirror`."""

    mirror: Mirror
    verdict: Verdict
    reason: str
    status: int | None = None
    ms: float | None = None


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100.0
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 1)


def to_dict(obj: Any) -> Any:
    """Recursively convert dataclasses / enums / tuples into JSON-friendly values."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out = {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
        for prop in ("url", "total_ms", "success_rate", "median_ms", "p95_ms", "score"):
            if hasattr(type(obj), prop) and isinstance(getattr(type(obj), prop), property):
                out[prop] = to_dict(getattr(obj, prop))
        if isinstance(obj, ResolverScore):
            out.pop("latencies", None)
        return out
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): to_dict(v) for k, v in obj.items()}
    return obj
