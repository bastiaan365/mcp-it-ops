"""mcp-it-ops — MCP server exposing homelab + IT-ops tools to Claude.

Stdio transport. Tools are defined as plain functions in the tools/ subpackage
and registered with FastMCP here. Run via:
    mcp-it-ops              # uses installed entry point
or:
    python -m mcp_it_ops.server
or for development with the MCP inspector:
    mcp dev src/mcp_it_ops/server.py
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .tools.freqtrade import get_freqtrade_bot_status
from .tools.host import (
    get_backup_status,
    get_container_status,
    get_smartd_health,
    get_system_health,
)
from .tools.observability import (
    get_grafana_alert_state,
    query_influxdb_flux,
    query_loki_logs,
)

mcp = FastMCP("mcp-it-ops")

mcp.tool()(get_system_health)
mcp.tool()(get_grafana_alert_state)
mcp.tool()(get_freqtrade_bot_status)
mcp.tool()(get_container_status)
mcp.tool()(query_loki_logs)
mcp.tool()(get_smartd_health)
mcp.tool()(get_backup_status)
mcp.tool()(query_influxdb_flux)


def main() -> None:
    """Run the MCP server over stdio (Claude Desktop / mcp dev mode)."""
    mcp.run()


if __name__ == "__main__":
    main()
