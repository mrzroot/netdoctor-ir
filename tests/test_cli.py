"""End-to-end CLI tests with the fake network (no real I/O)."""

import json
import re
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from netdoctor import __version__, cli
from netdoctor.mirrors import probe_url
from netdoctor.net import HttpReply, ProbeError
from tests.conftest import FakeNetwork

runner = CliRunner()


@pytest.fixture
def net(monkeypatch):
    fake = FakeNetwork()
    monkeypatch.setattr(cli, "make_network", lambda timeout, nameservers=None: fake)
    return fake


ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def invoke(*args, width=200):
    """Run the CLI; output is ANSI-stripped so assertions work with or without a TTY."""
    res = runner.invoke(cli.app, list(args), env={"COLUMNS": str(width)})
    return SimpleNamespace(exit_code=res.exit_code, output=ANSI.sub("", res.output))


def test_version():
    assert __version__ in invoke("--version").output
    assert __version__ in invoke("version").output


def test_help_mentions_commands():
    out = invoke("--help").output
    for cmd in ("scan", "dns", "mirrors", "restore", "report", "tui", "catalog"):
        assert cmd in out


def test_scan_table(net):
    docker = "Since Docker is a US company, we must comply with US export control regulations"
    net.http["https://registry-1.docker.io/v2/"] = HttpReply(403, 10, {}, docker)
    res = invoke("scan", "--only", "pypi,docker-registry")
    assert res.exit_code == 0, res.output
    assert "SANCTIONED" in res.output and "PyPI" in res.output
    assert "Verdict" in res.output


def test_scan_json_strict_and_resolver(net):
    net.dns[("pypi.org", "178.22.122.100")] = ["10.10.34.35"]
    res = invoke("scan", "--only", "pypi", "--resolver", "shecan", "--json", "--strict")
    assert res.exit_code == 1
    data = json.loads(res.output)
    assert data["resolver"].startswith("Shecan")
    assert data["scan"]["results"][0]["verdict"] == "filtered"


def test_scan_category_and_errors(net):
    res = invoke("scan", "--category", "go")
    assert res.exit_code == 0 and "Go module proxy" in res.output
    assert invoke("scan", "--only", "nope").exit_code == 2
    assert invoke("scan", "--category", "nope").exit_code == 2
    assert invoke("scan", "--resolver", "not-an-ip").exit_code == 2
    assert invoke("scan", "--only", "pypi", "--resolver", "9.9.9.9").exit_code == 0


def test_dns_ranking_and_hint(net):
    res = invoke("dns", "--only", "cloudflare,google", "--domain", "pypi.org")
    assert res.exit_code == 0, res.output
    assert "Cloudflare" in res.output and "Best right now" in res.output


def test_dns_compact_footnotes(net):
    net.dns[("pypi.org", "178.22.122.100")] = ProbeError("timeout")
    net.dns[("pypi.org", "185.51.200.2")] = ProbeError("timeout")
    res = invoke("dns", "--only", "cloudflare,shecan", "-d", "pypi.org", width=90)
    assert "Iran-only" in res.output


def test_dns_apply_prints_and_saves_script(net, tmp_path):
    script = tmp_path / "dns.sh"
    res = invoke(
        "dns",
        "--only",
        "cloudflare,shecan",
        "-d",
        "pypi.org",
        "--apply",
        "--use",
        "shecan",
        "--os",
        "macos",
        "--script",
        str(script),
    )
    assert res.exit_code == 0, res.output
    assert "networksetup" in res.output and "never changes system settings" in res.output
    assert "178.22.122.100" in script.read_text()


def test_dns_json_deep_and_kind(net):
    res = invoke(
        "dns", "--kind", "public", "--only", "cloudflare", "-d", "pypi.org", "--deep", "--json"
    )
    data = json.loads(res.output)
    assert data[0]["resolver"]["id"] == "cloudflare" and data[0]["unlock_total"] > 0


def test_dns_errors(net):
    assert invoke("dns", "--only", "nope").exit_code == 2
    assert invoke("dns", "--kind", "isp", "--only", "cloudflare").exit_code == 2
    assert (
        invoke("dns", "--only", "cloudflare", "-d", "x.org", "--apply", "--use", "nope").exit_code
        == 2
    )


def test_dns_nothing_answers(net):
    for ns in ("1.1.1.1", "1.0.0.1"):
        net.dns[("x.org", ns)] = ProbeError("timeout")
    res = invoke("dns", "--only", "cloudflare", "-d", "x.org")
    assert "No resolver answered" in res.output


def _mirror_replies(net, catalog):
    for m in catalog.mirrors:
        net.http[probe_url(m)] = ProbeError("timeout", "ConnectTimeout")
    ok = {
        "pypi-runflare": HttpReply(200, 40, {}, '<a href="pip-24.tar.gz">'),
        "npm-runflare": HttpReply(200, 40, {}, '{"name":"is-number"}'),
        "docker-arvancloud": HttpReply(401, 40, {}, ""),
        "go-runflare": HttpReply(200, 40, {}, "v0.1.0"),
        "maven-official": HttpReply(200, 10, {}, "<metadata>"),
    }
    by_id = {m.id: m for m in catalog.mirrors}
    for mid, reply in ok.items():
        net.http[probe_url(by_id[mid])] = reply


def test_mirrors_table_and_json(net, catalog):
    _mirror_replies(net, catalog)
    res = invoke("mirrors", "-e", "pypi,npm")
    assert res.exit_code == 0 and "pypi-runflare" in res.output and "★" in res.output
    data = json.loads(invoke("mirrors", "--json").output)
    assert data["best"]["docker"] == "docker-arvancloud"


def test_mirrors_write_and_restore(net, catalog, isolated_home, tmp_path):
    _mirror_replies(net, catalog)
    pip_conf = isolated_home / "pip.conf"
    pip_conf.write_text("[global]\ntimeout = 30\n")
    daemon = tmp_path / "daemon.json"

    dry = invoke("mirrors", "--write", "--dry-run", "--docker-config", str(daemon))
    assert "Dry run" in dry.output and "timeout = 30" in pip_conf.read_text()
    assert "index-url" not in pip_conf.read_text()

    res = invoke("mirrors", "--write", "--yes", "--docker-config", str(daemon))
    assert res.exit_code == 0, res.output
    assert "mirror-pypi.runflare.com" in pip_conf.read_text()
    assert "mirror-npm.runflare.com" in (isolated_home / ".npmrc").read_text()
    assert "mirror-go.runflare.com" in (isolated_home / "go.env").read_text()
    assert json.loads(daemon.read_text())["registry-mirrors"] == ["https://docker.arvancloud.ir"]

    listed = invoke("restore", "--list")
    assert "mirrors --write" in listed.output and "active" in listed.output
    assert "would restore" in invoke("restore", "--dry-run").output
    res = invoke("restore")
    assert res.exit_code == 0 and "Restored" in res.output
    assert pip_conf.read_text() == "[global]\ntimeout = 30\n"
    assert not daemon.exists() and not (isolated_home / ".npmrc").exists()
    assert invoke("restore").exit_code == 1  # nothing left


def test_mirrors_write_upstream_best_is_noop(net, catalog):
    official = next(m for m in catalog.mirrors if m.id == "pypi-official")
    net.http[probe_url(official)] = HttpReply(200, 10, {}, "pip-24.0.tar.gz")
    res = invoke("mirrors", "-o", "pypi-official", "--write", "--yes")
    assert "nothing to change" in res.output and "Nothing to write" in res.output


def test_mirrors_write_confirm_abort(net, catalog):
    _mirror_replies(net, catalog)
    res = runner.invoke(
        cli.app, ["mirrors", "-e", "npm", "--write"], input="n\n", env={"COLUMNS": "200"}
    )
    assert "Aborted" in res.output


def test_mirrors_use_pin(net, catalog, isolated_home):
    _mirror_replies(net, catalog)
    res = invoke("mirrors", "-e", "pypi", "--use", "pypi=pypi-tuna", "--write", "--yes")
    assert res.exit_code == 0, res.output
    assert "writing it anyway" in res.output
    assert "tuna.tsinghua" in (isolated_home / "pip.conf").read_text()


def test_mirrors_errors(net):
    assert invoke("mirrors", "-e", "cargo").exit_code == 2
    assert invoke("mirrors", "-o", "nope").exit_code == 2
    assert invoke("mirrors", "--use", "pypi").exit_code == 2
    assert invoke("mirrors", "--use", "pypi=npm-official").exit_code == 2
    assert invoke("mirrors", "-e", "maven", "-o", "pypi-official").exit_code == 2


def test_mirrors_bad_docker_json(net, catalog, tmp_path):
    _mirror_replies(net, catalog)
    bad = tmp_path / "daemon.json"
    bad.write_text("{oops")
    res = invoke("mirrors", "-e", "docker", "--write", "--yes", "--docker-config", str(bad))
    assert "not valid JSON" in res.output


def test_restore_list_empty():
    assert "No backups yet" in invoke("restore", "--list").output


def test_report_json_and_md(net, catalog, tmp_path):
    _mirror_replies(net, catalog)
    j, m = tmp_path / "r.json", tmp_path / "r.md"
    res = invoke("report", "--json", str(j), "--md", str(m))
    assert res.exit_code == 0, res.output
    data = json.loads(j.read_text())
    assert {"scan", "dns", "mirrors"} <= set(data)
    assert "## Developer services" in m.read_text()


def test_report_stdout_and_skips(net):
    res = invoke("report", "--md", "-", "--skip-dns", "--skip-mirrors", "-r", "1.1.1.1")
    assert res.exit_code == 0
    assert "# netdoctor report" in res.output and "## DNS resolvers" not in res.output


def test_report_default_path(net, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke("report", "--skip-dns", "--skip-mirrors")
    assert (tmp_path / "netdoctor-report.md").exists()


def test_catalog_commands(tmp_path):
    assert "catalog OK" in invoke("catalog", "validate").output
    for kind, needle in (
        ("services", "pypi.org"),
        ("resolvers", "178.22.122.100"),
        ("mirrors", "pypi-runflare"),
    ):
        assert needle in invoke("catalog", "list", kind).output
    assert invoke("catalog", "list", "nope").exit_code == 2
    (tmp_path / "services.yaml").write_text("services: []\n")
    res = invoke("--catalog-dir", str(tmp_path), "catalog", "validate")
    assert res.exit_code == 2 and "Catalog error" in res.output


def test_no_color_flag(net):
    assert invoke("--no-color", "scan", "--only", "pypi").exit_code == 0


def test_tui_missing_textual(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "netdoctor.tui":
            raise ImportError("no textual")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    res = invoke("tui")
    assert res.exit_code == 2 and "netdoctor-ir[tui]" in res.output
