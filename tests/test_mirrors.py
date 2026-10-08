import pytest

from netdoctor.mirrors import best_per_ecosystem, check_mirror, check_mirrors, probe_url
from netdoctor.models import Mirror, MirrorResult, Verdict, Verification
from netdoctor.net import HttpReply, ProbeError


def m(eco, url="https://mirror.example/x", mid=None, ver=Verification.COMMUNITY):
    return Mirror(mid or f"{eco}-m", "M", "P", eco, url, verification=ver)


def test_probe_urls():
    assert probe_url(m("pypi", "https://a/simple")) == "https://a/simple/pip/"
    assert probe_url(m("npm", "https://a")) == "https://a/is-number"
    assert probe_url(m("docker", "https://a/")) == "https://a/v2/"
    assert probe_url(m("go", "https://a")) == "https://a/golang.org/x/text/@v/list"
    assert probe_url(m("maven", "https://a")).endswith("/junit/junit/maven-metadata.xml")


@pytest.mark.parametrize(
    ("eco", "reply", "verdict"),
    [
        ("pypi", HttpReply(200, 50, {}, '<a href="pip-24.0.tar.gz">'), Verdict.OK),
        ("pypi", HttpReply(200, 50, {}, "<html>landing page</html>"), Verdict.HTTP_ERROR),
        ("npm", HttpReply(200, 50, {}, '{"name":"is-number"}'), Verdict.OK),
        ("docker", HttpReply(401, 50, {}, ""), Verdict.OK),
        ("docker", HttpReply(200, 5000, {}, "{}"), Verdict.SLOW),
        ("go", HttpReply(200, 50, {}, "v0.3.0\nv0.14.0"), Verdict.OK),
        ("maven", HttpReply(200, 50, {}, "<?xml?><metadata>"), Verdict.OK),
        ("pypi", HttpReply(404, 50, {}, ""), Verdict.HTTP_ERROR),
        ("pypi", HttpReply(403, 50, {}, ""), Verdict.FORBIDDEN),
        (
            "docker",
            HttpReply(
                403,
                50,
                {},
                "Since Docker is a US company, we must comply with US export control regulations",
            ),
            Verdict.SANCTIONED,
        ),
        ("npm", HttpReply(200, 50, {}, "http://10.10.34.34"), Verdict.FILTERED),
        ("npm", HttpReply(403, 50, {"cf-mitigated": "challenge"}, ""), Verdict.HTTP_ERROR),
    ],
)
async def test_check_mirror_verdicts(fake_net, catalog, eco, reply, verdict):
    mirror = m(eco)
    fake_net.http[probe_url(mirror)] = reply
    res = await check_mirror(mirror, fake_net, catalog)
    assert res.verdict is verdict, res.reason


@pytest.mark.parametrize(
    ("err", "verdict"),
    [
        (ProbeError("timeout", "ReadTimeout"), Verdict.TIMEOUT),
        (ProbeError("cert", "bad cert"), Verdict.TLS_ERROR),
        (ProbeError("connect", "[Errno -2] Name or service not known"), Verdict.DNS_ERROR),
        (ProbeError("connect", "All connection attempts failed"), Verdict.TCP_ERROR),
        (ProbeError("error", "weird"), Verdict.HTTP_ERROR),
    ],
)
async def test_check_mirror_errors(fake_net, catalog, err, verdict):
    mirror = m("pypi")
    fake_net.http[probe_url(mirror)] = err
    res = await check_mirror(mirror, fake_net, catalog)
    assert res.verdict is verdict


async def test_check_mirrors_order_and_callback(fake_net, catalog):
    mirrors = [m("docker", f"https://d{i}.example", mid=f"d{i}") for i in range(4)]
    got = []
    res = await check_mirrors(mirrors, fake_net, catalog, concurrency=2, on_result=got.append)
    assert [r.mirror.id for r in res] == ["d0", "d1", "d2", "d3"] and len(got) == 4


def test_best_per_ecosystem():
    a = MirrorResult(m("pypi", mid="a"), Verdict.SLOW, "", 200, 100)
    b = MirrorResult(m("pypi", mid="b"), Verdict.OK, "", 200, 900)
    c = MirrorResult(m("pypi", mid="c"), Verdict.OK, "", 200, 300)
    d = MirrorResult(m("npm", mid="d"), Verdict.TIMEOUT, "", None, None)
    best = best_per_ecosystem([a, b, c, d])
    assert best["pypi"].mirror.id == "c" and "npm" not in best
