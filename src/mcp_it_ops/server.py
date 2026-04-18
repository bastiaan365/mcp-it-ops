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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server over stdio (Claude Desktop / mcp dev mode)."""
    mcp.run()


if __name__ == "__main__":
    main()
