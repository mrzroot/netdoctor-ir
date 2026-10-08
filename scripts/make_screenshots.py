"""Regenerate the SVG screenshots in assets/ from *real* netdoctor runs.

Usage:  python scripts/make_screenshots.py [--width 150]

The output reflects the network of whoever runs it. The images committed to this
repository were produced on a build machine outside Iran (see README).
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from rich.console import Console
from rich.terminal_theme import MONOKAI

from netdoctor.catalog import load_catalog
from netdoctor.dnsbench import DEFAULT_HOSTS, benchmark, reference_answers
from netdoctor.mirrors import check_mirrors
from netdoctor.net import Network
from netdoctor.osapply import dns_instructions
from netdoctor.render import dns_table, instructions_panel, mirrors_table, print_scan
from netdoctor.scanner import scan, summarize

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def _console(width: int) -> Console:
    os.environ.setdefault("TERM", "xterm-256color")
    return Console(record=True, width=width, force_terminal=True, color_system="truecolor")


def _prompt(console: Console, cmd: str) -> None:
    console.print(f"[bold green]❯[/] [bold]{cmd}[/]")


async def main(width: int) -> None:
    cat = load_catalog()
    ASSETS.mkdir(exist_ok=True)

    console = _console(width)
    _prompt(console, "netdoctor scan")
    async with Network(timeout=6) as net:
        results = await scan(cat.services, net, cat)
    print_scan(console, results, summarize(results))
    console.save_svg(str(ASSETS / "scan.svg"), title="netdoctor scan", theme=MONOKAI)

    hero_cats = ("python", "javascript", "containers", "go")
    hero = [r for r in results if r.service.category in hero_cats]
    console = _console(width - 22)
    _prompt(console, "netdoctor scan -k python -k javascript -k containers -k go")
    print_scan(console, hero, summarize(hero))
    console.save_svg(str(ASSETS / "hero.svg"), title="netdoctor scan", theme=MONOKAI)

    console = _console(width)
    _prompt(console, "netdoctor dns --deep")
    deep = [s for s in cat.services if s.sanction_prone]
    async with Network(timeout=3) as net:
        ref = await reference_answers(DEFAULT_HOSTS, net, "1.1.1.1")
        scores = await benchmark(
            cat.resolvers, DEFAULT_HOSTS, net, cat, reference=ref, deep_services=deep
        )
    console.print(dns_table(scores, width=width))
    best = scores[0].resolver
    console.print(
        instructions_panel(
            f"netdoctor dns --apply → commands for linux (printed, never executed): {best.name}",
            dns_instructions(best, "linux", "wlan0"),
        )
    )
    console.save_svg(str(ASSETS / "dns.svg"), title="netdoctor dns --deep", theme=MONOKAI)

    console = _console(width)
    _prompt(console, "netdoctor mirrors")
    async with Network(timeout=8) as net:
        mres = await check_mirrors(cat.mirrors, net, cat)
    console.print(mirrors_table(mres, width=width))
    console.save_svg(str(ASSETS / "mirrors.svg"), title="netdoctor mirrors", theme=MONOKAI)
    print("wrote", *sorted(p.name for p in ASSETS.glob("*.svg")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=150)
    asyncio.run(main(parser.parse_args().width))
