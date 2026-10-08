"""Smoke-test the optional Textual dashboard headlessly with the fake network."""

import pytest

pytest.importorskip("textual")

from netdoctor import tui
from netdoctor.net import HttpReply
from tests.conftest import FakeNetwork


async def test_dashboard_scans_and_updates(monkeypatch, catalog):
    fake = FakeNetwork()
    fake.http["https://registry-1.docker.io/v2/"] = HttpReply(
        403, 5, {}, "Since Docker is a US company, we must comply with US export control"
    )
    monkeypatch.setattr(tui, "Network", lambda timeout: fake)
    app = tui.NetDoctorApp(catalog, timeout=1, interval=3600)
    async with app.run_test(size=(160, 50)) as pilot:
        for _ in range(50):
            await pilot.pause(0.05)
            if app.last_summary is not None:
                break
        table = app.query_one(tui.DataTable)
        assert table.row_count == len(catalog.services)
        assert app.last_summary is not None
        assert "services reachable" in app.last_summary.headline
        assert app.last_summary.counts.get("sanctioned") == 1
        await pilot.press("a")
        assert app.auto is False
        await pilot.press("r")
        await app.workers.wait_for_complete()
