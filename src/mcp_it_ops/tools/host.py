"""Host-side tools: system health, NVMe SMART, container status, backup status.

These tools query the local host the MCP server runs on — /proc, smartctl,
docker ps, and the niborserver backup log. None of them hit the network.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


def get_system_health() -> dict[str, Any]:
    """Report local system health: disk, memory, load, uptime, container count.

    Reads from /proc and shells out to df, uptime, docker ps. Designed for the
    host the MCP server runs on.
    """
    result: dict[str, Any] = {}

    try:
        result["hostname"] = Path("/etc/hostname").read_text().strip()
    except OSError:
        result["hostname"] = os.uname().nodename

    try:
        with open("/proc/uptime") as f:
            uptime_s = float(f.read().split()[0])
        result["uptime_seconds"] = int(uptime_s)
    except (OSError, ValueError):
        result["uptime_seconds"] = None

    try:
        with open("/proc/loadavg") as f:
            result["load_1min"] = float(f.read().split()[0])
    except (OSError, ValueError):
        result["load_1min"] = None

    try:
        meminfo: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, val = line.split(":", 1)
                meminfo[key] = int(val.strip().split()[0])
        total = meminfo.get("MemTotal", 0)
        avail = meminfo.get("MemAvailable", 0)
        result["memory_used_pct"] = round((total - avail) / total * 100, 1) if total else None
    except (OSError, ValueError, KeyError):
        result["memory_used_pct"] = None

    try:
        df_out = subprocess.run(
            ["df", "-P", "/"], capture_output=True, text=True, timeout=5, check=True
        ).stdout
        line = df_out.strip().splitlines()[1]
        used_pct = int(line.split()[4].rstrip("%"))
        result["disk_root_used_pct"] = used_pct
    except (subprocess.SubprocessError, IndexError, ValueError):
        result["disk_root_used_pct"] = None

    if shutil.which("docker"):
        try:
            count = subprocess.run(
                ["docker", "ps", "-q"], capture_output=True, text=True, timeout=5, check=True
            ).stdout.strip().splitlines()
            result["container_count_running"] = len([x for x in count if x])
        except subprocess.SubprocessError:
            result["container_count_running"] = None
    else:
        result["container_count_running"] = None

    return result


def get_container_status() -> dict[str, Any]:
    """Return structured docker-ps output: per-container name, image, state, status, ports, age.

    Shells out to docker ps with a tab-separated format string. Returns a list of containers
    plus a summary dict. Read-only — does not stop/restart anything.

    Returns {"error": "..."} if docker isn't installed or the docker socket is unreachable.
    """
    if not shutil.which("docker"):
        return {"error": "docker binary not found in PATH"}

    fmt = "{{.Names}}\t{{.Image}}\t{{.State}}\t{{.Status}}\t{{.Ports}}\t{{.RunningFor}}"
    try:
        out = subprocess.run(
            ["docker", "ps", "-a", "--format", fmt],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except subprocess.SubprocessError as e:
        return {"error": f"docker ps failed: {e}"}

    containers = []
    for line in out.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        name, image, state, status, ports, age = parts[:6]
        containers.append({
            "name": name,
            "image": image,
            "state": state,
            "status": status,
            "ports": ports if ports else None,
            "age": age,
        })

    summary = {
        "total": len(containers),
        "running": sum(1 for c in containers if c["state"] == "running"),
        "exited":  sum(1 for c in containers if c["state"] == "exited"),
        "other":   sum(1 for c in containers if c["state"] not in ("running", "exited")),
    }
    return {"summary": summary, "containers": containers}


def get_smartd_health(device: str = "/dev/nvme0n1") -> dict[str, Any]:
    """Query SMART health for a storage device via smartctl.

    device: /dev/nvme0n1, /dev/sda, etc. Default is niborserver's NVMe.
    Returns: overall_health, critical_warning, temperature_c, available_spare_pct,
    percentage_used_pct, power_on_hours, unsafe_shutdowns, media_errors.

    Requires sudo (smartctl needs raw device access). Returns {"error": ...} if
    smartctl isn't installed or sudo isn't permitted (the calling user must
    have NOPASSWD sudo for smartctl OR the MCP server must run as root).
    """
    if not shutil.which("smartctl"):
        return {"error": "smartctl not installed"}

    try:
        out = subprocess.run(
            ["sudo", "-n", "smartctl", "-a", device],
            capture_output=True, text=True, timeout=15,
        )
    except subprocess.SubprocessError as e:
        return {"error": f"smartctl failed: {e}"}

    text = out.stdout
    if not text.strip():
        return {"error": f"smartctl produced no output (sudo denied? need NOPASSWD or run as root): {out.stderr.strip() or 'no stderr'}"}

    def grab(pattern: str, cast=str) -> Any:
        m = re.search(pattern, text, re.MULTILINE)
        if not m:
            return None
        try:
            return cast(m.group(1).replace(",", "").strip())
        except (ValueError, AttributeError):
            return None

    return {
        "device": device,
        "overall_health": grab(r"SMART overall-health self-assessment test result:\s+(\S+)"),
        "critical_warning": grab(r"Critical Warning:\s+(\S+)"),
        "temperature_c": grab(r"Temperature:\s+(\d+)", int),
        "available_spare_pct": grab(r"Available Spare:\s+(\d+)%", int),
        "percentage_used_pct": grab(r"Percentage Used:\s+(\d+)%", int),
        "power_on_hours": grab(r"Power On Hours:\s+([\d,]+)", int),
        "unsafe_shutdowns": grab(r"Unsafe Shutdowns:\s+([\d,]+)", int),
        "media_errors": grab(r"Media and Data Integrity Errors:\s+(\d+)", int),
    }


def get_backup_status() -> dict[str, Any]:
    """Report on the niborserver backup pipeline's last run.

    Reads /var/log/niborserver-backup.log and reports: last_run_started,
    last_run_completed, last_run_duration_seconds, last_run_size, last_run_succeeded.

    Returns {"error": ...} if the log doesn't exist (backup not yet run).
    """
    log_path = "/var/log/niborserver-backup.log"
    if not Path(log_path).exists():
        return {"error": f"backup log not found at {log_path} — backup may not have run yet"}

    try:
        with open(log_path) as f:
            lines = f.readlines()
    except OSError as e:
        return {"error": f"could not read backup log: {e}"}

    if not lines:
        return {"error": "backup log is empty"}

    started_line = None
    completed_line = None
    size = None
    succeeded = False

    for line in reversed(lines):
        if completed_line is None and ("complete" in line or "FAIL" in line):
            completed_line = line.strip()
            succeeded = "complete" in line and "FAIL" not in line
            m = re.search(r"complete.*?\u2014\s*(\S+)", line)
            if m:
                size = m.group(1)
        if started_line is None and "starting" in line:
            started_line = line.strip()
        if started_line and completed_line:
            break

    def parse_ts(line: str | None) -> str | None:
        if not line:
            return None
        m = re.match(r"\[(\d{2}:\d{2}:\d{2})\]", line)
        return m.group(1) if m else None

    duration_seconds = None
    if started_line and completed_line:
        try:
            t1 = datetime.strptime(parse_ts(started_line), "%H:%M:%S")
            t2 = datetime.strptime(parse_ts(completed_line), "%H:%M:%S")
            duration_seconds = int((t2 - t1).total_seconds())
        except (ValueError, TypeError):
            pass

    return {
        "last_run_started_at": parse_ts(started_line),
        "last_run_completed_at": parse_ts(completed_line),
        "last_run_duration_seconds": duration_seconds,
        "last_run_size": size,
        "last_run_succeeded": succeeded,
        "log_path": log_path,
        "log_total_lines": len(lines),
    }
