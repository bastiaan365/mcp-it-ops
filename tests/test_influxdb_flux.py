"""Tests for query_influxdb_flux."""

from __future__ import annotations

import httpx
import pytest
import respx

from mcp_it_ops.server import query_influxdb_flux


SAMPLE_FLUX_CSV = """,result,table,_start,_stop,_time,_value,_field,_measurement,host
,_result,0,2026-04-19T12:00:00Z,2026-04-19T13:00:00Z,2026-04-19T12:30:00Z,42.5,temperature,sensors,niborserver
,_result,0,2026-04-19T12:00:00Z,2026-04-19T13:00:00Z,2026-04-19T12:31:00Z,43.1,temperature,sensors,niborserver
,_result,0,2026-04-19T12:00:00Z,2026-04-19T13:00:00Z,2026-04-19T12:32:00Z,42.9,temperature,sensors,niborserver
"""


@pytest.fixture
def influx_env(monkeypatch):
    monkeypatch.setenv("INFLUXDB_TOKEN", "test-token")
    monkeypatch.setenv("INFLUXDB_ORG", "test-org")


@respx.mock
def test_influxdb_flux_happy_path(influx_env):
    route = respx.post("http://localhost:8086/api/v2/query").mock(
        return_value=httpx.Response(200, text=SAMPLE_FLUX_CSV)
    )
    result = query_influxdb_flux(
        'from(bucket:"monitoring") |> range(start:-1h)',
        bucket="monitoring",
    )
    assert result["bucket"] == "monitoring"
    assert result["row_count"] == 3
    assert "_value" in result["columns"]
    assert result["records"][0]["_value"] == "42.5"
    assert result["records"][0]["host"] == "niborserver"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Token test-token"
    assert "org=test-org" in str(request.url)
    assert request.headers["Content-Type"] == "application/vnd.flux"


def test_influxdb_flux_missing_token(monkeypatch):
    monkeypatch.delenv("INFLUXDB_TOKEN", raising=False)
    monkeypatch.setenv("INFLUXDB_ORG", "test-org")
    result = query_influxdb_flux('from(bucket:"x") |> range(start:-1h)')
    assert "error" in result
    assert "INFLUXDB_TOKEN" in result["error"]


def test_influxdb_flux_missing_org(monkeypatch):
    monkeypatch.setenv("INFLUXDB_TOKEN", "test-token")
    monkeypatch.delenv("INFLUXDB_ORG", raising=False)
    result = query_influxdb_flux('from(bucket:"x") |> range(start:-1h)')
    assert "error" in result
    assert "INFLUXDB_ORG" in result["error"]


@respx.mock
def test_influxdb_flux_unreachable(influx_env):
    respx.post("http://localhost:8086/api/v2/query").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    result = query_influxdb_flux('from(bucket:"x") |> range(start:-1h)')
    assert "error" in result
    assert "InfluxDB query failed" in result["error"]


@respx.mock
def test_influxdb_flux_syntax_error(influx_env):
    respx.post("http://localhost:8086/api/v2/query").mock(
        return_value=httpx.Response(400, text='{"code":"invalid","message":"syntax error"}')
    )
    result = query_influxdb_flux("not valid flux")
    assert "error" in result
    assert "InfluxDB query failed" in result["error"]


@respx.mock
def test_influxdb_flux_empty_result(influx_env):
    respx.post("http://localhost:8086/api/v2/query").mock(
        return_value=httpx.Response(200, text="")
    )
    result = query_influxdb_flux('from(bucket:"empty") |> range(start:-1h)')
    assert result["row_count"] == 0
    assert result["records"] == []


@respx.mock
def test_influxdb_flux_truncates_large_results(influx_env):
    """Results > 500 rows should be capped with truncated_at: 500."""
    header = ',result,table,_value\n'
    rows = "".join(f',_result,0,{i}\n' for i in range(750))
    respx.post("http://localhost:8086/api/v2/query").mock(
        return_value=httpx.Response(200, text=header + rows)
    )
    result = query_influxdb_flux('from(bucket:"big") |> range(start:-1h)')
    assert result["row_count"] == 500
    assert result.get("truncated_at") == 500
