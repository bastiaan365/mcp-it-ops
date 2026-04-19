"""mcp-it-ops — MCP server exposing homelab + IT-ops tools to Claude.

v0.0.1 scope: stdio transport, two working tools (system_health, grafana_alerts).
Run via:
    mcp-it-ops              # uses installed entry point
or:
    python -m mcp_it_ops.server
or for development with the MCP inspector:
    mcp dev src/mcp_it_ops/server.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
import yaml
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PATH = Path(
    os.environ.get("MCP_IT_OPS_CONFIG", "config/settings.yaml")
)


def load_config() -> dict[str, Any]:
    """Load YAML config; return defaults if missing.

    Defaults assume a niborserver-shaped homelab (Grafana on localhost:3000,
    InfluxDB on localhost:8086). Override via config/settings.yaml.
    """
    defaults: dict[str, Any] = {
        "grafana": {
            "url": os.environ.get("GRAFANA_URL", "http://localhost:3000"),
            "user": os.environ.get("GRAFANA_USER", "admin"),
            "password_env": "GRAFANA_PASSWORD",
        },
        "freqtrade": {
            "bots": {
                "steady": {"url": "http://localhost:8090", "user_env": "FT_STEADY_USER", "pass_env": "FT_STEADY_PASS"},
                "fun":    {"url": "http://localhost:8091", "user_env": "FT_FUN_USER",    "pass_env": "FT_FUN_PASS"},
            },
        },
        "loki": {
            "url": os.environ.get("LOKI_URL", "http://localhost:3100"),
        },
    }

    path = DEFAULT_CONFIG_PATH
    if path.exists():
        loaded = yaml.safe_load(path.read_text()) or {}
        for k, v in loaded.items():
            if isinstance(v, dict) and isinstance(defaults.get(k), dict):
                defaults[k].update(v)
            else:
                defaults[k] = v
    return defaults


CONFIG = load_config()

# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------

mcp = FastMCP("mcp-it-ops")

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_system_health() -> dict[str, Any]:
    """Report local system health: disk, memory, load, uptime, container count.

    Reads from /proc and shells out to df, uptime, docker ps. Designed for the
    host the MCP server runs on.
    """
    result: dict[str, Any] = {}

    try:
        result["hostname"] = Path("/etc/hostname").read_text().strip()
    except OSError:
        result["hostname"] = os.uname().nodename

    try:
        with open("/proc/uptime") as f:
            uptime_s = float(f.read().split()[0])
        result["uptime_seconds"] = int(uptime_s)
    except (OSError, ValueError):
        result["uptime_seconds"] = None

    try:
        with open("/proc/loadavg") as f:
            result["load_1min"] = float(f.read().split()[0])
    except (OSError, ValueError):
        result["load_1min"] = None

    try:
        meminfo: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, val = line.split(":", 1)
                meminfo[key] = int(val.strip().split()[0])
        total = meminfo.get("MemTotal", 0)
        avail = meminfo.get("MemAvailable", 0)
        result["memory_used_pct"] = round((total - avail) / total * 100, 1) if total else None
    except (OSError, ValueError, KeyError):
        result["memory_used_pct"] = None

    try:
        df_out = subprocess.run(
            ["df", "-P", "/"], capture_output=True, text=True, timeout=5, check=True
        ).stdout
        line = df_out.strip().splitlines()[1]
        used_pct = int(line.split()[4].rstrip("%"))
        result["disk_root_used_pct"] = used_pct
    except (subprocess.SubprocessError, IndexError, ValueError):
        result["disk_root_used_pct"] = None

    if shutil.which("docker"):
        try:
            count = subprocess.run(
                ["docker", "ps", "-q"], capture_output=True, text=True, timeout=5, check=True
            ).stdout.strip().splitlines()
            result["container_count_running"] = len([x for x in count if x])
        except subprocess.SubprocessError:
            result["container_count_running"] = None
    else:
        result["container_count_running"] = None

    return result


@mcp.tool()
def get_grafana_alert_state() -> dict[str, Any]:
    """List Grafana alert rules with their current state.

    Queries the Grafana Prometheus-style rules API. Reads credentials from the
    config (Grafana URL + user) and from the env var named in
    grafana.password_env (defaults to GRAFANA_PASSWORD). Returns a dict with
    alerts grouped by state (firing/pending/inactive/no_data/error).
    """
    cfg = CONFIG["grafana"]
    url = cfg["url"].rstrip("/")
    user = cfg.get("user", "admin")
    password = os.environ.get(cfg.get("password_env", "GRAFANA_PASSWORD"))

    if not password:
        return {"error": f"Grafana password env var '{cfg.get('password_env')}' not set"}

    try:
        resp = httpx.get(
            f"{url}/api/prometheus/grafana/api/v1/rules",
            auth=(user, password),
            timeout=10,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return {"error": f"Grafana API request failed: {e}"}

    data = resp.json().get("data", {})
    by_state: dict[str, list[dict[str, Any]]] = {
        "firing": [], "pending": [], "inactive": [], "no_data": [], "error": [], "other": [],
    }

    for group in data.get("groups", []):
        folder = group.get("file", "")
        for rule in group.get("rules", []):
            state = rule.get("state", "other")
            entry = {
                "name": rule.get("name"),
                "folder": folder,
                "health": rule.get("health"),
                "last_evaluation": rule.get("lastEvaluation"),
                "annotations": rule.get("annotations", {}),
            }
            by_state.setdefault(state, by_state["other"]).append(entry)

    return {
        "summary": {state: len(entries) for state, entries in by_state.items() if entries},
        "alerts": {state: entries for state, entries in by_state.items() if entries},
    }


@mcp.tool()
def get_freqtrade_bot_status(bot_name: str) -> dict[str, Any]:
    """Query a freqtrade bot's REST API for its current trading state.

    bot_name must match a key under freqtrade.bots in config (e.g. 'steady', 'fun').
    Reads basic-auth credentials from the env vars named in user_env / pass_env
    on the bot's config entry.

    Returns a dict with: bot_name, dry_run, strategy, timeframe, exchange,
    closed_trade_count, open_trade_count, realised_p_and_l_fiat,
    realised_p_and_l_pct, total_p_and_l_fiat, total_p_and_l_pct, win_rate,
    open_positions (list of {pair, opened, current_pnl_fiat, current_pnl_pct}).

    Returns {"error": "..."} on any failure (unknown bot, missing creds, API down).
    """
    bots = CONFIG.get("freqtrade", {}).get("bots", {})
    bot = bots.get(bot_name)
    if not bot:
        return {"error": f"Unknown bot '{bot_name}'. Configured bots: {list(bots.keys())}"}

    user = os.environ.get(bot.get("user_env", ""))
    password = os.environ.get(bot.get("pass_env", ""))
    if not user or not password:
        return {"error": f"Missing credentials for bot '{bot_name}' (env vars {bot.get('user_env')} / {bot.get('pass_env')})"}

    base_url = bot["url"].rstrip("/")
    auth = (user, password)

    try:
        cfg_resp = httpx.get(f"{base_url}/api/v1/show_config", auth=auth, timeout=10)
        cfg_resp.raise_for_status()
        profit_resp = httpx.get(f"{base_url}/api/v1/profit", auth=auth, timeout=10)
        profit_resp.raise_for_status()
        status_resp = httpx.get(f"{base_url}/api/v1/status", auth=auth, timeout=10)
        status_resp.raise_for_status()
    except httpx.HTTPError as e:
        return {"error": f"freqtrade API request failed for '{bot_name}': {e}"}

    cfg_d = cfg_resp.json()
    profit_d = profit_resp.json()
    status_d = status_resp.json()

    open_positions = [
        {
            "pair": t.get("pair"),
            "opened": t.get("open_date"),
            "open_rate": t.get("open_rate"),
            "current_rate": t.get("current_rate"),
            "current_pnl_fiat": t.get("profit_abs"),
            "current_pnl_pct": t.get("profit_pct"),
        }
        for t in status_d
    ]

    return {
        "bot_name": bot_name,
        "dry_run": cfg_d.get("dry_run"),
        "strategy": cfg_d.get("strategy"),
        "timeframe": cfg_d.get("timeframe"),
        "exchange": cfg_d.get("exchange"),
        "closed_trade_count": profit_d.get("closed_trade_count"),
        "open_trade_count": profit_d.get("trade_count", 0) - profit_d.get("closed_trade_count", 0),
        "realised_p_and_l_fiat": profit_d.get("profit_closed_fiat"),
        "realised_p_and_l_pct": profit_d.get("profit_closed_percent"),
        "total_p_and_l_fiat": profit_d.get("profit_all_fiat"),
        "total_p_and_l_pct": profit_d.get("profit_all_percent"),
        "win_rate": profit_d.get("winrate"),
        "open_positions": open_positions,
    }


@mcp.tool()
def get_container_status() -> dict[str, Any]:
    """Return structured docker-ps output: per-container name, image, state, status, ports, age.

    Shells out to docker ps with a tab-separated format string. Returns a list of containers
    plus a summary dict. Read-only — does not stop/restart anything.

    Returns {"error": "..."} if docker isn't installed or the docker socket is unreachable.
    """
    if not shutil.which("docker"):
        return {"error": "docker binary not found in PATH"}

    fmt = "{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Status}}\t{{.Ports}}\t{{.RunningFor}}"
    try:
        out = subprocess.run(
            ["docker", "ps", "-a", "--format", fmt],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except subprocess.SubprocessError as e:
        return {"error": f"docker ps failed: {e}"}

    containers = []
    for line in out.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        name, image, state, status, ports, age = parts[:6]
        containers.append({
            "name": name,
            "image": image,
            "state": state,
            "status": status,
            "ports": ports if ports else None,
            "age": age,
        })

    summary = {
        "total": len(containers),
        "running": sum(1 for c in containers if c["state"] == "running"),
        "exited":  sum(1 for c in containers if c["state"] == "exited"),
        "other":   sum(1 for c in containers if c["state"] not in ("running", "exited")),
    }
    return {"summary": summary, "containers": containers}


@mcp.tool()
def query_loki_logs(query: str, since: str = "1h", limit: int = 100) -> dict[str, Any]:
    """Search container/syslog logs via Loki LogQL.

    query: LogQL query string, e.g. '{container="grafana"}' or '{container=~".+"} |= "ERROR"'
    since: how far back, e.g. '1h', '30m', '7d' (Loki duration syntax)
    limit: max log lines to return (Loki default = 100, hard-capped here at 1000)

    Returns a dict with: total_streams, total_lines, streams (list of {labels, lines}).
    Lines are timestamp-sorted oldest-first. Returns {"error": "..."} on Loki unreachable
    or invalid query.
    """
    cfg = CONFIG.get("loki", {})
    url = cfg.get("url", "http://localhost:3100").rstrip("/")
    limit = min(max(1, limit), 1000)

    try:
        resp = httpx.get(
            f"{url}/loki/api/v1/query_range",
            params={"query": query, "since": since, "limit": str(limit), "direction": "forward"},
            timeout=15,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return {"error": f"Loki query failed: {e}"}

    data = resp.json().get("data", {})
    streams = []
    total_lines = 0
    for item in data.get("result", []):
        labels = item.get("stream", {})
        values = item.get("values", [])  # [[ts_ns, line], ...]
        lines = [{"timestamp_ns": v[0], "line": v[1]} for v in values]
        streams.append({"labels": labels, "lines": lines, "line_count": len(lines)})
        total_lines += len(lines)

    return {
        "query": query,
        "since": since,
        "total_streams": len(streams),
        "total_lines": total_lines,
        "streams": streams,
    }


@mcp.tool()
def get_smartd_health(device: str = "/dev/nvme0n1") -> dict[str, Any]:
    """Query SMART health for a storage device via smartctl.

    device: /dev/nvme0n1, /dev/sda, etc. Default is niborserver's NVMe.
    Returns: overall_health, critical_warning, temperature_c, available_spare_pct,
    percentage_used_pct, power_on_hours, unsafe_shutdowns, media_errors.

    Requires sudo (smartctl needs raw device access). Returns {"error": ...} if
    smartctl isn't installed or sudo isn't permitted (the calling user must
    have NOPASSWD sudo for smartctl OR the MCP server must run as root).
    """
    if not shutil.which("smartctl"):
        return {"error": "smartctl not installed"}

    try:
        out = subprocess.run(
            ["sudo", "-n", "smartctl", "-a", device],
            capture_output=True, text=True, timeout=15,
        )
    except subprocess.SubprocessError as e:
        return {"error": f"smartctl failed: {e}"}

    text = out.stdout
    if not text.strip():
        return {"error": f"smartctl produced no output (sudo denied? need NOPASSWD or run as root): {out.stderr.strip() or 'no stderr'}"}

    def grab(pattern: str, cast=str) -> Any:
        import re
        m = re.search(pattern, text, re.MULTILINE)
        if not m:
            return None
        try:
            return cast(m.group(1).replace(",", "").strip())
        except (ValueError, AttributeError):
            return None

    return {
        "device": device,
        "overall_health": grab(r"SMART overall-health self-assessment test result:\s+(\S+)"),
        "critical_warning": grab(r"Critical Warning:\s+(\S+)"),
        "temperature_c": grab(r"Temperature:\s+(\d+)", int),
        "available_spare_pct": grab(r"Available Spare:\s+(\d+)%", int),
        "percentage_used_pct": grab(r"Percentage Used:\s+(\d+)%", int),
        "power_on_hours": grab(r"Power On Hours:\s+([\d,]+)", int),
        "unsafe_shutdowns": grab(r"Unsafe Shutdowns:\s+([\d,]+)", int),
        "media_errors": grab(r"Media and Data Integrity Errors:\s+(\d+)", int),
    }


@mcp.tool()
def get_backup_status() -> dict[str, Any]:
    """Report on the niborserver backup pipeline's last run.

    Reads /var/log/niborserver-backup.log and reports: last_run_started,
    last_run_completed, last_run_duration_seconds, last_run_size, last_run_succeeded,
    snapshots_on_destination (count of YYYY-MM-DD dirs visible to local checks).

    Returns {"error": ...} if the log doesn't exist (backup not yet run).
    """
    log_path = "/var/log/niborserver-backup.log"
    if not Path(log_path).exists():
        return {"error": f"backup log not found at {log_path} — backup may not have run yet"}

    try:
        with open(log_path) as f:
            lines = f.readlines()
    except OSError as e:
        return {"error": f"could not read backup log: {e}"}

    if not lines:
        return {"error": "backup log is empty"}

    started_line = None
    completed_line = None
    size = None
    succeeded = False

    for line in reversed(lines):
        if completed_line is None and ("complete" in line or "FAIL" in line):
            completed_line = line.strip()
            succeeded = "complete" in line and "FAIL" not in line
            import re
            m = re.search(r"complete.*?\u2014\s*(\S+)", line)
            if m:
                size = m.group(1)
        if started_line is None and "starting" in line:
            started_line = line.strip()
        if started_line and completed_line:
            break

    def parse_ts(line: str | None) -> str | None:
        if not line:
            return None
        import re
        m = re.match(r"\[(\d{2}:\d{2}:\d{2})\]", line)
        return m.group(1) if m else None

    duration_seconds = None
    if started_line and completed_line:
        from datetime import datetime
        try:
            t1 = datetime.strptime(parse_ts(started_line), "%H:%M:%S")
            t2 = datetime.strptime(parse_ts(completed_line), "%H:%M:%S")
            duration_seconds = int((t2 - t1).total_seconds())
        except (ValueError, TypeError):
            pass

    return {
        "last_run_started_at": parse_ts(started_line),
        "last_run_completed_at": parse_ts(completed_line),
        "last_run_duration_seconds": duration_seconds,
        "last_run_size": size,
        "last_run_succeeded": succeeded,
        "log_path": log_path,
        "log_total_lines": len(lines),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server over stdio (Claude Desktop / mcp dev mode)."""
    mcp.run()


if __name__ == "__main__":
    main()
