import json

from netdoctor.models import (
    Mirror,
    MirrorResult,
    Resolver,
    ResolverKind,
    ResolverScore,
    ServiceResult,
    Verdict,
)
from netdoctor.report import build_report, to_markdown
from netdoctor.scanner import summarize


def test_report_roundtrip(svc):
    results = [ServiceResult(svc(), Verdict.SANCTIONED, "HTTP 403 | blocked", status=403)]
    score = ResolverScore(
        Resolver("r", "R", ResolverKind.PUBLIC, ("1.1.1.1",)),
        queries=2,
        answered=2,
        latencies=[5.0, 7.0],
        best_address="1.1.1.1",
    )
    mres = [
        MirrorResult(
            Mirror("pypi-x", "X", "P", "pypi", "https://x/simple"), Verdict.OK, "fine", 200, 120.0
        )
    ]
    rep = build_report(
        scan=results, summary=summarize(results), dns=[score], mirrors=mres, resolver="system"
    )
    json.dumps(rep)  # serialisable
    assert rep["scan"]["results"][0]["verdict"] == "sanctioned"
    assert rep["dns"][0]["rank"] == 1 and rep["mirrors"]["best"] == {"pypi": "pypi-x"}
    md = to_markdown(rep)
    assert "# netdoctor report" in md
    assert "HTTP 403 \\| blocked" in md  # pipes escaped
    assert "| pypi | X ★ |" in md
    assert "| 1 | R | public | `1.1.1.1` | 2/2 | 6 ms |" in md


def test_report_partial():
    rep = build_report()
    assert "scan" not in rep and "dns" not in rep
    assert "netdoctor report" in to_markdown(rep)
