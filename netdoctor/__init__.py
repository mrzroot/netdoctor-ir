"""netdoctor-ir — connectivity doctor and mirror switcher for developers in Iran.

netdoctor measures; it never bypasses anything by itself. It tells you which developer
services are reachable from your network, why the broken ones are broken (DNS hijack,
TLS reset, sanction page, ...), which DNS resolvers and package mirrors work best *today*,
and can write pip / npm / Docker / Go configuration for the mirror you choose — with
automatic backups.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
