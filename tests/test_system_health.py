"""Tests for get_system_health.

Mocks /proc reads + subprocess (df, docker ps) so the test is host-independent
and can run on the GitHub Actions ubuntu-latest runner without depending on
the runner's actual disk/memory/container state.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, mock_open

import pytest

from mcp_it_ops.server import get_system_health


@pytest.fixture
def mock_system(monkeypatch):
    """Patch all the OS reads so the function returns a deterministic result."""
    proc_files = {
        "/proc/uptime": "12345.67 9876.54\n",
        "/proc/loadavg": "0.25 0.30 0.35 1/123 4567\n",
        "/proc/meminfo": (
            "MemTotal:        8000000 kB\n"
            "MemFree:         3000000 kB\n"
            "MemAvailable:    4000000 kB\n"
            "Buffers:           50000 kB\n"
        ),
    }

    builtin_open = open

    def fake_open(path, *args, **kwargs):
        path = str(path)
        if path in proc_files:
            return mock_open(read_data=proc_files[path])(path, *args, **kwargs)
        return builtin_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)
    monkeypatch.setattr(
        "mcp_it_ops.server.Path",
        lambda p: MagicMock(read_text=lambda: "test-host" if str(p) == "/etc/hostname" else None),
    )

    df_result = MagicMock(stdout="Filesystem 1024-blocks Used Available Capacity Mounted\n/dev/x  100 5  95  5% /\n")
    docker_result = MagicMock(stdout="abc\ndef\nghi\n")

    def fake_subprocess_run(args, *_, **__):
        if args[0] == "df":
            return df_result
        if args[0] == "docker":
            return docker_result
        raise ValueError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr("mcp_it_ops.server.subprocess.run", fake_subprocess_run)
    monkeypatch.setattr("mcp_it_ops.server.shutil.which", lambda cmd: "/usr/bin/docker" if cmd == "docker" else None)


def test_get_system_health_happy_path(mock_system):
    """All sources happy → all fields populated correctly."""
    result = get_system_health()
    assert result["hostname"] == "test-host"
    assert result["uptime_seconds"] == 12345
    assert result["load_1min"] == 0.25
    # MemTotal=8M, MemAvailable=4M → 50% used
    assert result["memory_used_pct"] == 50.0
    assert result["disk_root_used_pct"] == 5
    assert result["container_count_running"] == 3


def test_get_system_health_returns_all_expected_keys(mock_system):
    """Public contract: every documented key is in the response."""
    result = get_system_health()
    expected = {
        "hostname", "uptime_seconds", "load_1min",
        "memory_used_pct", "disk_root_used_pct", "container_count_running",
    }
    assert set(result.keys()) == expected


def test_get_system_health_handles_missing_docker(monkeypatch, mock_system):
    """If docker isn't installed, container_count_running is None — no crash."""
    monkeypatch.setattr("mcp_it_ops.server.shutil.which", lambda cmd: None)
    result = get_system_health()
    assert result["container_count_running"] is None
    assert result["disk_root_used_pct"] == 5


def test_get_system_health_handles_subprocess_error(monkeypatch, mock_system):
    """If df fails, disk_root_used_pct is None — other fields still populate."""
    import subprocess

    def fake_run(args, *_, **__):
        if args[0] == "df":
            raise subprocess.SubprocessError("simulated df failure")
        return MagicMock(stdout="abc\n")

    monkeypatch.setattr("mcp_it_ops.server.subprocess.run", fake_run)
    result = get_system_health()
    assert result["disk_root_used_pct"] is None
    # Other fields still populate from /proc reads
    assert result["uptime_seconds"] == 12345
    assert result["memory_used_pct"] == 50.0
