"""Tests for get_smartd_health."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from mcp_it_ops.server import get_smartd_health


SAMPLE_SMARTCTL_NVME = """smartctl 7.4 2023-08-01 r5530 [aarch64-linux-6.8.0-1051-raspi]
=== START OF SMART DATA SECTION ===
SMART overall-health self-assessment test result: PASSED

SMART/Health Information (NVMe Log 0x02)
Critical Warning:                   0x00
Temperature:                        33 Celsius
Available Spare:                    100%
Available Spare Threshold:          10%
Percentage Used:                    2%
Data Units Read:                    1,234,567 [632 GB]
Data Units Written:                 7,890,123 [4.04 TB]
Power Cycles:                       2,584
Power On Hours:                     1,956
Unsafe Shutdowns:                   326
Media and Data Integrity Errors:    0
"""


def test_smartd_health_happy_path(monkeypatch):
    monkeypatch.setattr("mcp_it_ops.tools.host.shutil.which", lambda cmd: "/usr/sbin/smartctl")
    monkeypatch.setattr(
        "mcp_it_ops.tools.host.subprocess.run",
        lambda *a, **k: MagicMock(stdout=SAMPLE_SMARTCTL_NVME, stderr=""),
    )
    result = get_smartd_health("/dev/nvme0n1")
    assert result["device"] == "/dev/nvme0n1"
    assert result["overall_health"] == "PASSED"
    assert result["critical_warning"] == "0x00"
    assert result["temperature_c"] == 33
    assert result["available_spare_pct"] == 100
    assert result["percentage_used_pct"] == 2
    assert result["power_on_hours"] == 1956
    assert result["unsafe_shutdowns"] == 326
    assert result["media_errors"] == 0


def test_smartd_health_no_smartctl(monkeypatch):
    monkeypatch.setattr("mcp_it_ops.tools.host.shutil.which", lambda cmd: None)
    result = get_smartd_health()
    assert "error" in result
    assert "smartctl not installed" in result["error"]


def test_smartd_health_sudo_denied(monkeypatch):
    monkeypatch.setattr("mcp_it_ops.tools.host.shutil.which", lambda cmd: "/usr/sbin/smartctl")
    monkeypatch.setattr(
        "mcp_it_ops.tools.host.subprocess.run",
        lambda *a, **k: MagicMock(stdout="", stderr="sudo: a password is required"),
    )
    result = get_smartd_health()
    assert "error" in result
    assert "sudo" in result["error"].lower()


def test_smartd_health_subprocess_failure(monkeypatch):
    monkeypatch.setattr("mcp_it_ops.tools.host.shutil.which", lambda cmd: "/usr/sbin/smartctl")

    def fake_run(*a, **k):
        raise subprocess.SubprocessError("simulated failure")

    monkeypatch.setattr("mcp_it_ops.tools.host.subprocess.run", fake_run)
    result = get_smartd_health()
    assert "error" in result
    assert "smartctl failed" in result["error"]


def test_smartd_health_partial_output(monkeypatch):
    """Some smartctl output formats may omit some fields → those become None, not crash."""
    monkeypatch.setattr("mcp_it_ops.tools.host.shutil.which", lambda cmd: "/usr/sbin/smartctl")
    minimal = "SMART overall-health self-assessment test result: PASSED\nTemperature: 25 Celsius\n"
    monkeypatch.setattr(
        "mcp_it_ops.tools.host.subprocess.run",
        lambda *a, **k: MagicMock(stdout=minimal, stderr=""),
    )
    result = get_smartd_health()
    assert result["overall_health"] == "PASSED"
    assert result["temperature_c"] == 25
    assert result["available_spare_pct"] is None
    assert result["media_errors"] is None
