"""Tests for get_freqtrade_bot_status.

Mocks the three freqtrade API endpoints (show_config, profit, status) via respx.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from mcp_it_ops.server import get_freqtrade_bot_status


SHOW_CONFIG_RESPONSE = {
    "dry_run": False,
    "strategy": "TestStrategy",
    "timeframe": "4h",
    "exchange": "kraken",
}

PROFIT_RESPONSE = {
    "closed_trade_count": 3,
    "trade_count": 4,
    "profit_closed_fiat": 42.5,
    "profit_closed_percent": 8.5,
    "profit_all_fiat": 50.0,
    "profit_all_percent": 10.0,
    "winrate": 0.667,
}

STATUS_RESPONSE = [
    {
        "pair": "BTC/EUR",
        "open_date": "2026-04-19 00:00:00",
        "open_rate": 60000.0,
        "current_rate": 61500.0,
        "profit_abs": 7.5,
        "profit_pct": 2.5,
    },
]


@respx.mock
def test_freqtrade_happy_path(monkeypatch):
    """Full pipeline: config + profit + status all OK → structured result."""
    monkeypatch.setenv("FT_STEADY_USER", "u")
    monkeypatch.setenv("FT_STEADY_PASS", "p")
    respx.get("http://localhost:8090/api/v1/show_config").mock(return_value=httpx.Response(200, json=SHOW_CONFIG_RESPONSE))
    respx.get("http://localhost:8090/api/v1/profit").mock(return_value=httpx.Response(200, json=PROFIT_RESPONSE))
    respx.get("http://localhost:8090/api/v1/status").mock(return_value=httpx.Response(200, json=STATUS_RESPONSE))

    result = get_freqtrade_bot_status("steady")

    assert result["bot_name"] == "steady"
    assert result["strategy"] == "TestStrategy"
    assert result["dry_run"] is False
    assert result["closed_trade_count"] == 3
    assert result["open_trade_count"] == 1
    assert result["realised_p_and_l_fiat"] == 42.5
    assert result["total_p_and_l_pct"] == 10.0
    assert result["win_rate"] == 0.667
    assert len(result["open_positions"]) == 1
    assert result["open_positions"][0]["pair"] == "BTC/EUR"


def test_freqtrade_unknown_bot():
    """Unknown bot name → error response with list of configured bots."""
    result = get_freqtrade_bot_status("nonexistent")
    assert "error" in result
    assert "Unknown bot" in result["error"]
    assert "nonexistent" in result["error"]


def test_freqtrade_missing_credentials(monkeypatch):
    """Bot exists but env-var credentials aren't set → error response."""
    monkeypatch.delenv("FT_STEADY_USER", raising=False)
    monkeypatch.delenv("FT_STEADY_PASS", raising=False)
    result = get_freqtrade_bot_status("steady")
    assert "error" in result
    assert "Missing credentials" in result["error"]


@respx.mock
def test_freqtrade_api_down(monkeypatch):
    """Bot configured + creds set but API returns 5xx → error response."""
    monkeypatch.setenv("FT_FUN_USER", "u")
    monkeypatch.setenv("FT_FUN_PASS", "p")
    respx.get("http://localhost:8091/api/v1/show_config").mock(return_value=httpx.Response(503))

    result = get_freqtrade_bot_status("fun")
    assert "error" in result
    assert "fun" in result["error"]


@respx.mock
def test_freqtrade_no_open_positions(monkeypatch):
    """Empty status response → empty open_positions list (not crash)."""
    monkeypatch.setenv("FT_STEADY_USER", "u")
    monkeypatch.setenv("FT_STEADY_PASS", "p")
    respx.get("http://localhost:8090/api/v1/show_config").mock(return_value=httpx.Response(200, json=SHOW_CONFIG_RESPONSE))
    respx.get("http://localhost:8090/api/v1/profit").mock(return_value=httpx.Response(200, json=PROFIT_RESPONSE))
    respx.get("http://localhost:8090/api/v1/status").mock(return_value=httpx.Response(200, json=[]))

    result = get_freqtrade_bot_status("steady")
    assert result["open_positions"] == []
