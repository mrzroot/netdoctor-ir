"""Command-line interface: ``netdoctor scan | dns | mirrors | restore | report | tui``."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.syntax import Syntax

from netdoctor import __version__
from netdoctor.backup import BackupError, BackupManager
from netdoctor.catalog import CatalogError, load_catalog, select
from netdoctor.configs import ECOSYSTEM_TOOL, ConfigChange, apply_changes, plan
from netdoctor.dnsbench import DEFAULT_HOSTS, benchmark, reference_answers
from netdoctor.mirrors import best_per_ecosystem, check_mirrors
from netdoctor.models import Catalog, Resolver, Verification
from netdoctor.net import Network
from netdoctor.osapply import current_os, dns_instructions, render_script
from netdoctor.render import (
    COMPACT_BELOW,
    dns_footnotes,
    dns_table,
    instructions_panel,
    mirrors_table,
    print_scan,
)
from netdoctor.report import build_report, to_markdown
from netdoctor.scanner import DEFAULT_SLOW_MS, scan, summarize

app = typer.Typer(
    name="netdoctor",
    help="Connectivity doctor & mirror switcher for developers in Iran. "
    "It measures and configures — it never bypasses anything by itself.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=True,
    pretty_exceptions_show_locals=False,
)
catalog_app = typer.Typer(help="Inspect and validate the data catalogs.", no_args_is_help=True)
app.add_typer(catalog_app, name="catalog")

console = Console()
err = Console(stderr=True)


def make_network(timeout: float, nameservers: Sequence[str] | None = None) -> Network:
    """Factory for the network layer (patched in tests)."""
    return Network(timeout=timeout, nameservers=nameservers)


def _state(ctx: typer.Context) -> dict[str, Any]:
    ctx.ensure_object(dict)
    obj: dict[str, Any] = ctx.obj
    return obj


def _catalog(ctx: typer.Context) -> Catalog:
    state = _state(ctx)
    if "catalog" not in state:
        try:
            state["catalog"] = load_catalog(state.get("catalog_dir"))
        except CatalogError as exc:
            err.print(f"[red]Catalog error:[/] {escape(str(exc))}")
            raise typer.Exit(2) from exc
    cat: Catalog = state["catalog"]
    return cat


def _split(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or []:
        out += [x.strip() for x in v.split(",") if x.strip()]
    return out


def _fail(msg: str, code: int = 2) -> typer.Exit:
    err.print(f"[red]Error:[/] {escape(msg)}")
    return typer.Exit(code)


def _resolve_resolver_arg(value: str | None, catalog: Catalog) -> tuple[str | None, str]:
    """Accept a catalog resolver id or a raw IP. Returns (ip, label)."""
    if not value:
        return None, "system"
    for r in catalog.resolvers:
        if r.id == value:
            return r.primary, f"{r.name} ({r.primary})"
    try:
        ipaddress.ip_address(value)
    except ValueError as exc:
        raise _fail(f"--resolver must be an IP address or a resolver id, got '{value}'") from exc
    return value, value


def _version_cb(value: bool) -> None:
    if value:
        console.print(f"netdoctor-ir {__version__}", highlight=False)
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    catalog_dir: Annotated[
        Path | None,
        typer.Option(
            "--catalog-dir",
            envvar="NETDOCTOR_CATALOG_DIR",
            help="Directory with catalog YAML files overriding the bundled ones.",
        ),
    ] = None,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable colours.")] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_cb, is_eager=True, help="Show version and exit."
        ),
    ] = False,
) -> None:
    """netdoctor — diagnose developer connectivity from Iran."""
    _state(ctx)["catalog_dir"] = catalog_dir
    if no_color:
        console.no_color = True
        err.no_color = True


# --------------------------------------------------------------------------- scan

Timeout = Annotated[float, typer.Option("--timeout", "-t", min=0.5, help="Per-step timeout (s).")]
Concurrency = Annotated[
    int, typer.Option("--concurrency", "-c", min=1, max=256, help="Parallel probes.")
]
JsonOut = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")]


@app.command("scan")
def scan_cmd(
    ctx: typer.Context,
    only: Annotated[
        list[str] | None,
        typer.Option("--only", "-o", help="Service ids (comma-separated or repeated)."),
    ] = None,
    category: Annotated[
        list[str] | None,
        typer.Option(
            "--category", "-k", help="Only these categories (python, containers, go, ...)."
        ),
    ] = None,
    resolver: Annotated[
        str | None,
        typer.Option(
            "--resolver", "-r", help="Resolve through this DNS (IP or resolver id, e.g. shecan)."
        ),
    ] = None,
    timeout: Timeout = 6.0,
    concurrency: Concurrency = 16,
    slow_ms: Annotated[
        float, typer.Option(help="Total latency above which a service counts as slow (ms).")
    ] = DEFAULT_SLOW_MS,
    as_json: JsonOut = False,
    strict: Annotated[
        bool, typer.Option("--strict", help="Exit 1 if any service is not healthy (for CI).")
    ] = False,
) -> None:
    """Check DNS, TCP, TLS and HTTP for developer services and explain failures."""
    cat = _catalog(ctx)
    try:
        services = select(cat.services, _split(only))
        cats = _split(category)
        if cats:
            services = [s for s in services if s.category in cats]
    except CatalogError as exc:
        raise _fail(str(exc)) from exc
    if not services:
        raise _fail("no services selected")
    ns, label = _resolve_resolver_arg(resolver, cat)

    async def run() -> Any:
        async with make_network(timeout) as net:
            if as_json:
                return await scan(
                    services, net, cat, concurrency=concurrency, slow_ms=slow_ms, nameserver=ns
                )
            done = 0
            with console.status(f"Probing {len(services)} services via {label} DNS…") as st:

                def tick(_: Any) -> None:
                    nonlocal done
                    done += 1
                    st.update(f"Probing services via {label} DNS… {done}/{len(services)}")

                return await scan(
                    services,
                    net,
                    cat,
                    concurrency=concurrency,
                    slow_ms=slow_ms,
                    on_result=tick,
                    nameserver=ns,
                )

    results = asyncio.run(run())
    summary = summarize(results)
    if as_json:
        print(json.dumps(build_report(scan=results, summary=summary, resolver=label), indent=2))
    else:
        print_scan(console, results, summary, title=f"Developer services · DNS: {label}")
    if strict and summary.level != "good":
        raise typer.Exit(1)


# --------------------------------------------------------------------------- dns


@app.command("dns")
def dns_cmd(
    ctx: typer.Context,
    only: Annotated[
        list[str] | None, typer.Option("--only", "-o", help="Resolver ids to test.")
    ] = None,
    kind: Annotated[str | None, typer.Option("--kind", help="public | anti-sanction | isp")] = None,
    domains: Annotated[
        list[str] | None,
        typer.Option("--domain", "-d", help="Domains to query (default: core developer domains)."),
    ] = None,
    all_domains: Annotated[
        bool, typer.Option("--all-domains", help="Query every host in the services catalog.")
    ] = False,
    deep: Annotated[
        bool,
        typer.Option(
            "--deep",
            help="Also fetch sanction-prone services through each resolver's answers "
            "to see which resolver actually unblocks them.",
        ),
    ] = False,
    reference: Annotated[
        str, typer.Option(help="Trusted resolver used to spot rewritten answers.")
    ] = "1.1.1.1",
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Print the commands to switch your OS to the best resolver "
            "(netdoctor never runs them).",
        ),
    ] = False,
    use: Annotated[
        str | None,
        typer.Option("--use", help="With --apply: resolver id to apply instead of the top-ranked."),
    ] = None,
    os_name: Annotated[
        str | None, typer.Option("--os", help="linux | macos | windows (default: this machine).")
    ] = None,
    interface: Annotated[
        str | None,
        typer.Option("--interface", "-i", help="Network interface/service name for the commands."),
    ] = None,
    script: Annotated[
        Path | None,
        typer.Option("--script", help="With --apply: also save the commands to this file."),
    ] = None,
    timeout: Timeout = 3.0,
    concurrency: Concurrency = 48,
    as_json: JsonOut = False,
) -> None:
    """Benchmark public and Iranian anti-sanction DNS resolvers on developer domains."""
    cat = _catalog(ctx)
    try:
        resolvers: list[Resolver] = select(cat.resolvers, _split(only))
    except CatalogError as exc:
        raise _fail(str(exc)) from exc
    if kind:
        resolvers = [r for r in resolvers if r.kind.value == kind]
    if not resolvers:
        raise _fail("no resolvers selected")
    hosts = _split(domains) or (
        list(dict.fromkeys(s.host for s in cat.services)) if all_domains else list(DEFAULT_HOSTS)
    )
    deep_services = [s for s in cat.services if s.sanction_prone] if deep else None

    async def run() -> Any:
        async with make_network(timeout) as net:
            ref = await reference_answers(hosts, net, reference)
            if as_json:
                return await benchmark(
                    resolvers,
                    hosts,
                    net,
                    cat,
                    concurrency=concurrency,
                    reference=ref,
                    deep_services=deep_services,
                )
            with console.status(
                f"Querying {len(hosts)} domains × {len(resolvers)} resolvers"
                + (" + deep HTTP checks" if deep else "")
                + "…"
            ):
                return await benchmark(
                    resolvers,
                    hosts,
                    net,
                    cat,
                    concurrency=concurrency,
                    reference=ref,
                    deep_services=deep_services,
                )

    scores = asyncio.run(run())
    if as_json:
        print(json.dumps(build_report(dns=scores)["dns"], indent=2))
        return
    console.print(dns_table(scores, width=console.width))
    if console.width < COMPACT_BELOW:
        for note in dns_footnotes(scores):
            console.print(f"[dim]• {note}[/]")
    console.print(
        f"[dim]{len(hosts)} domains per address · reference resolver {reference} · "
        "anti-sanction resolvers marked iran_only answer only inside Iran.[/]"
    )
    chosen: Resolver | None = None
    if use:
        chosen = next((r for r in cat.resolvers if r.id == use), None)
        if chosen is None:
            raise _fail(f"unknown resolver id '{use}'")
    elif scores and scores[0].answered:
        chosen = scores[0].resolver
    if chosen is None:
        console.print("[yellow]No resolver answered — check your connection.[/]")
        return
    target_os = os_name or current_os()
    instructions = dns_instructions(chosen, target_os, interface)
    if not apply:
        console.print(
            f"\n[bold green]Best right now:[/] {chosen.name} "
            f"({', '.join(chosen.addresses[:2])}). "
            f"Run [cyan]netdoctor dns --apply[/] to get the commands for {target_os}."
        )
        return
    console.print(
        instructions_panel(
            f"Switch DNS to {chosen.name} on {target_os} — review, then run yourself", instructions
        )
    )
    console.print(
        "[dim]netdoctor never changes system settings; most commands need admin rights.[/]"
    )
    if script:
        script.write_text(render_script(chosen, instructions, target_os), encoding="utf-8")
        console.print(f"Saved to [bold]{script}[/] (not executed).")


# --------------------------------------------------------------------------- mirrors


@app.command("mirrors")
def mirrors_cmd(
    ctx: typer.Context,
    ecosystem: Annotated[
        list[str] | None,
        typer.Option("--ecosystem", "-e", help="pypi, npm, docker, go, maven (default: all)."),
    ] = None,
    only: Annotated[
        list[str] | None, typer.Option("--only", "-o", help="Mirror ids to test.")
    ] = None,
    write: Annotated[
        bool,
        typer.Option(
            "--write",
            help="Write pip/npm/Docker/Go config for the best mirrors (with automatic backup).",
        ),
    ] = False,
    use: Annotated[
        list[str] | None,
        typer.Option("--use", help="Pin a mirror per ecosystem, e.g. --use pypi=pypi-runflare."),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="With --write: show the diff only.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    docker_config: Annotated[
        Path | None,
        typer.Option(
            help="daemon.json to edit (default: Docker Desktop's, or a staged copy on Linux)."
        ),
    ] = None,
    timeout: Timeout = 8.0,
    concurrency: Concurrency = 16,
    as_json: JsonOut = False,
) -> None:
    """Test package mirrors and optionally switch your tools to the best ones."""
    cat = _catalog(ctx)
    ecos = _split(ecosystem)
    unknown = [e for e in ecos if e not in cat.ecosystems]
    if unknown:
        raise _fail(f"unknown ecosystem(s): {', '.join(unknown)}")
    try:
        mirrors = select(cat.mirrors, _split(only))
    except CatalogError as exc:
        raise _fail(str(exc)) from exc
    if ecos:
        mirrors = [m for m in mirrors if m.ecosystem in ecos]
    pins: dict[str, str] = {}
    for item in _split(use):
        eco, _, mid = item.partition("=")
        if not mid:
            raise _fail(f"--use expects ecosystem=mirror-id, got '{item}'")
        if mid not in {m.id for m in cat.mirrors if m.ecosystem == eco}:
            raise _fail(f"'{mid}' is not a {eco} mirror in the catalog")
        pins[eco] = mid
        if not any(m.id == mid for m in mirrors):
            mirrors.append(next(m for m in cat.mirrors if m.id == mid))
    if not mirrors:
        raise _fail("no mirrors selected")

    async def run() -> Any:
        async with make_network(timeout) as net:
            if as_json:
                return await check_mirrors(mirrors, net, cat, concurrency=concurrency)
            with console.status(f"Testing {len(mirrors)} mirrors…"):
                return await check_mirrors(mirrors, net, cat, concurrency=concurrency)

    results = asyncio.run(run())
    if as_json:
        print(json.dumps(build_report(mirrors=results)["mirrors"], indent=2))
        return
    console.print(mirrors_table(results, width=console.width))
    console.print(
        "[dim]★ = fastest healthy mirror per ecosystem · trust: official / documented "
        "/ community-reported (unverified; please help confirm).[/]"
    )
    if not write:
        console.print(
            "Switch tools with [cyan]netdoctor mirrors --write[/] "
            "(backs up first; undo with [cyan]netdoctor restore[/])."
        )
        return
    _write_configs(results, pins, cat, dry_run=dry_run, yes=yes, docker_config=docker_config)


def _write_configs(
    results: Sequence[Any],
    pins: dict[str, str],
    cat: Catalog,
    *,
    dry_run: bool,
    yes: bool,
    docker_config: Path | None,
) -> None:
    best = best_per_ecosystem(results)
    by_id = {r.mirror.id: r for r in results}
    changes: list[ConfigChange] = []
    for eco, tool in ECOSYSTEM_TOOL.items():
        if eco in pins:
            picked = by_id[pins[eco]]
            if not picked.verdict.healthy:
                console.print(
                    f"[yellow]Note:[/] pinned {picked.mirror.id} is "
                    f"{picked.verdict.value}; writing it anyway as requested."
                )
        elif eco in best:
            picked = best[eco]
            if picked.mirror.verification is Verification.OFFICIAL:
                console.print(
                    f"[green]{eco}:[/] upstream is the fastest healthy option — nothing to change."
                )
                continue
        else:
            continue
        path = docker_config if tool == "docker" else None
        try:
            changes.append(plan(tool, picked.mirror.url, path))
        except ValueError as exc:
            console.print(f"[red]{tool}:[/] {escape(str(exc))}")
    changes = [c for c in changes if c.changed]
    if not changes:
        console.print("Nothing to write.")
        return
    for c in changes:
        console.rule(f"[bold]{c.tool}[/] → {c.path}")
        console.print(
            Syntax(
                c.diff() or "(no textual change)",
                "diff",
                theme="ansi_dark",
                background_color="default",
            )
        )
        if c.note:
            console.print(f"[dim]{escape(c.note)}[/]")
    if dry_run:
        console.print("[yellow]Dry run — nothing written.[/]")
        return
    if not yes and not typer.confirm(f"Write {len(changes)} file(s)?", default=True):
        console.print("Aborted.")
        return
    bset = apply_changes(changes, label="mirrors --write")
    if bset:
        console.print(
            f"[green]Done.[/] Backup [bold]{bset.id}[/] saved — undo any time with "
            f"[cyan]netdoctor restore[/]."
        )


# --------------------------------------------------------------------------- restore


@app.command("restore")
def restore_cmd(
    backup_id: Annotated[str | None, typer.Argument(help="Backup id (default: latest).")] = None,
    list_: Annotated[bool, typer.Option("--list", "-l", help="List backups.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would happen.")] = False,
) -> None:
    """Undo config files written by `mirrors --write`."""
    mgr = BackupManager()
    if list_:
        sets = mgr.sets()
        if not sets:
            console.print("No backups yet.")
            return
        for s in sets:
            state = "[dim]restored[/]" if s.restored else "[green]active[/]"
            console.print(f"[bold]{s.id}[/]  {s.created}  {s.label}  {state}")
            for e in s.entries:
                console.print(f"    {'•' if e.existed else '+'} {e.path}")
        return
    try:
        actions = mgr.restore(backup_id, dry_run=dry_run)
    except BackupError as exc:
        raise _fail(str(exc), 1) from exc
    for a in actions:
        console.print(("would " if dry_run else "") + a)
    if not dry_run:
        console.print("[green]Restored.[/]")


# --------------------------------------------------------------------------- report


@app.command("report")
def report_cmd(
    ctx: typer.Context,
    json_path: Annotated[
        Path | None, typer.Option("--json", help="Write JSON report here ('-' for stdout).")
    ] = None,
    md_path: Annotated[
        Path | None, typer.Option("--md", help="Write Markdown report here ('-' for stdout).")
    ] = None,
    skip_dns: Annotated[bool, typer.Option("--skip-dns")] = False,
    skip_mirrors: Annotated[bool, typer.Option("--skip-mirrors")] = False,
    resolver: Annotated[str | None, typer.Option("--resolver", "-r")] = None,
    timeout: Timeout = 6.0,
) -> None:
    """Run scan + dns + mirrors and write a shareable JSON/Markdown report."""
    if json_path is None and md_path is None:
        md_path = Path("netdoctor-report.md")
    cat = _catalog(ctx)
    ns, label = _resolve_resolver_arg(resolver, cat)

    async def run() -> dict[str, Any]:
        async with make_network(timeout) as net:
            results = await scan(cat.services, net, cat, nameserver=ns)
        out: dict[str, Any] = {"scan": results, "summary": summarize(results), "resolver": label}
        async with make_network(min(timeout, 3.0)) as net:
            if not skip_dns:
                ref = await reference_answers(DEFAULT_HOSTS, net, "1.1.1.1")
                out["dns"] = await benchmark(cat.resolvers, DEFAULT_HOSTS, net, cat, reference=ref)
        if not skip_mirrors:
            async with make_network(timeout) as net:
                out["mirrors"] = await check_mirrors(cat.mirrors, net, cat)
        return out

    with console.status("Collecting scan, DNS and mirror results…"):
        data = asyncio.run(run())
    report = build_report(**data)
    for path, text in (
        (json_path, json.dumps(report, indent=2) + "\n"),
        (md_path, to_markdown(report)),
    ):
        if path is None:
            continue
        if str(path) == "-":
            sys.stdout.write(text)
        else:
            path.write_text(text, encoding="utf-8")
            console.print(f"Wrote [bold]{path}[/]")


# --------------------------------------------------------------------------- catalog


@catalog_app.command("validate")
def catalog_validate(ctx: typer.Context) -> None:
    """Validate catalog YAML files (used in CI for contributor PRs)."""
    cat = _catalog(ctx)
    console.print(
        f"[green]✓ catalog OK[/] — {len(cat.services)} services, {len(cat.resolvers)} "
        f"resolvers, {len(cat.mirrors)} mirrors, {len(cat.signatures)} signatures"
    )


@catalog_app.command("list")
def catalog_list(
    ctx: typer.Context,
    kind: Annotated[str, typer.Argument(help="services | resolvers | mirrors")] = "mirrors",
) -> None:
    """List catalog entries."""
    from rich.table import Table

    cat = _catalog(ctx)
    table = Table(header_style="bold cyan", border_style="grey37")
    if kind == "services":
        for col in ("id", "name", "category", "host", "sanction-prone"):
            table.add_column(col)
        for s in cat.services:
            table.add_row(s.id, s.name, s.category, s.host, "yes" if s.sanction_prone else "")
    elif kind == "resolvers":
        for col in ("id", "name", "kind", "addresses", "trust"):
            table.add_column(col)
        for r in cat.resolvers:
            table.add_row(
                r.id,
                f"{r.name} {r.name_fa}".strip(),
                r.kind.value,
                ", ".join(r.addresses),
                r.verification.value,
            )
    elif kind == "mirrors":
        for col in ("id", "ecosystem", "provider", "url", "trust"):
            table.add_column(col)
        for m in cat.mirrors:
            table.add_row(m.id, m.ecosystem, m.provider, m.url, m.verification.value)
    else:
        raise _fail("kind must be services, resolvers or mirrors")
    console.print(table)


# --------------------------------------------------------------------------- misc


@app.command("tui")
def tui_cmd(ctx: typer.Context, timeout: Timeout = 6.0) -> None:
    """Live dashboard (needs the optional extra: pipx install 'netdoctor-ir[tui]')."""
    try:
        from netdoctor.tui import run_tui
    except ImportError as exc:
        raise _fail("the TUI needs Textual: pip install 'netdoctor-ir[tui]'") from exc
    run_tui(_catalog(ctx), timeout=timeout)  # pragma: no cover


@app.command("version")
def version_cmd() -> None:
    """Show the installed version."""
    console.print(f"netdoctor-ir {__version__}", highlight=False)


def main() -> None:
    """Console-script entry point."""
    app()
