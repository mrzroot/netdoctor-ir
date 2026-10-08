"""Rich renderers for terminal output (also used to produce the SVG screenshots)."""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from netdoctor.dnsbench import explain
from netdoctor.mirrors import best_per_ecosystem
from netdoctor.models import (
    MirrorResult,
    ResolverScore,
    ScanSummary,
    ServiceResult,
    Step,
    Verdict,
    Verification,
)
from netdoctor.osapply import Instruction

VERDICT_STYLE: dict[Verdict, tuple[str, str]] = {
    Verdict.OK: ("● OK", "bold green"),
    Verdict.SLOW: ("▲ SLOW", "bold yellow"),
    Verdict.SANCTIONED: ("⊘ SANCTIONED", "bold magenta"),
    Verdict.FILTERED: ("✖ FILTERED", "bold red"),
    Verdict.FORBIDDEN: ("⊘ FORBIDDEN", "bold dark_orange"),
    Verdict.DNS_ERROR: ("✖ DNS", "red"),
    Verdict.TCP_ERROR: ("✖ TCP", "red"),
    Verdict.TLS_ERROR: ("✖ TLS", "red"),
    Verdict.HTTP_ERROR: ("✖ HTTP", "red"),
    Verdict.TIMEOUT: ("◌ TIMEOUT", "red"),
}
LEVEL_STYLE = {"good": "green", "warn": "yellow", "bad": "red"}
TRUST_STYLE = {
    Verification.OFFICIAL: ("official", "green"),
    Verification.DOCUMENTED: ("documented", "cyan"),
    Verification.COMMUNITY: ("community", "dim"),
}


def verdict_text(v: Verdict) -> Text:
    """Coloured verdict badge."""
    label, style = VERDICT_STYLE[v]
    return Text(label, style=style)


def ms_text(ms: float | None, *, good: float = 150, ok: float = 600) -> Text:
    """Latency coloured by speed."""
    if ms is None:
        return Text("—", style="dim")
    style = "green" if ms < good else "yellow" if ms < ok else "red"
    return Text(f"{ms:.0f}", style=style)


def step_text(step: Step | None) -> Text:
    """Latency of a probe step, or the error kind if it failed."""
    if step is None:
        return Text("—", style="dim")
    if not step.ok:
        return Text(step.error or "fail", style="bold red")
    return ms_text(step.ms)


COMPACT_BELOW = 120
"""Terminal width under which tables drop secondary columns."""


def _table(title: str) -> Table:
    return Table(
        title=title,
        title_style="bold",
        header_style="bold cyan",
        border_style="grey37",
        expand=False,
        pad_edge=False,
    )


def scan_table(
    results: Sequence[ServiceResult],
    *,
    title: str = "Developer services",
    width: int | None = None,
) -> Table:
    """Table of scan results grouped by category (compact on narrow terminals)."""
    compact = width is not None and width < COMPACT_BELOW
    table = _table(title)
    if not compact:
        table.add_column("Area", style="bold magenta", no_wrap=True)
    table.add_column("Service", style="bold", no_wrap=True)
    if not compact:
        table.add_column("DNS", justify="right")
        table.add_column("TCP", justify="right")
        table.add_column("TLS", justify="right")
    table.add_column("HTTP", justify="right", no_wrap=True)
    table.add_column("ms", justify="right", no_wrap=True)
    table.add_column("Verdict", no_wrap=True)
    table.add_column("Why", style="grey70", overflow="fold", max_width=58, min_width=16)
    ordered = sorted(results, key=lambda r: r.service.category)
    last = None
    for r in ordered:
        area = r.service.category if r.service.category != last else ""
        if last is not None and r.service.category != last:
            table.add_section()
        last = r.service.category
        http = (
            Text(str(r.status), style="green" if r.verdict.healthy else "red")
            if r.status is not None
            else step_text(r.http)
        )
        lead: list[Text | str] = [r.service.name]
        steps: list[Text | str] = []
        if not compact:
            lead = [area, r.service.name]
            steps = [step_text(r.dns), step_text(r.tcp), step_text(r.tls)]
        table.add_row(
            *lead,
            *steps,
            http,
            ms_text(r.total_ms, good=400, ok=1200),
            verdict_text(r.verdict),
            r.reason,
        )
    return table


def summary_panel(summary: ScanSummary) -> Panel:
    """Overall verdict with counts and advice."""
    color = LEVEL_STYLE[summary.level]
    chips = Text()
    for v in Verdict:
        n = summary.counts.get(v.value, 0)
        if n:
            label, style = VERDICT_STYLE[v]
            chips.append(f" {label} ×{n} ", style=style)
            chips.append(" ")
    body: list[Text] = [Text(summary.headline, style=f"bold {color}"), chips]
    for tip in summary.advice:
        body.append(Text("→ " + tip, style="white"))
    return Panel(Group(*body), title="[bold]Verdict[/]", border_style=color, expand=False)


def dns_table(scores: Sequence[ResolverScore], *, width: int | None = None) -> Table:
    """Ranked resolver benchmark (compact on narrow terminals: notes move below)."""
    compact = width is not None and width < COMPACT_BELOW
    deep = any(s.unlocks is not None for s in scores)
    table = _table("DNS resolvers vs developer domains")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Resolver", style="bold", no_wrap=True)
    if not compact:
        table.add_column("Kind", style="dim", no_wrap=True)
    table.add_column("Address", no_wrap=True)
    table.add_column("Answered", justify="right", no_wrap=True)
    table.add_column("Median", justify="right", no_wrap=True)
    if not compact:
        table.add_column("p95", justify="right", no_wrap=True)
    if deep:
        table.add_column("Unblocks", justify="right", no_wrap=True)
    table.add_column("Score", justify="right", no_wrap=True)
    if not compact:
        table.add_column("Notes", style="grey70", overflow="fold", max_width=48)
    for i, s in enumerate(scores, 1):
        r = s.resolver
        name = Text(r.name)
        if r.name_fa and not compact:
            name.append(f"  {r.name_fa}", style="dim")
        answered = Text(
            f"{s.answered - s.hijacked}/{s.queries}",
            style="green" if s.success_rate > 0.95 else "yellow" if s.success_rate > 0.5 else "red",
        )
        score_style = "bold green" if s.score >= 80 else "yellow" if s.score >= 50 else "red"
        row: list[Text | str] = [str(i), name]
        if not compact:
            row.append(r.kind.value)
        row += [s.best_address or r.primary, answered, ms_text(s.median_ms, good=60, ok=200)]
        if not compact:
            row.append(ms_text(s.p95_ms, good=100, ok=400))
        if deep:
            row.append(f"{s.unlocks}/{s.unlock_total}" if s.unlocks is not None else "—")
        row.append(Text(f"{s.score:.0f}", style=score_style))
        if not compact:
            row.append(explain(s))
        table.add_row(*row)
    return table


def dns_footnotes(scores: Sequence[ResolverScore]) -> list[str]:
    """Condensed notes for compact mode (groups silent Iran-only resolvers)."""
    silent_ir = [s.resolver.name for s in scores if not s.answered and s.resolver.iran_only]
    notes = [
        f"{s.resolver.name}: {explain(s)}" for s in scores if s.answered or not s.resolver.iran_only
    ]
    if silent_ir:
        notes.append(
            f"No answer from {len(silent_ir)} Iran-only resolver(s) — expected outside Iran: "
            + ", ".join(silent_ir)
        )
    return notes


def instructions_panel(title: str, instructions: Sequence[Instruction]) -> Panel:
    """Copy-pasteable commands."""
    parts: list[Text] = []
    for ins in instructions:
        parts.append(Text(ins.title, style="bold"))
        for cmd in ins.commands:
            parts.append(Text("  $ " + cmd, style="cyan"))
        if ins.note:
            parts.append(Text("  " + ins.note, style="dim"))
        if ins.revert:
            parts.append(Text("  revert: " + " && ".join(ins.revert), style="dim"))
    return Panel(Group(*parts), title=title, border_style="cyan", expand=False)


def mirrors_table(results: Sequence[MirrorResult], *, width: int | None = None) -> Table:
    """Mirror health grouped by ecosystem; best per ecosystem starred."""
    compact = width is not None and width < COMPACT_BELOW
    best = {r.mirror.id for r in best_per_ecosystem(results).values()}
    table = _table("Package mirrors")
    table.add_column("Ecosystem", style="bold magenta", no_wrap=True)
    if not compact:
        table.add_column("Mirror", no_wrap=True)
    table.add_column("ID", style="dim" if not compact else "", no_wrap=True)
    table.add_column("ms", justify="right", no_wrap=True)
    table.add_column("Verdict", no_wrap=True)
    table.add_column("Trust", no_wrap=True)
    if not compact:
        table.add_column("Details", style="grey70", overflow="fold", max_width=46)
    last = None
    for r in results:
        eco = r.mirror.ecosystem
        if last is not None and eco != last:
            table.add_section()
        label, style = TRUST_STYLE[r.mirror.verification]
        star = r.mirror.id in best
        row: list[Text | str] = [eco if eco != last else ""]
        if compact:
            row.append(
                Text(("★ " if star else "  ") + r.mirror.id, style="bold green" if star else "")
            )
        else:
            row.append(
                Text(("★ " if star else "  ") + r.mirror.name, style="bold green" if star else "")
            )
            row.append(r.mirror.id)
        row += [ms_text(r.ms, good=300, ok=1000), verdict_text(r.verdict), Text(label, style=style)]
        if not compact:
            row.append(r.reason)
        table.add_row(*row)
        last = eco
    return table


def print_scan(
    console: Console,
    results: Sequence[ServiceResult],
    summary: ScanSummary,
    *,
    title: str = "Developer services",
) -> None:
    """Print the scan table and the verdict panel."""
    console.print(scan_table(results, title=title, width=console.width))
    console.print(summary_panel(summary))
