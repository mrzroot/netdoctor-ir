"""Automatic backups for every file netdoctor writes, and ``netdoctor restore``.

Each ``--write`` creates a backup set under ``~/.netdoctor/backups/<id>/`` containing a
``manifest.json`` and copies of the original files. Files that did not exist before are
recorded too, so restoring removes them again.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ENV_HOME = "NETDOCTOR_HOME"


def netdoctor_home() -> Path:
    """Directory for netdoctor state (``$NETDOCTOR_HOME`` or ``~/.netdoctor``)."""
    raw = os.environ.get(ENV_HOME)
    return Path(raw).expanduser() if raw else Path.home() / ".netdoctor"


@dataclass
class BackupEntry:
    """One file captured in a backup set."""

    path: str
    existed: bool
    stored: str | None = None


@dataclass
class BackupSet:
    """A group of files backed up by one netdoctor command."""

    id: str
    created: str
    label: str
    entries: list[BackupEntry] = field(default_factory=list)
    restored: bool = False


class BackupError(RuntimeError):
    """Raised when a backup set is missing or cannot be restored."""


class BackupManager:
    """Create, list and restore backup sets."""

    def __init__(self, home: Path | None = None) -> None:
        self.root = (home or netdoctor_home()) / "backups"

    # -- creation ------------------------------------------------------------------
    def create(self, label: str, paths: list[Path]) -> BackupSet:
        """Snapshot ``paths`` (existing or not) into a new backup set."""
        now = datetime.now(timezone.utc)
        base = now.strftime("%Y%m%d-%H%M%S")
        bid, n = base, 1
        while (self.root / bid).exists():
            n += 1
            bid = f"{base}-{n}"
        folder = self.root / bid
        folder.mkdir(parents=True)
        bset = BackupSet(id=bid, created=now.isoformat(timespec="seconds"), label=label)
        for i, p in enumerate(dict.fromkeys(Path(x).expanduser().resolve() for x in paths)):
            if p.is_file():
                stored = f"{i:02d}-{p.name}"
                shutil.copy2(p, folder / stored)
                bset.entries.append(BackupEntry(str(p), True, stored))
            else:
                bset.entries.append(BackupEntry(str(p), False))
        self._save(bset)
        return bset

    def _save(self, bset: BackupSet) -> None:
        (self.root / bset.id / "manifest.json").write_text(
            json.dumps(asdict(bset), indent=2), encoding="utf-8"
        )

    # -- query ---------------------------------------------------------------------
    def sets(self) -> list[BackupSet]:
        """All backup sets, newest first."""
        if not self.root.is_dir():
            return []
        sets: list[BackupSet] = []
        for manifest in self.root.glob("*/manifest.json"):
            try:
                raw = json.loads(manifest.read_text(encoding="utf-8"))
                raw["entries"] = [BackupEntry(**e) for e in raw.get("entries", [])]
                sets.append(BackupSet(**raw))
            except (ValueError, TypeError):
                continue
        return sorted(sets, key=lambda s: s.id, reverse=True)

    def get(self, backup_id: str | None = None) -> BackupSet:
        """Return a backup set by id, or the newest not-yet-restored one."""
        sets = self.sets()
        if backup_id:
            for s in sets:
                if s.id == backup_id:
                    return s
            raise BackupError(f"no backup with id '{backup_id}'")
        for s in sets:
            if not s.restored:
                return s
        raise BackupError("no backups to restore")

    # -- restore -------------------------------------------------------------------
    def restore(self, backup_id: str | None = None, *, dry_run: bool = False) -> list[str]:
        """Put files back as they were. Returns a human-readable list of actions."""
        bset = self.get(backup_id)
        folder = self.root / bset.id
        actions: list[str] = []
        for e in bset.entries:
            target = Path(e.path)
            if e.existed and e.stored:
                actions.append(f"restore {target}")
                if not dry_run:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(folder / e.stored, target)
            elif target.exists():
                actions.append(f"remove {target} (did not exist before)")
                if not dry_run:
                    target.unlink()
            else:
                actions.append(f"skip {target} (already absent)")
        if not dry_run:
            bset.restored = True
            self._save(bset)
        return actions
