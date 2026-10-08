# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- GitHub Actions CI enabled (moved from `.github/pending-workflows/`); CI badge in README.

## [0.1.0] - 2026-10-08

First public release.

### Added
- `netdoctor scan`: concurrent DNS → TCP → TLS → HTTP probes of 38 developer services, with
  verdicts (`ok`, `slow`, `sanctioned`, `filtered`, `forbidden`, `dns/tcp/tls/http-error`,
  `timeout`), plain-language reasons and a summary with advice. `--resolver` tests a
  resolver's answers end-to-end (IP-pinned HTTP with original Host/SNI). `--json`, `--strict`.
- Detection of DNS hijacks (`10.10.34.0/24`, loopback, null route), SNI-filtering fingerprints
  (TLS reset/stall after TCP connect), certificate interception, block pages and redirects
  (`peyvandha.ir`), sanction pages (Docker export control, Google 403, OpenAI unsupported
  country, Cloudflare 1009, CloudFront geo-block, GitLab embargo, generic markers), Cloudflare
  bot challenges (not counted as failures) and fake-IP proxies (`198.18.0.0/15`).
- `netdoctor dns`: benchmark of 13 public, Iranian anti-sanction and ISP resolvers via
  dnspython; ranking by success rate and latency; hijack and rewritten-answer counts; `--deep`
  "unblocks" check; `--apply` prints (and `--script` saves) per-OS commands, never runs them.
- `netdoctor mirrors`: content-verified checks of 37 PyPI / npm / Docker / Go / Maven mirrors
  with trust levels (`official`, `documented`, `community-reported`); `--write` for pip, npm,
  Docker `daemon.json` and Go `GOPROXY` with diffs, `--dry-run`, `--use eco=id` pins and
  automatic backups.
- `netdoctor restore` (`--list`, `--dry-run`).
- `netdoctor report --json/--md`.
- `netdoctor tui`: optional Textual live dashboard (`netdoctor-ir[tui]`).
- `netdoctor catalog list|validate`; `--catalog-dir` / `NETDOCTOR_CATALOG_DIR` overrides.
- YAML data catalogs in `netdoctor/data/`.
- Test suite with a scripted fake network (no real I/O), ruff, mypy (strict), a GitHub Actions
  CI workflow for Python 3.10–3.13 (staged in `.github/pending-workflows/` until enabled),
  GitHub Pages landing page.

[Unreleased]: https://github.com/mrzroot/netdoctor-ir/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mrzroot/netdoctor-ir/releases/tag/v0.1.0
