"""Config loading for mcp-it-ops tools.

Defaults assume a niborserver-shaped homelab (Grafana on localhost:3000,
InfluxDB on localhost:8086, Loki on localhost:3100). Override via
config/settings.yaml. Path is set via MCP_IT_OPS_CONFIG env var.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(
    os.environ.get("MCP_IT_OPS_CONFIG", "config/settings.yaml")
)


def load_config() -> dict[str, Any]:
    """Load YAML config; merge over niborserver defaults."""
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
        "influxdb": {
            "url": os.environ.get("INFLUXDB_URL", "http://localhost:8086"),
            "org_env": "INFLUXDB_ORG",
            "token_env": "INFLUXDB_TOKEN",
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
