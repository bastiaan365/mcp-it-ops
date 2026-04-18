"""Tests for query_loki_logs."""

from __future__ import annotations

import httpx
import pytest
import respx

from mcp_it_ops.server import query_loki_logs


SAMPLE_LOKI_RESPONSE = {
    "status": "success",
    "data": {
        "resultType": "streams",
        "result": [
            {
                "stream": {"container": "grafana", "level": "info"},
                "values": [
                    ["1745000000000000000", "msg=\"server started\""],
                    ["1745000010000000000", "msg=\"client connected\""],
                ],
            },
            {
                "stream": {"container": "loki", "level": "warn"},
                "values": [
                    ["1745000020000000000", "msg=\"slow query\""],
                ],
            },
        ],
    },
}


@respx.mock
def test_loki_logs_happy_path():
    respx.get("http://localhost:3100/loki/api/v1/query_range").mock(
        return_value=httpx.Response(200, json=SAMPLE_LOKI_RESPONSE)
    )
    result = query_loki_logs('{container="grafana"}')
    assert result["query"] == '{container="grafana"}'
    assert result["total_streams"] == 2
    assert result["total_lines"] == 3
    assert result["streams"][0]["labels"]["container"] == "grafana"
    assert result["streams"][0]["lines"][0]["line"] == 'msg="server started"'
    assert result["streams"][0]["line_count"] == 2


@respx.mock
def test_loki_logs_passes_since_and_limit_params():
    """Ensure custom since + limit are forwarded to Loki, with limit clamped."""
    route = respx.get("http://localhost:3100/loki/api/v1/query_range").mock(
        return_value=httpx.Response(200, json={"data": {"result": []}})
    )
    query_loki_logs("{job=\"test\"}", since="30m", limit=50)
    request = route.calls.last.request
    assert "since=30m" in str(request.url)
    assert "limit=50" in str(request.url)


@respx.mock
def test_loki_logs_clamps_limit():
    """limit > 1000 should be clamped to 1000."""
    route = respx.get("http://localhost:3100/loki/api/v1/query_range").mock(
        return_value=httpx.Response(200, json={"data": {"result": []}})
    )
    query_loki_logs("{job=\"test\"}", limit=99999)
    assert "limit=1000" in str(route.calls.last.request.url)


@respx.mock
def test_loki_logs_unreachable():
    respx.get("http://localhost:3100/loki/api/v1/query_range").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    result = query_loki_logs('{container="grafana"}')
    assert "error" in result
    assert "Loki query failed" in result["error"]


@respx.mock
def test_loki_logs_empty_result():
    respx.get("http://localhost:3100/loki/api/v1/query_range").mock(
        return_value=httpx.Response(200, json={"data": {"result": []}})
    )
    result = query_loki_logs('{container="nonexistent"}')
    assert result["total_streams"] == 0
    assert result["total_lines"] == 0
    assert result["streams"] == []
