import pytest

from netdoctor.backup import BackupError, BackupManager, netdoctor_home


def test_home_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NETDOCTOR_HOME", str(tmp_path / "x"))
    assert netdoctor_home() == tmp_path / "x"
    monkeypatch.delenv("NETDOCTOR_HOME")
    assert netdoctor_home().name == ".netdoctor"


def test_create_list_restore(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("v1")
    mgr = BackupManager(tmp_path / "nd")
    assert mgr.sets() == []
    first = mgr.create("one", [f, tmp_path / "missing.txt"])
    second = mgr.create("two", [f])
    assert first.id != second.id
    assert [s.label for s in mgr.sets()] == ["two", "one"]
    f.write_text("v2")
    actions = mgr.restore(first.id, dry_run=True)
    assert f.read_text() == "v2"
    assert "skip" in actions[1]
    mgr.restore(first.id)
    assert f.read_text() == "v1"
    assert mgr.get(first.id).restored
    # latest not-yet-restored is "two"
    assert mgr.get().id == second.id
    mgr.restore()
    with pytest.raises(BackupError, match="no backups"):
        mgr.get()
    with pytest.raises(BackupError, match="no backup with id"):
        mgr.get("nope")


def test_corrupt_manifest_is_skipped(tmp_path):
    mgr = BackupManager(tmp_path)
    mgr.create("ok", [])
    bad = mgr.root / "broken"
    bad.mkdir()
    (bad / "manifest.json").write_text("{not json")
    assert [s.label for s in mgr.sets()] == ["ok"]
