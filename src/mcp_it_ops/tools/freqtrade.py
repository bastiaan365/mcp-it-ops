"""Freqtrade tool: query a bot's REST API for trading state."""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..config import CONFIG


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
