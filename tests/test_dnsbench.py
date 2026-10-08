from netdoctor.dnsbench import benchmark, explain, rank, reference_answers
from netdoctor.models import Resolver, ResolverKind, ResolverScore, Verdict
from netdoctor.net import HttpReply, ProbeError

FAST = Resolver("fast", "Fast", ResolverKind.PUBLIC, ("1.1.1.1", "1.0.0.1"))
SLOW = Resolver("slow", "Slow", ResolverKind.PUBLIC, ("9.9.9.9",))
DEAD = Resolver("dead", "Dead", ResolverKind.ANTI_SANCTION, ("10.202.10.202",), iran_only=True)
GONE = Resolver("gone", "Gone", ResolverKind.PUBLIC, ("4.4.4.4",))
EVIL = Resolver("evil", "Evil", ResolverKind.ISP, ("2.2.2.2",))
PROXY = Resolver("proxy", "Proxy", ResolverKind.ANTI_SANCTION, ("3.3.3.3",))
HOSTS = ["pypi.org", "registry-1.docker.io"]


def _net(fake_net):
    for h in HOSTS:
        fake_net.dns[(h, "1.1.1.1")] = (["151.101.0.1"], 8.0)
        fake_net.dns[(h, "1.0.0.1")] = (["151.101.0.2"], 30.0)
        fake_net.dns[(h, "9.9.9.9")] = (["151.101.64.1"], 400.0)
        fake_net.dns[(h, "10.202.10.202")] = ProbeError("timeout")
        fake_net.dns[(h, "4.4.4.4")] = ProbeError("no-answer")
        fake_net.dns[(h, "2.2.2.2")] = (["10.10.34.35"], 5.0)
        fake_net.dns[(h, "3.3.3.3")] = (["178.22.122.101"], 20.0)
        fake_net.dns[(h, "ref")] = ["151.101.1.1"]
    return fake_net


async def test_reference_answers(fake_net):
    _net(fake_net)
    fake_net.dns[("gitlab.com", "ref")] = ProbeError("timeout")
    ref = await reference_answers([*HOSTS, "gitlab.com"], fake_net, "ref")
    assert ref["pypi.org"] == {"151.101.1.1"} and ref["gitlab.com"] == set()


async def test_benchmark_ranks_and_counts(fake_net, catalog):
    _net(fake_net)
    ref = await reference_answers(HOSTS, fake_net, "ref")
    scores = await benchmark(
        [DEAD, SLOW, EVIL, FAST, PROXY, GONE], HOSTS, fake_net, catalog, reference=ref
    )
    by_id = {s.resolver.id: s for s in scores}
    assert scores[0].resolver.id == "fast"
    assert by_id["fast"].best_address == "1.1.1.1"
    assert by_id["fast"].queries == 4 and by_id["fast"].success_rate == 1.0
    assert by_id["slow"].score < by_id["fast"].score
    assert by_id["evil"].hijacked == 2 and by_id["evil"].success_rate == 0.0
    assert by_id["proxy"].differs == 2 and by_id["fast"].differs == 0
    assert by_id["dead"].timeouts == 2 and by_id["dead"].score == 0
    assert by_id["gone"].errors == 2
    assert scores[-1].score == 0


async def test_benchmark_deep_unlocks(fake_net, catalog, svc):
    _net(fake_net)
    docker = svc(id="docker", host="registry-1.docker.io", path="/v2/", expect=(200, 401))
    pypi = svc(id="pypi", host="pypi.org", path="/simple/")
    blocked = "Since Docker is a US company, we must comply with US export control regulations"

    def docker_reply(url, ip):
        if ip == "178.22.122.101":
            return HttpReply(401, 10.0, {}, "")
        return HttpReply(403, 10.0, {}, blocked)

    fake_net.http[docker.url] = docker_reply
    fake_net.http[pypi.url] = HttpReply(200, 5.0, {}, "")
    seen = []
    scores = await benchmark(
        [FAST, PROXY, EVIL, DEAD],
        HOSTS,
        fake_net,
        catalog,
        deep_services=[docker, pypi],
        on_done=seen.append,
    )
    by_id = {s.resolver.id: s for s in scores}
    assert (by_id["proxy"].unlocks, by_id["proxy"].unlock_total) == (2, 2)
    assert by_id["fast"].unlocks == 1
    assert by_id["evil"].unlocks == 0  # hijacked answers never unlock
    assert by_id["dead"].unlocks is None  # never answered, never deep-checked
    assert len(seen) == 4
    assert scores[0].resolver.id == "proxy"  # unblock bonus beats raw speed


async def test_deep_check_http_error_counts_as_locked(fake_net, catalog, svc):
    _net(fake_net)
    s = svc(host="pypi.org")
    fake_net.http[s.url] = ProbeError("reset")
    (score,) = await benchmark([FAST], HOSTS, fake_net, catalog, deep_services=[s])
    assert score.unlocks == 0


def test_rank_tiebreak():
    a = ResolverScore(FAST, queries=1, answered=1, latencies=[10.0])
    b = ResolverScore(SLOW, queries=1, answered=1, latencies=[10.0])
    assert [s.resolver.id for s in rank([b, a])] == ["fast", "slow"]


def test_explain_messages():
    assert "Iranian networks" in explain(ResolverScore(DEAD, queries=2, timeouts=2))
    assert "unreachable" in explain(ResolverScore(GONE, queries=2, errors=2))
    assert explain(ResolverScore(FAST, queries=1, answered=1, latencies=[1.0])) == "Clean answers."
    s = ResolverScore(
        PROXY,
        queries=4,
        answered=3,
        timeouts=1,
        hijacked=1,
        differs=1,
        latencies=[1.0] * 3,
        unlocks=1,
        unlock_total=2,
    )
    text = explain(s)
    for bit in ("hijacked", "timeout", "rewritten", "unblocked 1/2"):
        assert bit in text
    assert Verdict.OK.value == "ok"
