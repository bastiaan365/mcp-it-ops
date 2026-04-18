# mcp-it-ops

MCP server that exposes homelab and IT-ops tools to Claude. Designed to grow tool-by-tool, starting with what's actually testable on a Linux homelab and extending toward AD / Intune / M365 when a corporate test environment is available.

> **Status: v0.0.1 (2026-04-19)** — scaffold + 2 working tools, locally tested on niborserver. Not yet on PyPI; install from source. CI + tests are v0.0.2 priorities.

## What it does today

Once installed and connected to Claude (Desktop or Code), Claude can call:

| Tool | What it does |
|---|---|
| `get_system_health` | Returns the local host's hostname, uptime, 1-min load, memory %, root-disk %, and running container count. Reads `/proc` + shells out to `df` and `docker ps`. |
| `get_grafana_alert_state` | Queries the Grafana Prometheus-style rules API and returns alerts grouped by state (firing / pending / inactive / no_data / error) with name, folder, health, last evaluation, and annotations. |

Two tools is small on purpose — v0.0.1 proves the protocol works end-to-end. Tools get added one at a time with tests.

## Roadmap (next tools, rough order)

- `get_freqtrade_bot_status(bot_name)` — query freqtrade REST API for profit/open trades/win rate
- `query_loki_logs(query, since='1h')` — search container logs via Loki LogQL
- `query_influxdb_flux(query, bucket)` — execute Flux queries
- `get_container_status` — full `docker ps` parsed into structured form
- `get_smartd_health(device='/dev/nvme0n1')` — NVMe SMART metrics for the host disk
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
