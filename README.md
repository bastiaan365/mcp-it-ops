# mcp-it-ops

An MCP (Model Context Protocol) server that gives Claude direct access to IT operations tools — Active Directory, Intune, Microsoft 365, network diagnostics, and system health checks.

Built this after spending too much time copy-pasting output between CLI tools and chat windows. With this running, you can ask Claude things like "which users in the Finance OU haven't logged in for 90 days" or "show me the compliance status of devices in the Netherlands" and get actual results without leaving the conversation.

## What it does

Once connected, Claude can:

- **Active Directory** — query users, groups, OUs, check last login, account status, group memberships
- **Intune/Endpoint Manager** — list devices, check compliance, see pending policies, query by user or device
- **Microsoft 365** — service health status, mailbox stats, license usage, group membership
- **DNS/Network** — resolve names, check reachability, trace routes, test port connectivity
- **System Health** — disk usage, running services, Windows event log summary, uptime

## Quickstart

```bash
git clone https://github.com/bastiaan365/mcp-it-ops.git
cd mcp-it-ops
pip install -e .

# Configure credentials (see config section below)
cp config/settings.example.yaml config/settings.yaml
```

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%/Claude/claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "it-ops": {
      "command": "python",
      "args": ["-m", "mcp_it_ops"],
      "cwd": "/path/to/mcp-it-ops"
    }
  }
}
```

Restart Claude Desktop and you'll see the IT ops tools available.

## Available tools

### Active Directory
```
get_ad_user(username)              → User details, last login, group memberships
search_ad_users(filter, ou)        → Find users matching criteria
get_stale_accounts(days=90)        → Users who haven't logged in for N days
get_ad_group_members(group_name)   → All members of a group
get_ou_summary(ou_path)            → User count and status for an OU
```

### Intune
```
get_device_compliance(filter)      → Compliance status for devices
get_user_devices(username)         → All enrolled devices for a user
get_noncompliant_devices()         → Devices failing compliance checks
get_pending_policies(device_id)    → Policies pending on a device
```

### Microsoft 365
```
get_m365_service_health()          → Current service health status
get_license_summary()              → License counts and availability
get_mailbox_stats(username)        → Mailbox size and usage
```

### Network & System
```
resolve_dns(hostname)              → DNS resolution with record details
check_connectivity(host, port)     → TCP connectivity test
get_system_health(hostname)        → Disk, memory, CPU, services
get_event_log_summary(hostname)    → Recent errors/warnings from Event Log
```

## Configuration

`config/settings.yaml`:

```yaml
active_directory:
  domain: corp.example.com
  server: dc01.corp.example.com
  # Uses current Windows credentials by default
  # Or specify service account:
  username_env: AD_USERNAME
  password_env: AD_PASSWORD

intune:
  tenant_id_env: AZURE_TENANT_ID
  client_id_env: AZURE_CLIENT_ID
  client_secret_env: AZURE_CLIENT_SECRET

network:
  timeout: 5
  max_hops: 15
```

Set sensitive values in environment variables, not in the config file.

## Requirements

- Python 3.10+
- `mcp` SDK: `pip install mcp`
- For AD tools: `ldap3` or RSAT with Python bindings (Windows only for full functionality)
- For Intune/M365: Azure app registration with appropriate Microsoft Graph API permissions
- Claude Desktop (or any MCP-compatible client)

## Permissions needed

For read-only operation (recommended default):
- AD: Domain Users + read access to OU
- Intune/M365: Microsoft Graph — `DeviceManagementManagedDevices.Read.All`, `Directory.Read.All`, `ServiceHealth.Read.All`

For write operations (optional, disabled by default):
- Configure `read_only: false` in settings and add write permissions as needed

## Project structure

```
mcp_it_ops/
├── __main__.py          # Server entrypoint
├── server.py            # MCP server setup
├── tools/
│   ├── active_directory.py
│   ├── intune.py
│   ├── m365.py
│   ├── network.py
│   └── system.py
├── auth/
│   └── graph.py         # Microsoft Graph auth
config/
├── settings.example.yaml
tests/
└── ...
```

## Background

I manage a mix of Windows and Linux endpoints and spend a lot of time context-switching between the Graph Explorer, AD tools, and terminal. This started as a personal tool — I got tired of the friction and wanted to just describe what I needed in plain language.

The MCP protocol makes this kind of integration pretty clean. The server handles auth and API calls; Claude handles understanding the intent and formatting results. Works well for the kind of ad-hoc queries that come up constantly in IT ops work.

## Limitations

- AD tools require Windows or a Linux machine with `ldap3` and domain access
- Some Intune queries are slow due to Graph API pagination — use specific filters where possible
- Write operations are intentionally disabled by default — enable explicitly and carefully

## Contributing

PRs welcome, especially for new tools or Microsoft Graph endpoints I haven't covered. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
