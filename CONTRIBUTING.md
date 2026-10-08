# Contributing to netdoctor-ir

Thanks for helping developers in Iran waste less time! Contributions of every size are welcome:
a new mirror, a changed resolver IP, a sanction page wording, a bug fix, or docs.

## The fastest way to help: catalogs

All data lives in [`netdoctor/data/`](netdoctor/data):

| File | What goes in it |
|---|---|
| `mirrors.yaml` | Package/registry mirrors (`pypi`, `npm`, `docker`, `go`, `maven`) |
| `resolvers.yaml` | DNS resolvers (`public`, `anti-sanction`, `isp`) |
| `signatures.yaml` | Fingerprints of sanction pages, block pages, bot challenges; filtering IP ranges |
| `services.yaml` | Developer services probed by `netdoctor scan` |

Rules of thumb:

- **Be honest with `verification`.** `official` = upstream itself. `documented` = the operator
  lists this exact endpoint on its own site/docs (put the link in `source`).
  `community-reported` = from a community list, not confirmed from inside Iran.
- **Always include a `source` link** for non-official entries.
- **Don't add services that require login** to probe, and keep probe paths lightweight
  (netdoctor reads at most 64 KiB).
- **Never add entries whose purpose is circumventing filtering** (VPNs, proxies, tunnels).
  netdoctor is a diagnostic and mirror-configuration tool.

Check your change:

```bash
netdoctor --catalog-dir netdoctor/data catalog validate
netdoctor mirrors -o <your-id>        # ideally run from inside Iran and paste the output in the PR
pytest tests/test_catalog.py
```

## Code changes

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev,tui]'
ruff check . && ruff format --check . && mypy netdoctor
pytest --cov
```

Guidelines:

- Python 3.10+, full type hints (`mypy --strict` must pass), docstrings on public functions.
- All I/O lives in `netdoctor/net.py`. Everything else should be testable with the fake
  network in `tests/conftest.py`. **Tests must never touch the real internet.**
- Keep heuristics in `detect.py` / `scanner.classify` pure and add a test for every new rule.
- Anything that writes files must go through `configs.apply_changes` (backup + restore).
- netdoctor must never change system settings or require root on its own.
- Add a line to `CHANGELOG.md` under *Unreleased*.

## Pull requests

1. Fork and create a branch (`feat/…`, `fix/…`, `catalog/…`).
2. Make sure the checks pass (lint, types, tests on 3.10–3.13, catalog validation).
3. Describe *what* and *why*; for catalog PRs include evidence.

## Code of conduct

Be kind and constructive. Harassment or discrimination of any kind isn't tolerated.
Maintainers may remove comments or contributions that violate this.
