import asyncio

import pytest

from netdoctor.models import Verdict
from netdoctor.net import HttpReply, ProbeError
from netdoctor.scanner import classify, probe_service, scan, summarize


async def test_ok_path(svc, fake_net, catalog):
    s = svc(note="all good")
    r = await probe_service(s, fake_net, catalog)
    assert r.verdict is Verdict.OK
    assert r.status == 200 and r.reason == "all good"
    assert r.total_ms == 5 + 10 + 15 + 20
    assert ("http", ("https://demo.example/x", "93.184.216.34")) in fake_net.calls


async def test_dns_failures(svc, fake_net, catalog):
    fake_net.dns["demo.example"] = ProbeError("timeout", "slow", 3000.0)
    r = await probe_service(svc(), fake_net, catalog)
    assert r.verdict is Verdict.TIMEOUT and r.dns and not r.dns.ok
    fake_net.dns["demo.example"] = ProbeError("nxdomain")
    r = await probe_service(svc(), fake_net, catalog)
    assert r.verdict is Verdict.DNS_ERROR and "does not exist" in r.reason
    fake_net.dns["demo.example"] = []
    r = await probe_service(svc(), fake_net, catalog)
    assert r.verdict is Verdict.DNS_ERROR


async def test_dns_hijack_is_filtered(svc, fake_net, catalog):
    fake_net.dns["demo.example"] = ["10.10.34.36"]
    r = await probe_service(svc(), fake_net, catalog)
    assert r.verdict is Verdict.FILTERED
    assert "10.10.34.36" in r.reason
    assert not any(c[0] == "tcp" for c in fake_net.calls)


async def test_custom_nameserver_is_used(svc, fake_net, catalog):
    fake_net.dns[("demo.example", "178.22.122.100")] = ["5.5.5.5"]
    r = await probe_service(svc(), fake_net, catalog, nameserver="178.22.122.100")
    assert r.ips == ["5.5.5.5"]


@pytest.mark.parametrize(
    ("kind", "verdict"),
    [("timeout", Verdict.TIMEOUT), ("refused", Verdict.TCP_ERROR), ("reset", Verdict.TCP_ERROR)],
)
async def test_tcp_failures(svc, fake_net, catalog, kind, verdict):
    fake_net.tcp["93.184.216.34"] = ProbeError(kind)
    r = await probe_service(svc(), fake_net, catalog)
    assert r.verdict is verdict
    assert r.tcp is not None and r.tcp.error == kind


@pytest.mark.parametrize(
    ("kind", "verdict"),
    [
        ("reset", Verdict.FILTERED),
        ("timeout", Verdict.FILTERED),
        ("cert", Verdict.FILTERED),
        ("tls", Verdict.TLS_ERROR),
    ],
)
async def test_tls_failures(svc, fake_net, catalog, kind, verdict):
    fake_net.tls["demo.example"] = ProbeError(kind)
    r = await probe_service(svc(), fake_net, catalog)
    assert r.verdict is verdict


async def test_plain_http_skips_tls(svc, fake_net, catalog):
    r = await probe_service(svc(scheme="http", port=80), fake_net, catalog)
    assert r.verdict is Verdict.OK and r.tls is None
    assert not any(c[0] == "tls" for c in fake_net.calls)


@pytest.mark.parametrize(
    ("kind", "verdict"), [("timeout", Verdict.TIMEOUT), ("reset", Verdict.HTTP_ERROR)]
)
async def test_http_failures(svc, fake_net, catalog, kind, verdict):
    fake_net.http["https://demo.example/x"] = ProbeError(kind)
    r = await probe_service(svc(), fake_net, catalog)
    assert r.verdict is verdict and r.http and not r.http.ok


async def test_private_answer_note(svc, fake_net, catalog):
    fake_net.dns["demo.example"] = ["192.168.1.10"]
    r = await probe_service(svc(), fake_net, catalog)
    assert r.verdict is Verdict.OK and "private address" in r.reason


def test_classify_variants(svc, catalog):
    s = svc(sanction_prone=True)
    docker = "Since Docker is a US company, we must comply with US export control regulations"
    v, why, sig = classify(s, HttpReply(403, 1, {}, docker), catalog)
    assert v is Verdict.SANCTIONED and sig == "docker-export-control"
    v, why, _ = classify(s, HttpReply(403, 1, {}, "nope"), catalog)
    assert v is Verdict.FORBIDDEN and "geo-block" in why
    v, why, _ = classify(svc(), HttpReply(451, 1, {}, ""), catalog)
    assert v is Verdict.FORBIDDEN and "geo-block" not in why
    v, _, _ = classify(s, HttpReply(500, 1, {}, ""), catalog)
    assert v is Verdict.HTTP_ERROR
    v, _, sig = classify(s, HttpReply(403, 1, {"cf-mitigated": "challenge"}, ""), catalog)
    assert v is Verdict.OK and sig == "bot-challenge"
    v, _, _ = classify(s, HttpReply(200, 1, {}, "see peyvandha.ir"), catalog)
    assert v is Verdict.FILTERED
    v, why, _ = classify(s, HttpReply(200, 1, {}, ""), catalog, total_ms=5000, slow_ms=1000)
    assert v is Verdict.SLOW and "5000" in why


async def test_scan_keeps_order_and_reports_progress(svc, fake_net, catalog):
    services = [svc(id=f"s{i}", host=f"h{i}.example") for i in range(6)]
    seen = []
    results = await scan(services, fake_net, catalog, concurrency=2, on_result=seen.append)
    assert [r.service.id for r in results] == [s.id for s in services]
    assert len(seen) == 6


async def test_scan_respects_concurrency(svc, catalog):
    from tests.conftest import FakeNetwork

    active = 0
    peak = 0

    class SlowNet(FakeNetwork):
        async def resolve(self, host, nameserver=None):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return await super().resolve(host, nameserver)

    services = [svc(id=f"s{i}") for i in range(8)]
    await scan(services, SlowNet(), catalog, concurrency=3)
    assert peak <= 3


def _results(svc, verdicts):
    from netdoctor.models import ServiceResult

    return [ServiceResult(svc(id=f"s{i}", name=f"S{i}"), v, "") for i, v in enumerate(verdicts)]


def test_summary_good(svc):
    s = summarize(_results(svc, [Verdict.OK] * 4))
    assert s.level == "good" and s.advice == [] and "all 4" in s.headline


def test_summary_mixed_advice(svc):
    vs = [Verdict.OK] * 6 + [
        Verdict.SANCTIONED,
        Verdict.FILTERED,
        Verdict.DNS_ERROR,
        Verdict.SLOW,
        Verdict.TLS_ERROR,
        Verdict.FORBIDDEN,
    ]
    s = summarize(_results(svc, vs))
    assert s.level == "bad"
    text = " ".join(s.advice)
    assert "netdoctor dns" in text and "mirrors" in text and "slow" in text
    assert "TCP/TLS/HTTP" in text
    assert s.counts["ok"] == 6


def test_summary_warn_and_fake_ip(svc):
    res = _results(svc, [Verdict.OK] * 9 + [Verdict.TIMEOUT])
    res[0].ips = ["198.18.0.7"]
    s = summarize(res)
    assert s.level == "warn"
    assert any("fake-IP" in a for a in s.advice)
