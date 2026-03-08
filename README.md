# Switchboard

A modern, keyboard-driven terminal UI for managing systemd services on Linux.
View status, resource usage, and journal logs — and start, stop, or restart services — all from one interactive dashboard.

```
┌─ Switchboard ───────────────────────────────────────────────────────────────────────┐
│  search: _                                                                          │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ Service                       Description                         Status   Mem   CPU│
│ accounts-daemon.service       Accounts Service                  ● running 1.4MB   — │
│ docker.service                Docker Application Container Eng  ● running 82MB 0.1% │
│ NetworkManager.service        Network Manager                   ● running 12MB   —  │
│ ollama.service                Ollama Service                    ● running 1.2GB 4%  │
│ sshd.service                  OpenSSH Daemon                    ● running 4.1MB —   │
│ openvpn.service               OpenVPN service                   ● dead    —     —   │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ [Details] [Logs]                                                                    │
│ Unit:        docker.service                                                         │
│ Active:      active (running)                                                       │
│ Memory:      82.3 MB                                                                │
└─────────────────────────────────────────────────────────────────────────────────────┘
  s:Start  x:Stop  r:Restart  e:Enable  d:Disable  /:Search  F5:Refresh  q:Quit
```

---

## Requirements

- Linux with systemd
- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) (recommended) **or** pip

---

## Installation

### Option 1 — Run directly with uv (no install needed)

```bash
git clone https://github.com/youruser/switchboard
cd switchboard
uv run switchboard
```

`uv` will create a virtual environment and install all dependencies automatically on first run.

### Option 2 — Install as a command (uv tool)

```bash
git clone https://github.com/youruser/switchboard
cd switchboard
uv tool install .
```

The `switchboard` command is then available globally in your shell:

```bash
switchboard
```

### Option 3 — Install with pip into a virtualenv

```bash
git clone https://github.com/youruser/switchboard
cd switchboard
python -m venv .venv
source .venv/bin/activate
pip install .
switchboard
```

---

## Permissions

Switchboard reads service status and resource data **without root**. It only needs elevated privileges when you start, stop, restart, enable, or disable a service.

When you trigger one of those actions, it runs `sudo systemctl <verb> <unit>`. A standard sudo password prompt will appear in your terminal.

### Passwordless sudo (optional)

To skip the password prompt for systemctl control commands, add a rule to sudoers:

```bash
sudo visudo -f /etc/sudoers.d/switchboard
```

Add:
```
%wheel ALL=(ALL) NOPASSWD: /usr/bin/systemctl start *
%wheel ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop *
%wheel ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart *
%wheel ALL=(ALL) NOPASSWD: /usr/bin/systemctl enable *
%wheel ALL=(ALL) NOPASSWD: /usr/bin/systemctl disable *
```

Replace `%wheel` with your username or group as appropriate.

---

## Usage

### Starting the app

```bash
switchboard
```

The table loads loaded systemd service units via `systemctl list-units --type=service --all` (active, inactive, failed, etc.). Resource data (memory, CPU, tasks) populates in a second pass and refreshes automatically every 3 seconds.

---

### Keyboard Reference

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate services |
| `s` | **Start** the selected service |
| `x` | **Stop** the selected service |
| `r` | **Restart** the selected service |
| `e` | **Enable** the selected service (start on boot) |
| `d` | **Disable** the selected service |
| `/` | Focus the search bar |
| `Escape` | Clear the search filter |
| `F5` or `Ctrl+R` | Force a full refresh |
| `q` | Quit |

---

### Columns

| Column | Description |
|--------|-------------|
| **Service** | systemd unit name (e.g. `docker.service`) |
| **Description** | From the unit's `Description=` field |
| **Status** | Color-coded: ● green = running, ● red = failed, ● yellow = activating, ● dim = inactive |
| **Memory** | Current RSS from cgroup accounting |
| **CPU** | CPU usage % calculated between refresh intervals |
| **Tasks** | Number of tasks/threads spawned by the service |

---

### Search / Filter

Press `/` to jump to the search bar. Type any part of the service name or description — the table filters in real-time. Use the **status dropdown** next to search to filter by service active state. Press `Escape` to clear both filters and return focus to the table.

---

### Detail Pane

Selecting a row (via arrow keys) opens the bottom detail pane with two tabs:

- **Details** — unit file path, active/load state, PID, memory, CPU, enable state, start timestamp
- **Logs** — last 80 lines from `journalctl -u <unit>`, with color-coded log levels (red = ERROR, yellow = WARN, cyan = INFO)

---

## Development

Install dev dependencies:

```bash
uv sync --extra dev
```

Run with the Textual development console (live CSS editing + widget inspector):

```bash
uv run textual run --dev src/switchboard/__main__.py
# In a second terminal:
uv run textual console
```

Run tests:

```bash
uv run pytest
```

---

## How it Works

Switchboard uses:

- **[Textual](https://github.com/Textualize/textual)** — async Python TUI framework for the full-screen interface, layout, key bindings, and widgets
- **[Rich](https://github.com/Textualize/rich)** — color rendering inside table cells and the log pane
- **`systemctl`** (subprocess) — service listing, property fetching, and control commands
- **`journalctl`** (subprocess) — journal log retrieval per service

All `systemctl`/`journalctl` calls are async (`asyncio.create_subprocess_exec`), keeping the UI fully responsive during data fetches. Resource refreshes use batched `systemctl show` calls (up to 50 units per call) with per-unit fallback retries for any missing units.
