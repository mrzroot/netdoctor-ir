import json
from pathlib import Path

import pytest

from netdoctor.backup import BackupManager
from netdoctor.configs import (
    apply_changes,
    docker_config_path,
    go_env_path,
    ini_set,
    kv_set,
    npmrc_path,
    pip_config_path,
    plan,
    plan_docker,
    plan_go,
    plan_npm,
    plan_pip,
)


def test_ini_set_new_file():
    assert (
        ini_set("", "global", "index-url", "https://m/simple")
        == "[global]\nindex-url = https://m/simple\n"
    )


def test_ini_set_preserves_comments_and_other_sections():
    text = "# my settings\n[install]\nuser = true\n\n[global]\ntimeout = 60\n"
    out = ini_set(text, "global", "index-url", "https://m/simple")
    assert out.startswith("# my settings\n[install]\nuser = true")
    assert "[global]\ntimeout = 60\nindex-url = https://m/simple\n" in out


def test_ini_set_replaces_existing_key_and_underscore_variant():
    text = "[global]\nindex_url = https://old\n[other]\nindex-url = keep\n"
    out = ini_set(text, "global", "index-url", "https://new")
    assert "index-url = https://new" in out and "https://old" not in out
    assert "index-url = keep" in out


def test_ini_set_appends_section():
    out = ini_set("[install]\nuser = true", "global", "k", "v")
    assert out == "[install]\nuser = true\n\n[global]\nk = v\n"


def test_kv_set():
    assert kv_set("", "registry", "https://r/") == "registry=https://r/\n"
    text = "save-exact=true\nregistry = https://old/\n"
    assert kv_set(text, "registry", "https://r/") == "save-exact=true\nregistry=https://r/\n"


def test_paths_per_os(tmp_path):
    env: dict[str, str] = {}
    assert pip_config_path("linux", env, tmp_path) == tmp_path / ".config/pip/pip.conf"
    assert pip_config_path("linux", {"XDG_CONFIG_HOME": "/x"}, tmp_path) == Path("/x/pip/pip.conf")
    assert pip_config_path("windows", {"APPDATA": "C:/AD"}, tmp_path) == Path("C:/AD/pip/pip.ini")
    assert pip_config_path("macos", env, tmp_path) == tmp_path / ".config/pip/pip.conf"
    legacy = tmp_path / "Library/Application Support/pip/pip.conf"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("")
    assert pip_config_path("macos", env, tmp_path) == legacy
    assert pip_config_path("linux", {"PIP_CONFIG_FILE": "/p.conf"}) == Path("/p.conf")

    assert npmrc_path({}, tmp_path) == tmp_path / ".npmrc"
    assert npmrc_path({"NPM_CONFIG_USERCONFIG": "/n"}) == Path("/n")

    assert go_env_path("linux", {}, tmp_path) == tmp_path / ".config/go/env"
    assert go_env_path("macos", {}, tmp_path) == tmp_path / "Library/Application Support/go/env"
    assert go_env_path("windows", {"APPDATA": "C:/AD"}, tmp_path) == Path("C:/AD/go/env")
    assert go_env_path("linux", {"GOENV": "/g"}) == Path("/g")
    assert go_env_path("linux", {"GOENV": "off"}, tmp_path) == tmp_path / ".config/go/env"


def test_docker_paths(tmp_path):
    path, how = docker_config_path("macos", tmp_path)
    assert path == tmp_path / ".docker/daemon.json" and "Docker Desktop" in how
    path, how = docker_config_path("linux", tmp_path)
    assert path.name == "daemon.json" and "sudo cp" in how


def test_plan_pip(tmp_path):
    target = tmp_path / "pip.conf"
    c = plan_pip("https://mirror/simple", target)
    assert c.before is None and c.changed and "index-url = https://mirror/simple" in c.after
    assert "/dev/null" in c.diff()
    insecure = plan_pip("http://plain.example/simple", target)
    assert "trusted-host = plain.example" in insecure.after and "not encrypted" in insecure.note


def test_plan_npm_and_go(tmp_path):
    c = plan_npm("https://r.example", tmp_path / ".npmrc")
    assert c.after == "registry=https://r.example/\n"
    g = plan_go("https://goproxy.example/", tmp_path / "env")
    assert g.after == "GOPROXY=https://goproxy.example,direct\n" and "go env -w" in g.note


def test_plan_docker_merges(tmp_path):
    target = tmp_path / "daemon.json"
    target.write_text(
        json.dumps({"debug": True, "registry-mirrors": ["https://old", "https://new/"]})
    )
    c = plan_docker("https://new", target)
    data = json.loads(c.after)
    assert data == {"debug": True, "registry-mirrors": ["https://new", "https://old"]}


def test_plan_docker_seed_and_errors(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text('{"log-driver": "json-file"}')
    c = plan_docker("https://m.example/path", tmp_path / "out.json", seed=seed)
    assert json.loads(c.after)["log-driver"] == "json-file"
    assert "host-only" in c.note
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    with pytest.raises(ValueError, match="not valid JSON"):
        plan_docker("https://m", bad)
    bad.write_text("[1, 2]")
    with pytest.raises(ValueError, match="JSON object"):
        plan_docker("https://m", bad)


def test_plan_docker_default_path(tmp_path, monkeypatch):
    monkeypatch.setattr("netdoctor.configs.current_os", lambda: "linux")
    c = plan_docker("https://m.example", seed=None)
    assert "sudo cp" in c.note and c.path.name == "daemon.json"


def test_plan_dispatch(tmp_path):
    assert plan("npm", "https://r", tmp_path / "x").tool == "npm"
    with pytest.raises(ValueError, match="unknown tool"):
        plan("cargo", "https://r")


def test_apply_and_restore_roundtrip(tmp_path):
    pip_conf = tmp_path / "pip.conf"
    pip_conf.write_text("[global]\ntimeout = 5\n")
    npmrc = tmp_path / "sub" / ".npmrc"  # does not exist yet
    changes = [plan_pip("https://m/simple", pip_conf), plan_npm("https://r", npmrc)]
    mgr = BackupManager(tmp_path / "nd")
    bset = apply_changes(changes, "test", mgr)
    assert bset is not None and len(bset.entries) == 2
    assert "index-url" in pip_conf.read_text() and npmrc.exists()

    actions = mgr.restore()
    assert any(a.startswith("restore") for a in actions)
    assert any(a.startswith("remove") for a in actions)
    assert pip_conf.read_text() == "[global]\ntimeout = 5\n"
    assert not npmrc.exists()


def test_apply_noop(tmp_path):
    p = tmp_path / ".npmrc"
    p.write_text("registry=https://r/\n")
    assert apply_changes([plan_npm("https://r", p)], "x", BackupManager(tmp_path)) is None
