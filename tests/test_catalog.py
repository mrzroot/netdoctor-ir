import textwrap

import pytest

from netdoctor.catalog import (
    CatalogError,
    load_catalog,
    parse_mirrors,
    parse_resolvers,
    parse_services,
    parse_signatures,
    select,
)
from netdoctor.models import ResolverKind, Verification


def test_bundled_catalog_is_valid(catalog):
    assert len(catalog.services) >= 30
    assert len(catalog.resolvers) >= 10
    assert {"pypi", "npm", "docker", "go", "maven"} <= set(catalog.ecosystems)
    ids = [s.id for s in catalog.services]
    assert len(ids) == len(set(ids))
    assert any(r.kind is ResolverKind.ANTI_SANCTION for r in catalog.resolvers)
    assert catalog.block_ranges and catalog.block_hosts


def test_every_iranian_mirror_has_a_source(catalog):
    for m in catalog.mirrors:
        if m.verification is not Verification.OFFICIAL:
            assert m.source.startswith("http"), m.id


def test_mirrors_for(catalog):
    assert all(m.ecosystem == "docker" for m in catalog.mirrors_for("docker"))


@pytest.mark.parametrize(
    ("data", "msg"),
    [
        ({"services": []}, "non-empty list"),
        ({"services": ["x"]}, "must be a mapping"),
        ({"services": [{"id": "Bad_ID", "name": "n", "host": "h"}]}, "kebab-case"),
        ({"services": [{"id": "a", "host": "h"}]}, "missing required field 'name'"),
        ({"services": [{"id": "a", "name": "n", "host": "h", "scheme": "ftp"}]}, "scheme"),
        ({"services": [{"id": "a", "name": "n", "host": "h", "path": "x"}]}, "path"),
        (
            {
                "services": [
                    {"id": "a", "name": "n", "host": "h"},
                    {"id": "a", "name": "n", "host": "h"},
                ]
            },
            "duplicate",
        ),
    ],
)
def test_service_validation(data, msg):
    with pytest.raises(CatalogError, match=msg):
        parse_services(data)


def test_service_http_default_port():
    (s,) = parse_services(
        {"services": [{"id": "a", "name": "n", "host": "h", "scheme": "http", "expect": [200]}]}
    )
    assert s.port == 80 and s.expect == (200,)


@pytest.mark.parametrize(
    ("entry", "msg"),
    [
        ({"id": "a", "name": "n", "kind": "public", "addresses": []}, "non-empty"),
        ({"id": "a", "name": "n", "kind": "public", "addresses": ["nope"]}, "not an IP"),
        ({"id": "a", "name": "n", "kind": "weird", "addresses": ["1.1.1.1"]}, "kind"),
        (
            {
                "id": "a",
                "name": "n",
                "kind": "public",
                "addresses": ["1.1.1.1"],
                "verification": "trust-me",
            },
            "verification",
        ),
    ],
)
def test_resolver_validation(entry, msg):
    with pytest.raises(CatalogError, match=msg):
        parse_resolvers({"resolvers": [entry]})


@pytest.mark.parametrize(
    ("entry", "msg"),
    [
        ({"id": "a", "name": "n", "ecosystem": "cargo", "url": "https://x"}, "ecosystem"),
        ({"id": "a", "name": "n", "ecosystem": "pypi", "url": "ftp://x"}, "absolute"),
    ],
)
def test_mirror_validation(entry, msg):
    with pytest.raises(CatalogError, match=msg):
        parse_mirrors({"mirrors": [entry]})


def test_mirror_trailing_slash_stripped():
    (m,) = parse_mirrors(
        {"mirrors": [{"id": "a", "name": "n", "ecosystem": "pypi", "url": "https://x/simple/"}]}
    )
    assert m.url == "https://x/simple"
    assert m.verification is Verification.COMMUNITY


@pytest.mark.parametrize(
    ("data", "msg"),
    [
        ({"signatures": [{"id": "a", "name": "n", "kind": "evil", "patterns": ["x"]}]}, "kind"),
        (
            {"signatures": [{"id": "a", "name": "n", "kind": "block", "patterns": "x"}]},
            "list of strings",
        ),
        (
            {
                "signatures": [{"id": "a", "name": "n", "kind": "block", "patterns": ["x"]}],
                "block_ranges": [{"cidr": "not-a-net"}],
            },
            "bad block range",
        ),
    ],
)
def test_signature_validation(data, msg):
    with pytest.raises(CatalogError, match=msg):
        parse_signatures(data)


def test_signature_patterns_lowercased():
    sigs, ranges, hosts = parse_signatures(
        {
            "signatures": [{"id": "a", "name": "n", "kind": "sanction", "patterns": ["HeLLo"]}],
            "block_hosts": ["Peyvandha.IR"],
        }
    )
    assert sigs[0].patterns == ("hello",)
    assert ranges == () and hosts == ("peyvandha.ir",)


def test_override_dir(tmp_path):
    (tmp_path / "resolvers.yaml").write_text(
        textwrap.dedent("""
        resolvers:
          - id: only-one
            name: Only
            kind: public
            addresses: [9.9.9.9]
    """)
    )
    cat = load_catalog(tmp_path)
    assert [r.id for r in cat.resolvers] == ["only-one"]
    assert len(cat.services) > 10  # other files still bundled


def test_override_via_env(tmp_path, monkeypatch):
    (tmp_path / "mirrors.yaml").write_text(
        "mirrors:\n  - {id: m, name: M, ecosystem: npm, url: 'https://r.example'}\n"
    )
    monkeypatch.setenv("NETDOCTOR_CATALOG_DIR", str(tmp_path))
    assert [m.id for m in load_catalog().mirrors] == ["m"]


def test_override_errors(tmp_path):
    with pytest.raises(CatalogError, match="not found"):
        load_catalog(tmp_path / "missing")
    (tmp_path / "services.yaml").write_text("services: [unclosed")
    with pytest.raises(CatalogError, match="invalid YAML"):
        load_catalog(tmp_path)
    (tmp_path / "services.yaml").write_text("- just a list")
    with pytest.raises(CatalogError, match="mapping"):
        load_catalog(tmp_path)


def test_select(catalog):
    assert select(catalog.services, None) == list(catalog.services)
    picked = select(catalog.services, ["pypi", " npm "])
    assert [s.id for s in picked] == ["pypi", "npm"]
    with pytest.raises(CatalogError, match="unknown id"):
        select(catalog.services, ["nope"])
