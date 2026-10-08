from rich.console import Console

from netdoctor.models import (
    Mirror,
    MirrorResult,
    Resolver,
    ResolverKind,
    ResolverScore,
    ServiceResult,
    Step,
    Verdict,
)
from netdoctor.osapply import dns_instructions
from netdoctor.render import (
    dns_footnotes,
    dns_table,
    instructions_panel,
    mirrors_table,
    ms_text,
    print_scan,
    step_text,
)
from netdoctor.scanner import summarize


def _console(width=160):
    return Console(width=width, record=True, color_system=None)


def test_scan_render_full_and_compact(svc):
    res = [
        ServiceResult(
            svc(id="a", name="Alpha"),
            Verdict.OK,
            "",
            dns=Step(True, 5),
            tcp=Step(True, 50),
            tls=Step(True, 900),
            http=Step(True, 10),
            status=200,
        ),
        ServiceResult(
            svc(id="b", name="Beta", category="go"),
            Verdict.FILTERED,
            "TLS reset",
            dns=Step(True, 5),
            tcp=Step(True, 5),
            tls=Step(False, 1, "reset"),
        ),
    ]
    for width, has_area in ((160, True), (90, False)):
        c = _console(width)
        print_scan(c, res, summarize(res))
        out = c.export_text()
        assert "Alpha" in out and "FILTERED" in out and "Verdict" in out
        assert ("Area" in out) is has_area


def test_helpers():
    assert ms_text(None).plain == "—" and ms_text(10).style == "green"
    assert ms_text(300).style == "yellow" and ms_text(9000).style == "red"
    assert step_text(None).plain == "—"
    assert step_text(Step(False, None, None)).plain == "fail"


def _scores():
    fast = ResolverScore(
        Resolver("c", "Cloud", ResolverKind.PUBLIC, ("1.1.1.1",)),
        queries=2,
        answered=2,
        latencies=[5, 6],
        unlocks=1,
        unlock_total=2,
    )
    dead = ResolverScore(
        Resolver(
            "s", "Shecan", ResolverKind.ANTI_SANCTION, ("1.2.3.4",), name_fa="شکن", iran_only=True
        ),
        queries=2,
        timeouts=2,
    )
    return [fast, dead]


def test_dns_render():
    for width in (160, 80):
        c = _console(width)
        c.print(dns_table(_scores(), width=width))
        out = c.export_text()
        assert "Cloud" in out and "Unblocks" in out
    notes = dns_footnotes(_scores())
    assert any("Iran-only" in n for n in notes)


def test_mirrors_and_instructions_render():
    res = [
        MirrorResult(
            Mirror("pypi-a", "A mirror", "P", "pypi", "https://a"), Verdict.OK, "", 200, 50
        ),
        MirrorResult(
            Mirror("npm-b", "B mirror", "P", "npm", "https://b"), Verdict.TIMEOUT, "ConnectTimeout"
        ),
    ]
    for width in (160, 80):
        c = _console(width)
        c.print(mirrors_table(res, width=width))
        out = c.export_text()
        assert "★" in out and "TIMEOUT" in out
    c = _console()
    r = _scores()[0].resolver
    c.print(instructions_panel("Switch", dns_instructions(r, "linux")))
    assert "resolvectl" in c.export_text()
