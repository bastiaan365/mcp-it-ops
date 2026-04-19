# mcp-it-ops

MCP server that exposes homelab and IT-ops tools to Claude. Designed to grow tool-by-tool, starting with what's actually testable on a Linux homelab and extending toward AD / Intune / M365 when a corporate test environment is available.

> **Status: v0.0.5 (2026-04-19)** — 8 working tools, 37 pytest tests, CI green on Python 3.10/3.11/3.12. Tools split into category modules under `tools/`. Locally tested on niborserver. Not yet on PyPI; install from source.

## What it does today

Once installed and connected to Claude (Desktop or Code), Claude can call:

| Tool | What it does |
|---|---|
| `get_system_health` | Local host's hostname, uptime, 1-min load, memory %, root-disk %, and running container count. Reads `/proc` + shells out to `df` and `docker ps`. |
| `get_grafana_alert_state` | Queries the Grafana Prometheus-style rules API and returns alerts grouped by state (firing / pending / inactive / no_data / error) with name, folder, health, last evaluation, annotations. |
| `get_freqtrade_bot_status(bot)` | Profit, win rate, open trade count, balance from a freqtrade REST API. Bot name resolved via config. |
| `get_container_status` | Full `docker ps` parsed into structured per-container records (name, image, state, health, uptime, ports). |
| `query_loki_logs(query, since, limit)` | Loki LogQL `query_range` against `localhost:3100`. Returns structured streams + lines, limit clamped to 1000. |
| `get_smartd_health(device='/dev/nvme0n1')` | NVMe/SATA SMART health via `sudo smartctl -a` — overall health, critical warning, temperature, available spare, percentage used, power-on hours, unsafe shutdowns, media errors. |
| `get_backup_status` | Reads `/var/log/niborserver-backup.log` and reports last_run_started/completed/duration/size/succeeded. Closes the "watch the watchers" loop. |
| `query_influxdb_flux(flux, bucket)` | Executes a Flux query against the local InfluxDB v2 and returns parsed CSV records (capped at 500 rows). Auth via `INFLUXDB_TOKEN` + `INFLUXDB_ORG` env vars. |

## Roadmap

- `get_uptime_kuma_status` — pull monitor states via Uptime Kuma API
- HTTP transport so openclaw / other tailnet peers can query niborserver-resident tools (currently stdio only)
- _Eventually_: `get_ad_user`, `get_intune_compliance`, `get_m365_service_health` — when a corporate test environment is available

## Quickstart

### On the host where the MCP server will run

```bash
git clone https://github.com/bastiaan365/mcp-it-ops.git
cd mcp-it-ops
python3 -m venv .venv
.venv/bin/pip install -e .
```

### Configuration

Copy the example and customise:

```bash
cp config/settings.example.yaml config/settings.yaml
# Edit config/settings.yaml — point at your Grafana, freqtrade bots, etc.
```

Secrets come from environment variables, never from the YAML. Default env var names:

| Env var | What |
|---|---|
| `GRAFANA_PASSWORD` | Grafana admin password (referenced from `grafana.password_env`) |
| `FT_STEADY_USER` / `FT_STEADY_PASS` | freqtrade bot1 API basic auth |
| `FT_FUN_USER` / `FT_FUN_PASS` | freqtrade bot2 API basic auth |

### Connect to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, or `%APPDATA%/Claude/claude_desktop_config.json` on Windows:

```json
{
  "mcpServers": {
    "it-ops": {
      "command": "/path/to/mcp-it-ops/.venv/bin/mcp-it-ops",
      "env": {
        "GRAFANA_PASSWORD": "your-grafana-password",
        "MCP_IT_OPS_CONFIG": "/path/to/mcp-it-ops/config/settings.yaml"
      }
    }
  }
}
```

Restart Claude Desktop. The tools appear under "it-ops".

### Smoke-test without Claude

```bash
GRAFANA_PASSWORD=... .venv/bin/python -c "
from mcp_it_ops.server import get_system_health, get_grafana_alert_state
import json
print(json.dumps(get_system_health(), indent=2))
print(json.dumps(get_grafana_alert_state().get('summary'), indent=2))
"
```

Or use the official MCP inspector:

```bash
.venv/bin/python -m mcp dev src/mcp_it_ops/server.py
```

## Requirements

- Python 3.10+
- `mcp>=1.27.0`, `httpx>=0.27`, `pyyaml>=6.0` (auto-installed)
- Read access to `/proc`, `df`, `docker ps` for `get_system_health`
- Network reach + credentials for the services you want tools for

## How development works

- `src/mcp_it_ops/server.py` — all tool definitions
- `tests/` — pytest tests; one file per tool (TODO: backfill)
- `config/settings.example.yaml` — committed template; `config/settings.yaml` is gitignored

When adding a tool: see [`CLAUDE.md`](./CLAUDE.md) for the workflow + design conventions.

## License

MIT
