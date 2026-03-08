"""Data models for systemd service information."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from rich.text import Text

# systemd sentinel: MemoryCurrent / CPUUsageNSec when accounting is off
UINT64_MAX = 18446744073709551615


@dataclass
class ServiceInfo:
    unit: str
    description: str
    load_state: str
    active_state: str
    sub_state: str
    main_pid: int = 0
    memory_bytes: Optional[int] = None
    cpu_ns: Optional[int] = None       # cumulative nanoseconds
    cpu_ns_prev: Optional[int] = None  # previous sample for delta calc
    cpu_elapsed_prev: float = 0.0      # seconds since last sample
    tasks: Optional[int] = None

    # --- display helpers ---

    @property
    def status_text(self) -> Text:
        """Rich Text with colored status indicator."""
        state = self.active_state
        sub = self.sub_state
        label = f"● {sub}"
        if state == "active" and sub == "running":
            return Text(label, style="bold green")
        elif state == "active":
            return Text(label, style="green")
        elif state == "failed":
            return Text(label, style="bold red")
        elif state == "activating":
            return Text(label, style="bold yellow")
        elif state == "deactivating":
            return Text(label, style="yellow")
        elif state == "reloading":
            return Text(label, style="bold cyan")
        else:
            return Text(label, style="dim")

    @property
    def memory_display(self) -> str:
        if self.memory_bytes is None:
            return "—"
        b = self.memory_bytes
        if b >= 1024 ** 3:
            return f"{b / 1024**3:.1f} GB"
        elif b >= 1024 ** 2:
            return f"{b / 1024**2:.1f} MB"
        elif b >= 1024:
            return f"{b / 1024:.1f} KB"
        return f"{b} B"

    @property
    def cpu_display(self) -> str:
        """Return CPU % calculated from delta between two samples."""
        if (
            self.cpu_ns is None
            or self.cpu_ns_prev is None
            or self.cpu_elapsed_prev <= 0
        ):
            return "—"
        delta_ns = self.cpu_ns - self.cpu_ns_prev
        if delta_ns < 0:
            return "—"
        pct = delta_ns / (self.cpu_elapsed_prev * 1e9) * 100
        return f"{pct:.1f}%"

    @property
    def tasks_display(self) -> str:
        return "—" if self.tasks is None else str(self.tasks)

    def update_resources(
        self,
        memory_bytes: Optional[int],
        cpu_ns: Optional[int],
        tasks: Optional[int],
        elapsed: float,
    ) -> None:
        """Update resource fields, preserving previous CPU sample for delta."""
        self.memory_bytes = memory_bytes
        self.cpu_ns_prev = self.cpu_ns
        self.cpu_elapsed_prev = elapsed
        self.cpu_ns = cpu_ns
        self.tasks = tasks
