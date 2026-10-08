from netdoctor.models import (
    Mirror,
    Resolver,
    ResolverKind,
    ResolverScore,
    Service,
    ServiceResult,
    Step,
    Verdict,
    _percentile,
    to_dict,
)


def test_service_url_and_expect():
    s = Service("a", "A", "python", "pypi.org", "/simple/")
    assert s.url == "https://pypi.org/simple/"
    assert s.status_expected(200) and s.status_expected(302)
    assert not s.status_expected(404)
    custom = Service("b", "B", "x", "h", "/v2/", port=8443, expect=(401,))
    assert custom.url == "https://h:8443/v2/"
    assert custom.status_expected(401) and not custom.status_expected(200)
    plain = Service("c", "C", "x", "h", scheme="http", port=80)
    assert plain.url == "http://h/"


def test_verdict_healthy():
    assert Verdict.OK.healthy and Verdict.SLOW.healthy
    assert not Verdict.SANCTIONED.healthy and not Verdict.FILTERED.healthy


def test_percentile():
    assert _percentile([], 50) is None
    assert _percentile([10.0], 95) == 10.0
    assert _percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5


def _resolver() -> Resolver:
    return Resolver("r", "R", ResolverKind.PUBLIC, ("1.1.1.1", "1.0.0.1"))


def test_resolver_score_metrics():
    s = ResolverScore(_resolver(), queries=10, answered=10, latencies=[20.0] * 10)
    assert s.success_rate == 1.0
    assert s.median_ms == 20.0
    assert s.score == 99.0  # 100 - 20/20
    s.hijacked = 5
    assert s.success_rate == 0.5
    s.unlocks, s.unlock_total = 2, 4
    assert s.score == 49.3  # 0.7 * (50 - 1) + 30 * 2/4


def test_resolver_score_empty():
    s = ResolverScore(_resolver())
    assert s.success_rate == 0.0 and s.score == 0.0 and s.median_ms is None
    assert _resolver().primary == "1.1.1.1"


def test_service_result_total_and_to_dict():
    s = Service("a", "A", "python", "pypi.org")
    r = ServiceResult(
        s,
        Verdict.OK,
        "",
        dns=Step(True, 1.0),
        tcp=Step(True, 2.0),
        tls=Step(True, 3.0),
        http=Step(True, 4.0),
    )
    assert r.total_ms == 10.0
    d = to_dict(r)
    assert d["verdict"] == "ok"
    assert d["service"]["url"] == "https://pypi.org/"
    assert d["total_ms"] == 10.0
    assert ServiceResult(s, Verdict.DNS_ERROR, "").total_ms is None


def test_to_dict_resolver_score_drops_latencies():
    d = to_dict(ResolverScore(_resolver(), queries=1, answered=1, latencies=[5.0]))
    assert "latencies" not in d
    assert d["median_ms"] == 5.0 and d["resolver"]["kind"] == "public"
    assert to_dict({"k": (1, 2)}) == {"k": [1, 2]}
    m = Mirror("m", "M", "P", "pypi", "https://x/simple")
    assert to_dict(m)["verification"] == "community-reported"
