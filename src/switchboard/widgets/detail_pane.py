"""Detail pane — shows service properties and journal logs."""
from __future__ import annotations

import re

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import TabbedContent, TabPane, RichLog, Static
from textual.widget import Widget

from ..services.models import ServiceInfo


_LOG_LEVEL_RE = re.compile(
    r"\b(ERROR|CRITICAL|EMERG|ALERT|error|critical)\b"
    r"|\b(WARNING|WARN|warning|warn)\b"
    r"|\b(INFO|NOTICE|info|notice)\b"
    r"|\b(DEBUG|debug)\b"
)


def _colorize_log(line: str) -> Text:
    """Apply basic color styling to a journal log line."""
    text = Text(line)
    if re.search(r"\b(error|ERROR|failed|FAILED|critical|CRITICAL|emerg|EMERG)\b", line):
        text.stylize("red")
    elif re.search(r"\b(warn|WARN|warning|WARNING)\b", line):
        text.stylize("yellow")
    elif re.search(r"\b(info|INFO|notice|NOTICE)\b", line):
        text.stylize("cyan")
    return text


class DetailPane(Widget):
    """Bottom panel with Details tab and Logs tab for a selected service."""

    DEFAULT_CSS = """
    DetailPane {
        height: 35%;
        border-top: solid $accent;
        background: $surface;
    }
    DetailPane TabbedContent {
        height: 1fr;
    }
    #detail-props {
        padding: 0 1;
        overflow-y: auto;
    }
    #detail-logs {
        overflow-y: scroll;
        scrollbar-gutter: stable;
    }
    """

    def compose(self) -> ComposeResult:
        with TabbedContent(id="detail-tabs"):
            with TabPane("Details", id="tab-details"):
                yield Static("Select a service to view details.", id="detail-props")
            with TabPane("Logs", id="tab-logs"):
                yield RichLog(id="detail-logs", highlight=True, markup=False, wrap=True)

    def show_details(self, svc: ServiceInfo, props: dict[str, str]) -> None:
        """Render the details tab for the given service."""
        props_widget = self.query_one("#detail-props", Static)

        lines: list[str] = []
        lines.append(f"[bold cyan]Unit:[/]        {svc.unit}")
        lines.append(f"[bold cyan]Description:[/] {svc.description or '—'}")
        lines.append(f"[bold cyan]Load State:[/]  {svc.load_state}")
        lines.append(
            f"[bold cyan]Active:[/]      [{_state_color(svc.active_state)}]"
            f"{svc.active_state} ({svc.sub_state})[/]"
        )
        lines.append(f"[bold cyan]Main PID:[/]    {svc.main_pid or '—'}")
        lines.append(f"[bold cyan]Memory:[/]      {svc.memory_display}")
        lines.append(f"[bold cyan]CPU:[/]         {svc.cpu_display}")
        lines.append(f"[bold cyan]Tasks:[/]       {svc.tasks_display}")

        for key, label in [
            ("UnitFileState", "Unit File"),
            ("FragmentPath", "File Path"),
            ("ActiveEnterTimestamp", "Active Since"),
            ("ExecMainStartTimestamp", "Exec Start"),
            ("Result", "Result"),
            ("ConditionResult", "Condition"),
        ]:
            val = props.get(key, "")
            if val:
                lines.append(f"[bold cyan]{label}:[/] {val}")

        props_widget.update("\n".join(lines))

    def show_logs(self, log_text: str) -> None:
        log_widget = self.query_one("#detail-logs", RichLog)
        log_widget.clear()
        for line in log_text.splitlines():
            log_widget.write(_colorize_log(line))
        log_widget.scroll_end(animate=False)

    def clear_detail(self) -> None:
        self.query_one("#detail-props", Static).update("Select a service to view details.")
        self.query_one("#detail-logs", RichLog).clear()


def _state_color(state: str) -> str:
    mapping = {
        "active": "green",
        "failed": "red",
        "activating": "yellow",
        "deactivating": "yellow",
        "inactive": "dim",
        "reloading": "cyan",
    }
    return mapping.get(state, "white")
