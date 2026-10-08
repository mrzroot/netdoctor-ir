"""Optional live dashboard built with Textual (``pip install 'netdoctor-ir[tui]'``)."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header, Static

from netdoctor.models import Catalog, ScanSummary, ServiceResult, Verdict
from netdoctor.net import Network
from netdoctor.render import VERDICT_STYLE
from netdoctor.scanner import scan, summarize


class NetDoctorApp(App[None]):
    """Live, auto-refreshing table of developer-service health."""

    TITLE = "netdoctor"
    SUB_TITLE = "connectivity doctor for developers in Iran"
    CSS = """
    #stats { height: 3; padding: 0 1; }
    .stat { width: 1fr; content-align: center middle; border: round $primary; }
    DataTable { height: 1fr; }
    """
    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("r", "rescan", "Rescan"),
        Binding("a", "toggle_auto", "Auto-refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, catalog: Catalog, timeout: float = 6.0, interval: float = 60.0) -> None:
        super().__init__()
        self.catalog = catalog
        self.timeout = timeout
        self.interval = interval
        self.auto = True
        self._scanning = False
        self.last_summary: ScanSummary | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="stats"):
            yield Static("healthy —", id="healthy", classes="stat")
            yield Static("sanctioned —", id="sanctioned", classes="stat")
            yield Static("filtered —", id="filtered", classes="stat")
            yield Static("other —", id="other", classes="stat")
        yield DataTable(id="table", zebra_stripes=True, cursor_type="row")
        yield Static("", id="headline")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Service", "Category", "Host", "ms", "Verdict", "Why")
        for s in self.catalog.services:
            table.add_row(
                s.name, s.category, s.host, "…", Text("pending", style="dim"), "", key=s.id
            )
        self.set_interval(self.interval, self._auto_tick)
        self.action_rescan()

    def _auto_tick(self) -> None:
        if self.auto:
            self.action_rescan()

    def action_toggle_auto(self) -> None:
        self.auto = not self.auto
        self.notify(f"Auto-refresh {'on' if self.auto else 'off'}")

    def action_rescan(self) -> None:
        if not self._scanning:
            self.run_worker(self._scan(), exclusive=True)

    def _update_row(self, res: ServiceResult) -> None:
        table = self.query_one(DataTable)
        label, style = VERDICT_STYLE[res.verdict]
        ms = f"{res.total_ms:.0f}" if res.total_ms else "—"
        table.update_cell(res.service.id, table.ordered_columns[3].key, ms)
        table.update_cell(res.service.id, table.ordered_columns[4].key, Text(label, style=style))
        table.update_cell(res.service.id, table.ordered_columns[5].key, res.reason)

    async def _scan(self) -> None:
        self._scanning = True
        self.sub_title = "scanning…"
        try:
            async with Network(timeout=self.timeout) as net:
                results = await scan(
                    self.catalog.services, net, self.catalog, on_result=self._update_row
                )
            summary = summarize(results)
            self.last_summary = summary
            c = summary.counts
            healthy = c.get(Verdict.OK.value, 0) + c.get(Verdict.SLOW.value, 0)
            sanctioned = c.get(Verdict.SANCTIONED.value, 0) + c.get(Verdict.FORBIDDEN.value, 0)
            filtered = c.get(Verdict.FILTERED.value, 0)
            self.query_one("#healthy", Static).update(f"[green]healthy {healthy}[/]")
            self.query_one("#sanctioned", Static).update(f"[magenta]sanctioned {sanctioned}[/]")
            self.query_one("#filtered", Static).update(f"[red]filtered {filtered}[/]")
            self.query_one("#other", Static).update(
                f"other {summary.total - healthy - sanctioned - filtered}"
            )
            self.query_one("#headline", Static).update(summary.headline)
        finally:
            self._scanning = False
            self.sub_title = "r: rescan · a: auto-refresh · q: quit"


def run_tui(catalog: Catalog, timeout: float = 6.0) -> None:
    """Start the dashboard (blocking)."""
    asyncio.get_event_loop_policy()  # ensure loop policy is initialised on Windows
    NetDoctorApp(catalog, timeout=timeout).run()
