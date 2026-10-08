"""Load and validate the YAML data catalogs.

The bundled catalogs live in ``netdoctor/data``. Users and contributors can point
netdoctor at another directory (``--catalog-dir`` or ``NETDOCTOR_CATALOG_DIR``); any
file present there replaces the bundled file of the same name.
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Iterable, Mapping
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from netdoctor.models import (
    BlockRange,
    Catalog,
    Mirror,
    Resolver,
    ResolverKind,
    Service,
    Signature,
    Verification,
)

CATALOG_FILES = ("services.yaml", "resolvers.yaml", "mirrors.yaml", "signatures.yaml")
ECOSYSTEMS = ("pypi", "npm", "docker", "go", "maven")
SIGNATURE_KINDS = ("sanction", "block", "challenge")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ENV_CATALOG_DIR = "NETDOCTOR_CATALOG_DIR"


class CatalogError(ValueError):
    """Raised when a catalog file is missing or malformed."""


def _read_text(name: str, override: Path | None) -> str:
    if override is not None and (override / name).is_file():
        return (override / name).read_text(encoding="utf-8")
    return resources.files("netdoctor.data").joinpath(name).read_text(encoding="utf-8")


def _load_yaml(name: str, override: Path | None) -> Mapping[str, Any]:
    try:
        data = yaml.safe_load(_read_text(name, override))
    except yaml.YAMLError as exc:
        raise CatalogError(f"{name}: invalid YAML: {exc}") from exc
    if not isinstance(data, Mapping):
        raise CatalogError(f"{name}: top level must be a mapping")
    return data


def _require(entry: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in entry or entry[key] in (None, ""):
        raise CatalogError(f"{where}: missing required field '{key}'")
    return entry[key]


def _check_id(value: Any, where: str, seen: set[str]) -> str:
    ident = str(value)
    if not _ID_RE.match(ident):
        raise CatalogError(f"{where}: id '{ident}' must be lowercase kebab-case")
    if ident in seen:
        raise CatalogError(f"{where}: duplicate id '{ident}'")
    seen.add(ident)
    return ident


def _verification(value: Any, where: str) -> Verification:
    try:
        return Verification(value or Verification.COMMUNITY.value)
    except ValueError as exc:
        allowed = ", ".join(v.value for v in Verification)
        raise CatalogError(f"{where}: verification must be one of: {allowed}") from exc


def _entries(data: Mapping[str, Any], key: str, name: str) -> list[Mapping[str, Any]]:
    items = data.get(key)
    if not isinstance(items, list) or not items:
        raise CatalogError(f"{name}: '{key}' must be a non-empty list")
    for i, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise CatalogError(f"{name}: {key}[{i}] must be a mapping")
    return items


def parse_services(data: Mapping[str, Any]) -> tuple[Service, ...]:
    """Parse ``services.yaml`` content."""
    seen: set[str] = set()
    out: list[Service] = []
    for e in _entries(data, "services", "services.yaml"):
        where = f"services.yaml[{e.get('id', '?')}]"
        scheme = str(e.get("scheme", "https"))
        if scheme not in ("http", "https"):
            raise CatalogError(f"{where}: scheme must be http or https")
        path = str(e.get("path", "/"))
        if not path.startswith("/"):
            raise CatalogError(f"{where}: path must start with '/'")
        expect = tuple(int(x) for x in e.get("expect", []) or [])
        out.append(
            Service(
                id=_check_id(_require(e, "id", where), where, seen),
                name=str(_require(e, "name", where)),
                category=str(e.get("category", "other")),
                host=str(_require(e, "host", where)),
                path=path,
                port=int(e.get("port", 443 if scheme == "https" else 80)),
                scheme=scheme,
                expect=expect,
                sanction_prone=bool(e.get("sanction_prone", False)),
                note=str(e.get("note", "")),
            )
        )
    return tuple(out)


def parse_resolvers(data: Mapping[str, Any]) -> tuple[Resolver, ...]:
    """Parse ``resolvers.yaml`` content."""
    seen: set[str] = set()
    out: list[Resolver] = []
    for e in _entries(data, "resolvers", "resolvers.yaml"):
        where = f"resolvers.yaml[{e.get('id', '?')}]"
        addrs = _require(e, "addresses", where)
        if not isinstance(addrs, list) or not addrs:
            raise CatalogError(f"{where}: addresses must be a non-empty list")
        for a in addrs:
            try:
                ipaddress.ip_address(str(a))
            except ValueError as exc:
                raise CatalogError(f"{where}: '{a}' is not an IP address") from exc
        try:
            kind = ResolverKind(_require(e, "kind", where))
        except ValueError as exc:
            raise CatalogError(f"{where}: kind must be public, anti-sanction or isp") from exc
        out.append(
            Resolver(
                id=_check_id(_require(e, "id", where), where, seen),
                name=str(_require(e, "name", where)),
                kind=kind,
                addresses=tuple(str(a) for a in addrs),
                website=str(e.get("website", "")),
                name_fa=str(e.get("name_fa", "")),
                doh=str(e.get("doh", "")),
                iran_only=bool(e.get("iran_only", False)),
                verification=_verification(e.get("verification"), where),
                note=str(e.get("note", "")),
            )
        )
    return tuple(out)


def parse_mirrors(data: Mapping[str, Any]) -> tuple[Mirror, ...]:
    """Parse ``mirrors.yaml`` content."""
    seen: set[str] = set()
    out: list[Mirror] = []
    for e in _entries(data, "mirrors", "mirrors.yaml"):
        where = f"mirrors.yaml[{e.get('id', '?')}]"
        eco = str(_require(e, "ecosystem", where))
        if eco not in ECOSYSTEMS:
            raise CatalogError(f"{where}: ecosystem must be one of {', '.join(ECOSYSTEMS)}")
        url = str(_require(e, "url", where)).rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise CatalogError(f"{where}: url must be an absolute http(s) URL")
        out.append(
            Mirror(
                id=_check_id(_require(e, "id", where), where, seen),
                name=str(_require(e, "name", where)),
                provider=str(e.get("provider", "")),
                ecosystem=eco,
                url=url,
                country=str(e.get("country", "IR")),
                verification=_verification(e.get("verification"), where),
                source=str(e.get("source", "")),
                note=str(e.get("note", "")),
            )
        )
    return tuple(out)


def parse_signatures(
    data: Mapping[str, Any],
) -> tuple[tuple[Signature, ...], tuple[BlockRange, ...], tuple[str, ...]]:
    """Parse ``signatures.yaml`` content into signatures, block ranges and block hosts."""
    seen: set[str] = set()
    sigs: list[Signature] = []
    for e in _entries(data, "signatures", "signatures.yaml"):
        where = f"signatures.yaml[{e.get('id', '?')}]"
        kind = str(_require(e, "kind", where))
        if kind not in SIGNATURE_KINDS:
            raise CatalogError(f"{where}: kind must be one of {', '.join(SIGNATURE_KINDS)}")
        patterns = _require(e, "patterns", where)
        if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
            raise CatalogError(f"{where}: patterns must be a list of strings")
        sigs.append(
            Signature(
                id=_check_id(_require(e, "id", where), where, seen),
                name=str(_require(e, "name", where)),
                kind=kind,
                patterns=tuple(p.lower() for p in patterns),
                statuses=tuple(int(s) for s in e.get("statuses", []) or []),
            )
        )
    ranges: list[BlockRange] = []
    for r in data.get("block_ranges", []) or []:
        try:
            ipaddress.ip_network(str(r["cidr"]), strict=False)
        except (KeyError, ValueError, TypeError) as exc:
            raise CatalogError(f"signatures.yaml: bad block range {r!r}") from exc
        ranges.append(BlockRange(cidr=str(r["cidr"]), description=str(r.get("description", ""))))
    hosts = tuple(str(h).lower() for h in data.get("block_hosts", []) or [])
    return tuple(sigs), tuple(ranges), hosts


def _resolve_override(catalog_dir: str | os.PathLike[str] | None) -> Path | None:
    raw = catalog_dir if catalog_dir is not None else os.environ.get(ENV_CATALOG_DIR)
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise CatalogError(f"catalog directory not found: {path}")
    return path


def load_catalog(catalog_dir: str | os.PathLike[str] | None = None) -> Catalog:
    """Load all catalogs, preferring files in ``catalog_dir`` when given."""
    override = _resolve_override(catalog_dir)
    sigs, ranges, hosts = parse_signatures(_load_yaml("signatures.yaml", override))
    return Catalog(
        services=parse_services(_load_yaml("services.yaml", override)),
        resolvers=parse_resolvers(_load_yaml("resolvers.yaml", override)),
        mirrors=parse_mirrors(_load_yaml("mirrors.yaml", override)),
        signatures=sigs,
        block_ranges=ranges,
        block_hosts=hosts,
    )


def select(items: Iterable[Any], ids: Iterable[str] | None, attr: str = "id") -> list[Any]:
    """Filter catalog items by id (or another attribute); unknown ids raise CatalogError."""
    pool = list(items)
    wanted = [i.strip() for i in (ids or []) if i and i.strip()]
    if not wanted:
        return pool
    known = {getattr(x, attr) for x in pool}
    unknown = [w for w in wanted if w not in known]
    if unknown:
        raise CatalogError(f"unknown {attr}(s): {', '.join(unknown)}")
    return [x for x in pool if getattr(x, attr) in wanted]
