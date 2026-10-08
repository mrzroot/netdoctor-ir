from netdoctor.detect import (
    blocked_ips,
    explain_error,
    is_fake_ip,
    is_private_answer,
    match_signature,
)
from netdoctor.models import BlockRange, Signature

RANGES = (BlockRange("10.10.34.0/24", "Iran filter"), BlockRange("::1/128", "v6 loopback"))


def test_blocked_ips():
    hits = blocked_ips(["1.2.3.4", "10.10.34.35", "garbage", "::1"], RANGES)
    assert [h[0] for h in hits] == ["10.10.34.35", "::1"]
    assert hits[0][1].description == "Iran filter"
    assert blocked_ips(["8.8.8.8"], RANGES) == []


def test_fake_and_private():
    assert is_fake_ip("198.18.0.1") and is_fake_ip("198.19.255.1")
    assert not is_fake_ip("8.8.8.8") and not is_fake_ip("x")
    assert is_private_answer("10.0.0.5") and is_private_answer("100.64.1.1")
    assert not is_private_answer("1.1.1.1") and not is_private_answer("x")


def test_bundled_signatures(catalog):
    docker_page = "Since Docker is a US company, we must comply with US export control regulations."
    sig = match_signature(403, docker_page, {}, catalog.signatures)
    assert sig is not None and sig.id == "docker-export-control"

    google = "<p><b>403.</b> That’s an error.</p> Your client does not have permission to get URL"
    sig = match_signature(403, google, {}, catalog.signatures)
    assert sig is not None and sig.id == "google-403"
    # same text with a 200 must not count (statuses filter)
    assert match_signature(200, google, {}, catalog.signatures) is None

    oa = '{"error": {"code": "unsupported_country_region_territory"}}'
    assert match_signature(403, oa, {}, catalog.signatures).id == "openai-unsupported-country"

    cf = "Error 1009 Access denied. The owner of this website has banned the country"
    assert match_signature(403, cf, {}, catalog.signatures).id == "cloudflare-1009"


def test_block_page_and_redirect(catalog):
    body = '<iframe src="http://10.10.34.34?type=Invalid Site"></iframe>'
    sig = match_signature(200, body, {}, catalog.signatures, catalog.block_hosts)
    assert sig is not None and sig.kind == "block"
    sig = match_signature(
        302, "", {"location": "https://www.peyvandha.ir/"}, catalog.signatures, catalog.block_hosts
    )
    assert sig is not None and sig.id == "block-redirect"


def test_challenge_detection(catalog):
    sig = match_signature(403, "", {"cf-mitigated": "challenge"}, catalog.signatures)
    assert sig is not None and sig.kind == "challenge"
    sig = match_signature(503, "<title>Just a moment...</title>", {}, catalog.signatures)
    assert sig is not None and sig.kind == "challenge"


def test_no_match_and_server_header():
    sig = Signature("s", "S", "sanction", ("evilcdn",))
    assert match_signature(200, "hello", {}, [sig]) is None
    assert match_signature(200, "", {"server": "EvilCDN"}, [sig]) is sig


def test_explain_error():
    assert "SNI" in explain_error("tls", "reset")
    assert "interception" in explain_error("tls", "cert")
    assert explain_error("http", "weird") == "HTTP failed (weird)."
