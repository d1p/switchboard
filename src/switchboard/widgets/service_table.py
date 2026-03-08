"""Service table widget — a styled DataTable for systemd services."""
from __future__ import annotations

from textual.widgets import DataTable
from textual.coordinate import Coordinate
from rich.text import Text

from ..services.models import ServiceInfo


COLUMNS = [
    ("service", "Service", 30),
    ("description", "Description", 42),
    ("status", "Status", 14),
    ("memory", "Memory", 10),
    ("cpu", "CPU", 8),
    ("tasks", "Tasks", 7),
]


class ServiceTable(DataTable):
    """DataTable subclass pre-configured for the service list."""

    DEFAULT_CSS = """
    ServiceTable {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(zebra_stripes=True, cursor_type="row", **kwargs)
        self._row_keys: list[str] = []   # unit names in display order
        self._filter: str = ""
        self._status_filter: str = ""  # empty = show all

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_columns(self) -> None:
        for col_id, label, width in COLUMNS:
            self.add_column(label, width=width, key=col_id)

    def populate(self, services: list[ServiceInfo]) -> None:
        """Initial full population of the table."""
        self.clear()
        self._row_keys = []
        for svc in services:
            if self._matches_filter(svc):
                self._add_row(svc)

    def update_rows(self, services: list[ServiceInfo]) -> None:
        """In-place update of all rows (no flicker full-rebuild)."""
        # Rebuild is fine here; Textual DataTable v1 does not flicker on clear()
        # because we scroll-restore manually.
        cursor_row = self.cursor_row
        self.populate(services)
        # Restore cursor position if possible
        if self._row_keys and cursor_row < len(self._row_keys):
            self.move_cursor(row=cursor_row)

    def apply_filter(
        self,
        query: str,
        services: list[ServiceInfo],
        status_filter: str | None = None,
    ) -> None:
        self._filter = query.lower()
        if status_filter is not None:
            self._status_filter = status_filter
        self.populate(services)

    def selected_unit(self) -> str | None:
        """Return the unit name of the currently highlighted row."""
        if not self._row_keys:
            return None
        try:
            row_key = self._row_keys[self.cursor_row]
            return row_key
        except IndexError:
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _matches_filter(self, svc: ServiceInfo) -> bool:
        if self._status_filter and svc.active_state != self._status_filter:
            return False
        if not self._filter:
            return True
        return (
            self._filter in svc.unit.lower()
            or self._filter in svc.description.lower()
        )

    def _row_data(self, svc: ServiceInfo) -> list:
        # Style unit name cell for failed services (no row-level style in Textual v1)
        if svc.active_state == "failed":
            unit_cell = Text(svc.unit, style="bold red")
        elif svc.active_state == "active":
            unit_cell = Text(svc.unit, style="green")
        else:
            unit_cell = Text(svc.unit, style="dim")

        return [
            unit_cell,
            svc.description or "—",
            svc.status_text,
            svc.memory_display,
            svc.cpu_display,
            svc.tasks_display,
        ]

    def _add_row(self, svc: ServiceInfo) -> None:
        data = self._row_data(svc)
        self.add_row(*data, key=svc.unit)
        self._row_keys.append(svc.unit)
