"""Tests for get_container_status."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcp_it_ops.server import get_container_status


@pytest.fixture
def mock_docker(monkeypatch):
    """docker binary present + a synthetic docker-ps output."""
    monkeypatch.setattr("mcp_it_ops.server.shutil.which", lambda cmd: "/usr/bin/docker" if cmd == "docker" else None)

    sample_output = (
        "grafana\tgrafana/grafana:latest\trunning\tUp 3 hours\t0.0.0.0:3000->3000/tcp\t3 hours ago\n"
        "old-test\talpine:3\texited\tExited (0) 2 days ago\t\t2 days ago\n"
        "loki\tgrafana/loki:2.9.10\trunning\tUp 1 day (healthy)\t0.0.0.0:3100->3100/tcp\t1 day ago\n"
    )
    monkeypatch.setattr(
        "mcp_it_ops.server.subprocess.run",
        lambda *a, **k: MagicMock(stdout=sample_output),
    )


def test_container_status_happy_path(mock_docker):
    result = get_container_status()
    assert result["summary"] == {"total": 3, "running": 2, "exited": 1, "other": 0}
    assert len(result["containers"]) == 3
    assert result["containers"][0]["name"] == "grafana"
    assert result["containers"][0]["image"] == "grafana/grafana:latest"
    assert result["containers"][0]["state"] == "running"
    assert result["containers"][1]["state"] == "exited"
    assert result["containers"][1]["ports"] is None  # empty ports → None


def test_container_status_no_docker(monkeypatch):
    monkeypatch.setattr("mcp_it_ops.server.shutil.which", lambda cmd: None)
    result = get_container_status()
    assert "error" in result
    assert "docker binary not found" in result["error"]


def test_container_status_docker_failure(monkeypatch):
    """Docker installed but daemon unreachable → error response."""
    import subprocess
    monkeypatch.setattr("mcp_it_ops.server.shutil.which", lambda cmd: "/usr/bin/docker")

    def fake_run(*a, **k):
        raise subprocess.CalledProcessError(1, "docker ps")

    monkeypatch.setattr("mcp_it_ops.server.subprocess.run", fake_run)
    result = get_container_status()
    assert "error" in result
    assert "docker ps failed" in result["error"]
