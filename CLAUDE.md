# mcp-it-ops

MCP (Model Context Protocol) server that gives Claude direct, structured access to homelab and IT-ops tools — system health, Grafana alert state, freqtrade bot APIs, and more. Maintained by Bastiaan ([@bastiaan365](https://github.com/bastiaan365)).

This file scopes Claude's behaviour for this repo. The global `~/.claude/CLAUDE.md` covers personal conventions; everything below is repo-specific.

## What this repo is

- **A working MCP server** as of v0.0.1 (2026-04-19). Not vapor anymore — speaks the protocol, registers tools, runs over stdio. Two tools shipped (`get_system_health`, `get_grafana_alert_state`). Designed to grow tool-by-tool.
- **Niborserver-shaped by default**: defaults assume Grafana on `localhost:3000`, freqtrade bots on `:8090`/`:8091`. Override via `config/settings.yaml` for other deployments.
- **Stdio transport** (Claude Desktop / `mcp dev`) for now. HTTP transport would let openclaw or other tailnet peers query — flagged for future work.

## Repo conventions

### Structure

```
src/mcp_it_ops/
├── __init__.py
├── config.py            # YAML + env-var config loading; CONFIG dict
├── server.py            # FastMCP setup + main(); imports tools and registers them
└── tools/
    ├── __init__.py
    ├── host.py          # local-host ops: system, smartd, containers, backup
    ├── observability.py # grafana_alerts, loki_logs, influxdb_flux
    └── freqtrade.py     # freqtrade bot REST API
tests/                   # pytest tests; one test file per tool
config/
├── settings.example.yaml   # committed template
└── settings.yaml           # gitignored — local overrides
pyproject.toml           # PEP 621, requires Python 3.10+
.github/workflows/ci.yml # matrix CI on Python 3.10/3.11/3.12
```

Tools are plain functions returning dicts (no MCP coupling). `server.py` registers them via `mcp.tool()(fn)`. New categories: add a new `tools/<category>.py` module and a corresponding import + registration in `server.py`. Keep one tool per module-level function with a clear docstring.

### Python style

- **Python 3.10+** target (matches MCP SDK floor).
- `from __future__ import annotations` at top of every module that uses forward refs.
- Type hints on every public function. Tools especially — the type hints become the tool schema Claude sees.
- f-strings for formatting; never `.format()` or `%` style.
- One module = one concern. `server.py` stays focused on registration + tool definitions; complex logic moves to helper modules.
- snake_case for tool names (matches freqtrade, k8s, github CLI conventions; matches the MCP ecosystem norm).

### Tool design

Every tool function:

1. Has a clear, single-sentence first line in its docstring — that becomes the tool description Claude reads.
2. Returns structured data (dict / list of dicts) — never plain strings. The structure is the API.
3. Handles errors by returning `{"error": "<reason>"}` rather than raising. Claude can read errors as data.
4. Times out (httpx `timeout=10`, subprocess `timeout=5`) — never blocks the MCP server forever.
5. Reads secrets from environment variables, never from positional args. Tool callers must not pass secrets in tool parameters because Claude/users see them.
6. Defaults safely — if a config field is missing, the tool returns an `error` field explaining what's missing rather than crashing.

### Testing

- pytest, async mode auto. `tests/test_<tool_name>.py` per tool.
- For tools that hit external services (Grafana, freqtrade, InfluxDB), mock httpx with `respx` or use pytest fixtures with deterministic responses.
- For tools that read /proc or shell out, mock `subprocess.run` and `Path.read_text` — never let tests touch real `/proc/uptime`.
- Run: `.venv/bin/python -m pytest tests/ -v`

### Validation gates

Before any commit:

- `python -m py_compile src/mcp_it_ops/**/*.py` — fast syntax check
- `python -m pytest tests/ -v` — all pass
- Sanity-load the server: `.venv/bin/python -c "from mcp_it_ops.server import mcp; import asyncio; print(len(asyncio.run(mcp.list_tools())))"` — should print the tool count without errors
- For tools that hit external services: confirm at least one real-environment call works (e.g., on niborserver: `GRAFANA_PASSWORD=... .venv/bin/python -c "from mcp_it_ops.server import get_grafana_alert_state; print(get_grafana_alert_state())"`)
- Leak grep before commit:
  ```bash
  grep -REn 'AGE-SECRET-KEY|akv8h|UnifiedHouse|aumjz' src/ tests/ config/ README.md \
    | grep -vE '"version"|^[^:]+:[0-9]+:\s*#'
  ```
  No hits expected — all secrets must be env-var references, never literals.

## Workflow expectations for Claude

When I ask you to **add a new tool**:

1. Propose the tool signature first as plain text (name, parameters, return shape) before writing code.
2. Implement in `server.py` (until refactor needed). Add type hints + the structured-error-return pattern.
3. Add `tests/test_<tool_name>.py` with at minimum: happy path, missing-config, external-service-error.
4. Update README's "Available tools" section.
5. Run pytest + the sanity-load before declaring done.

When I ask you to **modify an existing tool**:

1. Show the diff.
2. If the return shape changes (a new field, a removed field), call it a breaking change explicitly. The tool schema is part of Claude's prompt; downstream prompts may depend on it.
3. Update the tool's tests.

When I ask you to **add a new dependency**:

1. Add to `pyproject.toml` with a `>=X.Y` lower bound (not pinned).
2. Justify why it's needed (one sentence) — fewer deps = less attack surface.
3. Run `pip install -e ".[dev]"` and confirm tests still pass.

When I ask you to **expose a new external service** (HA Prometheus endpoint, OPNsense API, Loki logs):

1. Confirm the service is actually reachable from where the MCP server runs (default: niborserver).
2. Decide: is this a read-only tool or a write tool? **Default to read-only.** Write tools (create AD user, restart container, modify Grafana dashboard) need extra confirmation in the docstring and explicit user opt-in via a `confirm: bool = False` parameter.
3. Cache or rate-limit if the service is rate-sensitive.

## Things to avoid

- Hardcoding URLs, hostnames, or credentials anywhere outside `config/settings.example.yaml` (and even there, only env-var references — never values).
- Shell injection — always use list-form `subprocess.run(["cmd", "arg"], ...)`, never `subprocess.run("cmd " + user_input, shell=True)`.
- Blocking the event loop. If a tool needs a long-running call, use `httpx.AsyncClient` and an `async def` tool function.
- Returning huge payloads (>~50KB). Paginate or summarise. Claude has a context budget per tool call.
- `print()` in tool functions — output goes to stdout, which is the MCP transport. Use `logging.info()` if you need logs.
- Adding tools that perform writes to homelab services (e.g., creating a Grafana alert, modifying freqtrade config) without an explicit `confirm: bool = False` parameter that defaults to refusing.

## Related repos

- [`grafana-dashboards`](https://github.com/bastiaan365/grafana-dashboards) — the dashboards that the `get_grafana_alert_state` tool talks to
- [`homelab-infrastructure`](https://github.com/bastiaan365/homelab-infrastructure) — the network these tools live in
- [`Job-Agent`](https://github.com/bastiaan365/Job-Agent) — sibling Python project; conventions kept compatible (src layout, pytest, ruff/black-friendly)

## Drift from target structure

_Claude maintains this section. List anything in the repo that doesn't match the conventions above, with why it's still there and what would need to happen to fix it._

- **Stdio transport only** — HTTP transport would let openclaw and other tailnet peers query niborserver-resident MCP tools. v0.1+.
- **Homelab-only subset** — the original README aspirationally listed 18 tools across AD/Intune/M365/network/system. Currently 8 tools, all homelab-resident and testable on niborserver. Enterprise tools (AD/Intune/M365) wait until there's a corporate test environment.
- _(Resolved at v0.0.2: CI workflow added, pytest tests added.)_
- _(Resolved at v0.0.5: server.py refactored into tools/ modules per the threshold rule.)_
