# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | ✅ |

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report privately through GitHub's
[private vulnerability reporting](https://github.com/mrzroot/netdoctor-ir/security/advisories/new).
You should get a reply within 7 days. Once a fix is released you'll be credited, unless you
prefer otherwise.

## Scope and threat model

netdoctor writes developer configuration files (`pip.conf`, `.npmrc`, `daemon.json`, Go env)
and prints shell commands. Things we consider security-relevant:

- Writing outside the documented config paths, or without a backup.
- Executing commands (netdoctor must never run DNS or system commands itself).
- Catalog entries that point users to malicious mirrors, or tampering with catalog validation.
- Leaking personal data (reports must not include the user's IP address).

### A note on mirrors

Any package mirror can see what you download and could, in theory, serve modified packages.
Prefer `official` and `documented` entries, pin versions, and verify hashes
(`pip install --require-hashes`, `npm ci` with lockfiles, Go's checksum database).
