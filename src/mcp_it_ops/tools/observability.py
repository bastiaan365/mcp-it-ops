"""Observability tools: Grafana alerts + Loki logs.

These tools query the local Grafana / Loki stack on niborserver. URLs come
from the YAML config; secrets come from environment variables.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..config import CONFIG


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
        values = item.get("values", [])
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


def query_influxdb_flux(flux: str, bucket: str = "monitoring") -> dict[str, Any]:
    """Execute a Flux query against the local InfluxDB and return parsed records.

    flux: Flux query string. The bucket is NOT auto-substituted — include
        `from(bucket:"<bucket>") |> range(start: -1h) |> ...` yourself.
    bucket: name surfaced in the response for context (does not modify the query).

    Reads InfluxDB URL from config (`influxdb.url`, default localhost:8086) and the
    org + token from the env vars named in `influxdb.org_env` / `influxdb.token_env`
    (default `INFLUXDB_ORG` / `INFLUXDB_TOKEN`).

    Returns: {bucket, row_count, columns, records (list of dicts), truncated_at}.
    Records are capped at 500 rows to keep Claude's context manageable; if more
    were returned, `truncated_at: 500` appears in the response.

    Returns {"error": "..."} on missing token, network failure, or Flux syntax error.
    """
    cfg = CONFIG.get("influxdb", {})
    url = cfg.get("url", "http://localhost:8086").rstrip("/")
    org = os.environ.get(cfg.get("org_env", "INFLUXDB_ORG"))
    token = os.environ.get(cfg.get("token_env", "INFLUXDB_TOKEN"))

    if not token:
        return {"error": f"InfluxDB token env var '{cfg.get('token_env', 'INFLUXDB_TOKEN')}' not set"}
    if not org:
        return {"error": f"InfluxDB org env var '{cfg.get('org_env', 'INFLUXDB_ORG')}' not set"}

    try:
        resp = httpx.post(
            f"{url}/api/v2/query",
            params={"org": org},
            headers={
                "Authorization": f"Token {token}",
                "Content-Type": "application/vnd.flux",
                "Accept": "application/csv",
            },
            content=flux,
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return {"error": f"InfluxDB query failed: {e}"}

    import csv
    import io

    text = resp.text or ""
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if r and not all(c == "" for c in r)]

    if not rows:
        return {"bucket": bucket, "row_count": 0, "columns": [], "records": []}

    header_idx = 0
    for i, row in enumerate(rows):
        if row and row[0] == "" and len(row) > 1 and row[1] == "result":
            header_idx = i
            break
    header = rows[header_idx]
    data_rows = rows[header_idx + 1 :]

    cap = 500
    truncated = len(data_rows) > cap
    columns = [c for c in header if c]
    records = [
        {k: v for k, v in zip(header, r) if k}
        for r in data_rows[:cap]
    ]

    out: dict[str, Any] = {
        "bucket": bucket,
        "row_count": len(records),
        "columns": columns,
        "records": records,
    }
    if truncated:
        out["truncated_at"] = cap
    return out
