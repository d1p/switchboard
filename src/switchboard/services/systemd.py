"""Async systemd interaction layer using subprocess / systemctl."""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from .models import ServiceInfo, UINT64_MAX

# How many units to pass to a single `systemctl show` call.
# Avoids ARG_MAX limits while keeping subprocess count low.
_BATCH_SIZE = 50

# Properties fetched for every unit in batch refreshes
_RESOURCE_PROPS = (
    "Id,Description,LoadState,ActiveState,SubState,"
    "MainPID,MemoryCurrent,CPUUsageNSec,TasksCurrent,"
    "ExecMainStartTimestamp,FragmentPath,UnitFileState,"
    "ActiveEnterTimestamp,InactiveEnterTimestamp,"
    "ConditionResult,Result"
)


async def _run(*args: str, input: Optional[str] = None) -> tuple[int, str, str]:
    """Run a command asynchronously; return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if input else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=input.encode() if input else None)
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def list_all_services() -> list[ServiceInfo]:
    """Return loaded systemd service units (any active state)."""
    rc, out, _ = await _run(
        "systemctl", "list-units",
        "--type=service", "--all",
        "--no-pager", "--output=json",
    )
    if rc == 0 and out.strip():
        try:
            raw = json.loads(out)
            return [
                ServiceInfo(
                    unit=entry.get("unit", ""),
                    description=entry.get("description", ""),
                    load_state=entry.get("load", ""),
                    active_state=entry.get("active", ""),
                    sub_state=entry.get("sub", ""),
                )
                for entry in raw
                if entry.get("unit", "").endswith(".service")
            ]
        except json.JSONDecodeError:
            pass

    # Fallback: plain-text parsing for older systemd
    return await _list_services_plaintext()


async def _list_services_plaintext() -> list[ServiceInfo]:
    """Fallback service list parser for systemd without --output=json."""
    rc, out, _ = await _run(
        "systemctl", "list-units",
        "--type=service", "--all",
        "--no-pager", "--plain", "--no-legend",
    )
    services: list[ServiceInfo] = []
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit, load, active, sub = parts[0], parts[1], parts[2], parts[3]
        description = parts[4].strip() if len(parts) > 4 else ""
        if unit.endswith(".service"):
            services.append(ServiceInfo(
                unit=unit,
                description=description,
                load_state=load,
                active_state=active,
                sub_state=sub,
            ))
    return services


def _parse_properties(text: str) -> dict[str, str]:
    """Parse key=value output from systemctl show."""
    props: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()
    return props


async def get_service_properties(unit: str) -> dict[str, str]:
    """Fetch detailed properties for a single service unit (used for detail pane)."""
    rc, out, _ = await _run(
        "systemctl", "show", unit,
        f"--property={_RESOURCE_PROPS}",
    )
    return _parse_properties(out) if rc == 0 else {}


def _parse_show_output(text: str) -> dict[str, dict[str, str]]:
    """
    Parse the output of `systemctl show unit1 unit2 ... --property=Id,...`.

    systemctl separates each unit's block with a blank line.
    We use the `Id=` field to key the results.
    """
    result: dict[str, dict[str, str]] = {}
    current: dict[str, str] = {}

    for line in text.splitlines():
        if line.strip() == "":
            # End of a unit block
            unit_id = current.get("Id", "")
            if unit_id:
                result[unit_id] = current
            current = {}
        elif "=" in line:
            k, _, v = line.partition("=")
            current[k.strip()] = v.strip()

    # Flush the final block (no trailing blank line)
    unit_id = current.get("Id", "")
    if unit_id:
        result[unit_id] = current

    return result


async def batch_get_resources(units: list[str]) -> dict[str, dict[str, str]]:
    """
    Fetch resource properties for all given units using batched systemctl show calls.

    Passes up to _BATCH_SIZE units per subprocess call instead of one call per unit,
    reducing ~142 subprocesses to ~3 and avoiding module-level asyncio object issues.
    """
    if not units:
        return {}

    tasks = []
    for i in range(0, len(units), _BATCH_SIZE):
        chunk = units[i : i + _BATCH_SIZE]
        tasks.append(_show_batch(chunk))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    merged: dict[str, dict[str, str]] = {}
    for r in results:
        if isinstance(r, dict):
            merged.update(r)

    # Fallback: if a batch fails or misses some units, retry per-unit.
    missing_units = [unit for unit in units if unit not in merged]
    if missing_units:
        retry_results = await asyncio.gather(
            *(get_service_properties(unit) for unit in missing_units),
            return_exceptions=True,
        )
        for unit, props in zip(missing_units, retry_results):
            if isinstance(props, dict) and props:
                merged[unit] = props

    return merged


async def _show_batch(units: list[str]) -> dict[str, dict[str, str]]:
    """Run one `systemctl show unit1 unit2 … --property=...` call and parse it."""
    rc, out, _ = await _run(
        "systemctl", "show",
        f"--property={_RESOURCE_PROPS}",
        *units,
    )
    if rc != 0 or not out.strip():
        return {}
    return _parse_show_output(out)


def _parse_int(value: str, sentinel: int = UINT64_MAX) -> Optional[int]:
    try:
        v = int(value)
        return None if v == sentinel else v
    except (ValueError, TypeError):
        return None


def enrich_service(service: ServiceInfo, props: dict[str, str], elapsed: float) -> None:
    """Update a ServiceInfo in-place from a property dict."""
    service.description = props.get("Description", service.description) or service.description
    service.load_state = props.get("LoadState", service.load_state)
    service.active_state = props.get("ActiveState", service.active_state)
    service.sub_state = props.get("SubState", service.sub_state)
    service.main_pid = _parse_int(props.get("MainPID", "0")) or 0

    memory = _parse_int(props.get("MemoryCurrent", ""))
    cpu = _parse_int(props.get("CPUUsageNSec", ""))
    tasks = _parse_int(props.get("TasksCurrent", ""))
    service.update_resources(memory, cpu, tasks, elapsed)


async def _run_control(verb: str, unit: str) -> tuple[bool, str]:
    """Run a systemctl control command (start/stop/restart/enable/disable)."""
    rc, out, err = await _run("sudo", "systemctl", verb, unit)
    if rc == 0:
        past_tense = {
            "start": "Started",
            "stop": "Stopped",
            "restart": "Restarted",
            "enable": "Enabled",
            "disable": "Disabled",
        }
        return True, f"{past_tense.get(verb, verb.capitalize())} {unit}"
    msg = err.strip() or out.strip() or f"Exit code {rc}"
    return False, msg


async def start_service(unit: str) -> tuple[bool, str]:
    return await _run_control("start", unit)


async def stop_service(unit: str) -> tuple[bool, str]:
    return await _run_control("stop", unit)


async def restart_service(unit: str) -> tuple[bool, str]:
    return await _run_control("restart", unit)


async def enable_service(unit: str) -> tuple[bool, str]:
    return await _run_control("enable", unit)


async def disable_service(unit: str) -> tuple[bool, str]:
    return await _run_control("disable", unit)


async def get_journal_logs(unit: str, lines: int = 80) -> str:
    """Return the last N journal log lines for a service."""
    rc, out, _ = await _run(
        "journalctl", "-u", unit,
        "--no-pager", f"-n{lines}",
        "--output=short",
    )
    return out if rc == 0 else f"(no logs available for {unit})"
