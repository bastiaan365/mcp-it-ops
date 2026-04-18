"""Tests for get_grafana_alert_state.

Uses respx to mock the Grafana API so tests run without a real Grafana server.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from mcp_it_ops.server import get_grafana_alert_state


SAMPLE_RULES_RESPONSE = {
    "status": "success",
    "data": {
        "groups": [
            {
                "name": "homelab",
                "file": "niborserver-alerts",
                "rules": [
                    {
                        "name": "disk usage > 90%",
                        "state": "inactive",
                        "health": "ok",
                        "lastEvaluation": "2026-04-19T08:00:00Z",
                        "annotations": {"summary": "disk full"},
                    },
                    {
                        "name": "container restart loop",
                        "state": "firing",
                        "health": "ok",
                        "lastEvaluation": "2026-04-19T08:00:00Z",
                        "annotations": {},
                    },
                    {
                        "name": "broken-rule",
                        "state": "error",
                        "health": "err",
                        "lastEvaluation": "2026-04-19T08:00:00Z",
                        "annotations": {},
                    },
                ],
            }
        ]
    },
}


@respx.mock
def test_grafana_alerts_happy_path(monkeypatch):
    """Real-shaped response → grouped by state with correct counts."""
    monkeypatch.setenv("GRAFANA_PASSWORD", "test-pw")
    respx.get("http://localhost:3000/api/prometheus/grafana/api/v1/rules").mock(
        return_value=httpx.Response(200, json=SAMPLE_RULES_RESPONSE)
    )

    result = get_grafana_alert_state()
    assert "summary" in result
    assert result["summary"] == {"inactive": 1, "firing": 1, "error": 1}
    assert "alerts" in result
    assert result["alerts"]["firing"][0]["name"] == "container restart loop"
    assert result["alerts"]["firing"][0]["folder"] == "niborserver-alerts"


def test_grafana_alerts_missing_password(monkeypatch):
    """No password env var → returns {error: ...} rather than crashing."""
    monkeypatch.delenv("GRAFANA_PASSWORD", raising=False)
    result = get_grafana_alert_state()
    assert "error" in result
    assert "GRAFANA_PASSWORD" in result["error"]


@respx.mock
def test_grafana_alerts_http_error(monkeypatch):
    """5xx response → returns {error: ...} rather than raising."""
    monkeypatch.setenv("GRAFANA_PASSWORD", "test-pw")
    respx.get("http://localhost:3000/api/prometheus/grafana/api/v1/rules").mock(
        return_value=httpx.Response(500, text="internal error")
    )

    result = get_grafana_alert_state()
    assert "error" in result
    assert "Grafana API request failed" in result["error"]


@respx.mock
def test_grafana_alerts_empty_rule_list(monkeypatch):
    """No rules → empty summary + alerts dicts (not a crash)."""
    monkeypatch.setenv("GRAFANA_PASSWORD", "test-pw")
    respx.get("http://localhost:3000/api/prometheus/grafana/api/v1/rules").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": {"groups": []}})
    )

    result = get_grafana_alert_state()
    assert result["summary"] == {}
    assert result["alerts"] == {}
