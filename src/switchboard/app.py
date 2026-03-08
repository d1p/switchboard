"""Switchboard — Main Textual Application."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Footer, Input, Label, Static, DataTable, Select
from textual.containers import Container, Horizontal
from textual import work, on

from .services import (
    ServiceInfo,
    list_all_services,
    batch_get_resources,
    enrich_service,
    start_service,
    stop_service,
    restart_service,
    enable_service,
    disable_service,
    get_journal_logs,
    get_service_properties,
)
from .widgets import ServiceTable, DetailPane

CSS_PATH = Path(__file__).parent / "styles" / "app.tcss"


class SwitchboardApp(App):
    """A rich TUI for managing systemd services."""

    CSS_PATH = CSS_PATH
    TITLE = "Switchboard"
    SUB_TITLE = "systemd service manager"

    BINDINGS = [
        Binding("s", "service_start", "Start", show=True),
        Binding("x", "service_stop", "Stop", show=True),
        Binding("r", "service_restart", "Restart", show=True),
        Binding("e", "service_enable", "Enable", show=True),
        Binding("d", "service_disable", "Disable", show=True),
        Binding("/", "focus_search", "Search", show=True),
        Binding("escape", "clear_search", "Clear", show=False),
        Binding("f5", "force_refresh", "Refresh", show=True),
        Binding("ctrl+r", "force_refresh", "Refresh", show=False),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._services: dict[str, ServiceInfo] = {}  # unit → ServiceInfo
        self._last_refresh: float = 0.0
        self._loading: bool = True

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    # Status filter options shown in the Select dropdown
    STATUS_OPTIONS: list[tuple[str, str]] = [
        ("All statuses", ""),
        ("● Running", "active"),
        ("● Activating", "activating"),
        ("● Inactive", "inactive"),
        ("● Failed", "failed"),
        ("● Reloading", "reloading"),
        ("● Deactivating", "deactivating"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="search-container"):
            yield Label(" search:", id="search-label")
            yield Input(placeholder="filter services…", id="search")
            yield Label(" status:", id="status-label")
            yield Select(
                self.STATUS_OPTIONS,
                value="",
                allow_blank=False,
                id="status-filter",
            )
        yield ServiceTable(id="service-table")
        with Horizontal(id="status-bar"):
            yield Static("Loading services…", id="status-text")
            yield Static("", id="refresh-indicator")
        yield DetailPane(id="detail-pane")
        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        table = self.query_one("#service-table", ServiceTable)
        table.build_columns()
        self.load_services()
        self.set_interval(3.0, self._periodic_refresh)

    # ------------------------------------------------------------------
    # Data loading workers
    # ------------------------------------------------------------------

    @work(exclusive=False, thread=False)
    async def load_services(self) -> None:
        """Initial full load: fetch service list + all resources."""
        self._loading = True
        self._set_status("Loading services…")

        services = await list_all_services()

        # Populate basic list immediately for fast first paint
        for svc in services:
            self._services[svc.unit] = svc

        table = self.query_one("#service-table", ServiceTable)
        table.populate(list(self._services.values()))
        self._set_status(f"Fetching resources for {len(services)} services…")

        # Now enrich with resource data
        await self._refresh_resources()
        table.update_rows(list(self._services.values()))

        self._loading = False
        self._set_status(f"{len(self._services)} services loaded.")
        self._set_refresh_indicator("")

    @work(exclusive=True, thread=False)
    async def _periodic_refresh(self) -> None:
        if self._loading:
            return
        await self._do_refresh()

    @work(exclusive=False, thread=False)
    async def action_force_refresh(self) -> None:
        self._set_status("Refreshing…")
        await self._do_refresh(full=True)

    async def _do_refresh(self, full: bool = False) -> None:
        self._set_refresh_indicator("⟳")
        t0 = time.monotonic()

        if full:
            services = await list_all_services()
            # Merge: keep resource data for existing, add new, remove gone
            new_units = {s.unit for s in services}
            old_units = set(self._services.keys())
            # Remove disappeared units
            for gone in old_units - new_units:
                del self._services[gone]
            # Add new units
            for svc in services:
                if svc.unit not in self._services:
                    self._services[svc.unit] = svc
                else:
                    # Preserve resource data, update meta
                    existing = self._services[svc.unit]
                    existing.load_state = svc.load_state
                    existing.active_state = svc.active_state
                    existing.sub_state = svc.sub_state

        await self._refresh_resources()
        elapsed = time.monotonic() - t0

        table = self.query_one("#service-table", ServiceTable)
        search_input = self.query_one("#search", Input)
        table.apply_filter(
            search_input.value,
            list(self._services.values()),
            status_filter=self._current_status_filter(),
        )

        n = len(self._services)
        self._set_status(f"{n} services  •  refreshed in {elapsed:.1f}s")
        self._set_refresh_indicator("")

    async def _refresh_resources(self) -> None:
        units = list(self._services.keys())
        t0 = time.monotonic()
        props_map = await batch_get_resources(units)
        elapsed = time.monotonic() - t0

        for unit, props in props_map.items():
            if unit in self._services:
                enrich_service(self._services[unit], props, elapsed)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#status-text", Static).update(msg)
        except Exception:
            pass

    def _set_refresh_indicator(self, text: str) -> None:
        try:
            self.query_one("#refresh-indicator", Static).update(text)
        except Exception:
            pass

    def _selected_unit(self) -> Optional[str]:
        table = self.query_one("#service-table", ServiceTable)
        return table.selected_unit()

    def _current_status_filter(self) -> str:
        try:
            v = self.query_one("#status-filter", Select).value
            return "" if v is Select.BLANK else str(v)
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Detail pane update
    # ------------------------------------------------------------------

    @work(exclusive=True, thread=False)
    async def _update_detail(self, unit: str) -> None:
        """Fetch properties + logs for selected service and display them."""
        pane = self.query_one("#detail-pane", DetailPane)
        svc = self._services.get(unit)
        if not svc:
            pane.clear_detail()
            return

        props, logs = await _gather_detail(unit)
        enrich_service(svc, props, 0)
        pane.show_details(svc, props)
        pane.show_logs(logs)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @on(DataTable.RowHighlighted, "#service-table")
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        unit = str(event.row_key.value) if event.row_key else None
        if unit:
            self._update_detail(unit)

    @on(Input.Changed, "#search")
    def on_search_changed(self, event: Input.Changed) -> None:
        table = self.query_one("#service-table", ServiceTable)
        table.apply_filter(
            event.value,
            list(self._services.values()),
            status_filter=self._current_status_filter(),
        )
        n = table.row_count
        self._set_status(f"Showing {n} of {len(self._services)} services")

    @on(Select.Changed, "#status-filter")
    def on_status_filter_changed(self, event: Select.Changed) -> None:
        status = "" if event.value is Select.BLANK else str(event.value)
        table = self.query_one("#service-table", ServiceTable)
        search_input = self.query_one("#search", Input)
        table.apply_filter(
            search_input.value,
            list(self._services.values()),
            status_filter=status,
        )
        n = table.row_count
        self._set_status(f"Showing {n} of {len(self._services)} services")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_clear_search(self) -> None:
        inp = self.query_one("#search", Input)
        sel = self.query_one("#status-filter", Select)
        if inp.value or sel.value != "":
            inp.clear()
            sel.value = ""
        else:
            self.query_one("#service-table", ServiceTable).focus()

    @work(exclusive=False, thread=False)
    async def action_service_start(self) -> None:
        await self._control_action("start")

    @work(exclusive=False, thread=False)
    async def action_service_stop(self) -> None:
        await self._control_action("stop")

    @work(exclusive=False, thread=False)
    async def action_service_restart(self) -> None:
        await self._control_action("restart")

    @work(exclusive=False, thread=False)
    async def action_service_enable(self) -> None:
        await self._control_action("enable")

    @work(exclusive=False, thread=False)
    async def action_service_disable(self) -> None:
        await self._control_action("disable")

    async def _control_action(self, verb: str) -> None:
        unit = self._selected_unit()
        if not unit:
            self.notify("No service selected.", title="Switchboard", severity="warning")
            return

        self._set_status(f"Running: {verb} {unit} …")
        fn = {
            "start": start_service,
            "stop": stop_service,
            "restart": restart_service,
            "enable": enable_service,
            "disable": disable_service,
        }[verb]

        ok, msg = await fn(unit)
        if ok:
            self.notify(msg, title="OK", severity="information")
        else:
            if "Permission denied" in msg or "polkit" in msg.lower() or "authentication" in msg.lower():
                self.notify(
                    f"Permission denied for '{unit}'.\n"
                    "Configure passwordless sudo for systemctl, or run switchboard with sudo.",
                    title="Permission Error",
                    severity="error",
                    timeout=8,
                )
            else:
                self.notify(msg, title=f"{verb} failed", severity="error", timeout=6)

        # Refresh after action
        await self._do_refresh(full=False)


async def _gather_detail(unit: str) -> tuple[dict[str, str], str]:
    """Fetch service properties and journal logs concurrently."""
    import asyncio
    props_task = asyncio.create_task(get_service_properties(unit))
    logs_task = asyncio.create_task(get_journal_logs(unit))
    props, logs = await asyncio.gather(props_task, logs_task)
    return props, logs
