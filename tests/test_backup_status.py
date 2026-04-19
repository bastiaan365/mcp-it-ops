"""Tests for get_backup_status."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from mcp_it_ops.server import get_backup_status


SAMPLE_BACKUP_LOG_SUCCESS = """[03:01:00] === niborserver backup 2026-04-19 starting (encrypted) ===
[03:01:00] [1/5] InfluxDB backup...
[03:02:30] [2/5] Grafana DB copy + encrypt...
[03:02:31] [3/5] Monitoring stack tar+encrypt...
[03:02:32] [4/5] Freqtrade tar+encrypt...
[03:03:15] [5/5] Home/scripts/claude tar+encrypt...
[03:03:15] Staging total: 1.1G (encrypted)
[03:03:15] Rsync to root@openclaw:/var/backups/niborserver/2026-04-19/...
[03:05:42] Prune old (keeping last 7)...
[03:05:42] === niborserver backup 2026-04-19 complete (encrypted) — 1.1G ===
"""

SAMPLE_BACKUP_LOG_FAILURE = """[03:01:00] === niborserver backup 2026-04-19 starting (encrypted) ===
[03:01:00] [1/5] InfluxDB backup...
FAIL: influx backup command failed
"""


def _patch_log(monkeypatch, content: str | None, exists: bool = True):
    if exists:
        monkeypatch.setattr(Path, "exists", lambda self: True)
        if content is None:
            content = ""
        m = mock_open(read_data=content)
        monkeypatch.setattr("builtins.open", m)
    else:
        monkeypatch.setattr(Path, "exists", lambda self: False)


def test_backup_status_happy_path(monkeypatch):
    _patch_log(monkeypatch, SAMPLE_BACKUP_LOG_SUCCESS)
    result = get_backup_status()
    assert result["last_run_succeeded"] is True
    assert result["last_run_started_at"] == "03:01:00"
    assert result["last_run_completed_at"] == "03:05:42"
    assert result["last_run_duration_seconds"] == 282  # 4m42s
    assert result["last_run_size"] == "1.1G"
    assert result["log_total_lines"] > 0


def test_backup_status_failure(monkeypatch):
    _patch_log(monkeypatch, SAMPLE_BACKUP_LOG_FAILURE)
    result = get_backup_status()
    assert result["last_run_succeeded"] is False
    assert result["last_run_started_at"] == "03:01:00"


def test_backup_status_log_missing(monkeypatch):
    _patch_log(monkeypatch, None, exists=False)
    result = get_backup_status()
    assert "error" in result
    assert "not found" in result["error"]


def test_backup_status_log_empty(monkeypatch):
    _patch_log(monkeypatch, "")
    result = get_backup_status()
    assert "error" in result
    assert "empty" in result["error"]
