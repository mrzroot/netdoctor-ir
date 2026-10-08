## What & why

<!-- Short description of the change and the motivation. -->

## Checklist

- [ ] `ruff check . && ruff format --check . && mypy netdoctor` pass
- [ ] `pytest` passes (tests don't touch the real internet)
- [ ] Catalog changes: `netdoctor catalog validate` passes, `source` links included, `verification` is honest
- [ ] `CHANGELOG.md` updated under *Unreleased*
