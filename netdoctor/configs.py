"""Plan and write tool configuration for a chosen mirror.

Supported tools: pip (``pip.conf``/``pip.ini``), npm (``.npmrc``), Docker
(``daemon.json`` ``registry-mirrors``) and Go (``GOPROXY`` in Go's env file).
Existing content and comments are preserved; only the relevant key changes.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from netdoctor.backup import BackupManager, BackupSet, netdoctor_home
from netdoctor.osapply import current_os

TOOLS = ("pip", "npm", "docker", "go")
ECOSYSTEM_TOOL = {"pypi": "pip", "npm": "npm", "docker": "docker", "go": "go"}


@dataclass
class ConfigChange:
    """A planned edit of one config file."""

    tool: str
    path: Path
    before: str | None
    after: str
    note: str = ""

    @property
    def changed(self) -> bool:
        """True if writing would modify the file."""
        return self.before != self.after

    def diff(self) -> str:
        """Unified diff between current and planned content."""
        return "".join(
            difflib.unified_diff(
                (self.before or "").splitlines(keepends=True),
                self.after.splitlines(keepends=True),
                fromfile=f"{self.path} (current)" if self.before is not None else "/dev/null",
                tofile=f"{self.path} (netdoctor)",
            )
        )


# --------------------------------------------------------------------------- paths


def _env(env: dict[str, str] | None) -> dict[str, str]:
    return dict(os.environ) if env is None else env


def pip_config_path(
    os_name: str | None = None, env: dict[str, str] | None = None, home: Path | None = None
) -> Path:
    """User-level pip config file for this OS (honours ``PIP_CONFIG_FILE``)."""
    e, h, osn = _env(env), home or Path.home(), os_name or current_os()
    if e.get("PIP_CONFIG_FILE"):
        return Path(e["PIP_CONFIG_FILE"]).expanduser()
    if osn == "windows":
        return Path(e.get("APPDATA", h / "AppData" / "Roaming")) / "pip" / "pip.ini"
    if osn == "macos":
        legacy = h / "Library" / "Application Support" / "pip" / "pip.conf"
        if legacy.exists():
            return legacy
    xdg = Path(e["XDG_CONFIG_HOME"]) if e.get("XDG_CONFIG_HOME") else h / ".config"
    return xdg / "pip" / "pip.conf"


def npmrc_path(env: dict[str, str] | None = None, home: Path | None = None) -> Path:
    """User-level ``.npmrc`` (honours ``NPM_CONFIG_USERCONFIG``)."""
    e = _env(env)
    if e.get("NPM_CONFIG_USERCONFIG"):
        return Path(e["NPM_CONFIG_USERCONFIG"]).expanduser()
    return (home or Path.home()) / ".npmrc"


def go_env_path(
    os_name: str | None = None, env: dict[str, str] | None = None, home: Path | None = None
) -> Path:
    """Go's user env file — the one ``go env -w`` edits (honours ``GOENV``)."""
    e, h, osn = _env(env), home or Path.home(), os_name or current_os()
    if e.get("GOENV") and e["GOENV"] != "off":
        return Path(e["GOENV"]).expanduser()
    if osn == "windows":
        return Path(e.get("APPDATA", h / "AppData" / "Roaming")) / "go" / "env"
    if osn == "macos":
        return h / "Library" / "Application Support" / "go" / "env"
    xdg = Path(e["XDG_CONFIG_HOME"]) if e.get("XDG_CONFIG_HOME") else h / ".config"
    return xdg / "go" / "env"


def docker_config_path(os_name: str | None = None, home: Path | None = None) -> tuple[Path, str]:
    """Where netdoctor writes ``daemon.json`` and what to do afterwards.

    Docker Desktop (macOS/Windows) reads ``~/.docker/daemon.json``. On Linux the daemon
    reads ``/etc/docker/daemon.json`` (root-owned), so netdoctor writes a staged copy
    under ``~/.netdoctor/out`` and prints the ``sudo cp`` command instead of needing root.
    """
    h, osn = home or Path.home(), os_name or current_os()
    if osn in ("macos", "windows"):
        return h / ".docker" / "daemon.json", "Restart Docker Desktop to apply."
    staged = netdoctor_home() / "out" / "daemon.json"
    return staged, (
        f"Apply with:  sudo cp {staged} /etc/docker/daemon.json && sudo systemctl restart docker"
    )


# --------------------------------------------------------------------------- editors


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def ini_set(text: str, section: str, key: str, value: str) -> str:
    """Set ``key = value`` in ``[section]`` of INI ``text``, preserving everything else."""
    lines = text.splitlines()
    sec_re = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
    key_pat = "[-_]".join(re.escape(part) for part in key.split("-"))
    key_re = re.compile(rf"^\s*{key_pat}\s*[=:]")
    in_sec, sec_start, insert_at = False, None, None
    for i, line in enumerate(lines):
        m = sec_re.match(line)
        if m:
            if in_sec:
                break
            in_sec = m.group("name").strip() == section
            if in_sec:
                sec_start = insert_at = i + 1
            continue
        if in_sec:
            if key_re.match(line):
                lines[i] = f"{key} = {value}"
                return "\n".join(lines) + "\n"
            if line.strip():
                insert_at = i + 1
    if sec_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"[{section}]", f"{key} = {value}"]
    else:
        lines.insert(insert_at or sec_start, f"{key} = {value}")
    return "\n".join(lines) + "\n"


def kv_set(text: str, key: str, value: str) -> str:
    """Set ``key=value`` in a flat ``KEY=VALUE`` file (``.npmrc``, Go env)."""
    lines = text.splitlines()
    key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for i, line in enumerate(lines):
        if key_re.match(line):
            lines[i] = f"{key}={value}"
            return "\n".join(lines) + "\n"
    lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- planners


def plan_pip(index_url: str, path: Path | None = None) -> ConfigChange:
    """Point pip's ``index-url`` at ``index_url``."""
    target = path or pip_config_path()
    before = _read(target)
    after = ini_set(before or "", "global", "index-url", index_url)
    note = ""
    parsed = urlparse(index_url)
    if parsed.scheme == "http" and parsed.hostname:
        after = ini_set(after, "global", "trusted-host", parsed.hostname)
        note = "Plain-HTTP index: added trusted-host (traffic is not encrypted)."
    return ConfigChange("pip", target, before, after, note)


def plan_npm(registry: str, path: Path | None = None) -> ConfigChange:
    """Point npm's ``registry`` at ``registry``."""
    target = path or npmrc_path()
    before = _read(target)
    url = registry if registry.endswith("/") else registry + "/"
    return ConfigChange("npm", target, before, kv_set(before or "", "registry", url))


def plan_go(proxy: str, path: Path | None = None) -> ConfigChange:
    """Set ``GOPROXY=<proxy>,direct`` in Go's env file."""
    target = path or go_env_path()
    before = _read(target)
    after = kv_set(before or "", "GOPROXY", f"{proxy.rstrip('/')},direct")
    return ConfigChange(
        "go",
        target,
        before,
        after,
        "Same effect as: go env -w GOPROXY=" + f"{proxy.rstrip('/')},direct",
    )


def plan_docker(
    mirror_url: str, path: Path | None = None, seed: Path | None = Path("/etc/docker/daemon.json")
) -> ConfigChange:
    """Add ``mirror_url`` first in ``registry-mirrors``, keeping all other settings."""
    target, howto = (path, "") if path else docker_config_path()
    before = _read(target)
    source = before
    if source is None and seed is not None:
        try:
            source = _read(seed)
        except OSError:
            source = None
    try:
        data = json.loads(source) if source and source.strip() else {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"{target}: existing daemon.json is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{target}: daemon.json must contain a JSON object")
    mirror = mirror_url.rstrip("/")
    current = [m for m in data.get("registry-mirrors", []) if m.rstrip("/") != mirror]
    data["registry-mirrors"] = [mirror, *current]
    notes = [howto] if howto else []
    if urlparse(mirror).path not in ("", "/"):
        notes.append("Warning: Docker expects host-only mirror URLs; this one has a path.")
    return ConfigChange(
        "docker", target, before, json.dumps(data, indent=2) + "\n", " ".join(notes)
    )


def plan(tool: str, url: str, path: Path | None = None) -> ConfigChange:
    """Dispatch to the planner for ``tool``."""
    planners = {"pip": plan_pip, "npm": plan_npm, "go": plan_go, "docker": plan_docker}
    if tool not in planners:
        raise ValueError(f"unknown tool '{tool}' (expected one of {', '.join(TOOLS)})")
    return planners[tool](url, path)


def apply_changes(
    changes: list[ConfigChange], label: str, manager: BackupManager | None = None
) -> BackupSet | None:
    """Back up then write every changed file. Returns the backup set (None if no-op)."""
    todo = [c for c in changes if c.changed]
    if not todo:
        return None
    bset = (manager or BackupManager()).create(label, [c.path for c in todo])
    for c in todo:
        c.path.parent.mkdir(parents=True, exist_ok=True)
        c.path.write_text(c.after, encoding="utf-8")
    return bset
