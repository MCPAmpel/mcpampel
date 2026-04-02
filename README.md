# MCPAmpel - MCP Security Scanner

[![MCPAmpel](https://mcpampel.com/badge/MCPAmpel/mcpampel.svg)](https://mcpampel.com/repo/MCPAmpel/mcpampel)

Scan your installed MCP servers for security vulnerabilities, directly from your AI agent.

MCPAmpel discovers MCP servers from your Claude Code, Cursor, Windsurf, or Gemini CLI configuration, submits them to 16 scanning engines, and returns an aggregated trust score with detailed findings.

50 API calls/day included.

## Quick Start

```bash
uvx mcpampel
```

## Configuration

### Claude Code / Claude Desktop

Add to `~/.claude/settings.json` or `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mcpampel": {
      "command": "uvx",
      "args": ["mcpampel"],
      "env": {
        "MCPAMPEL_API_KEY": "your_key_here"
      }
    }
  }
}
```

### Cursor

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "mcpampel": {
      "command": "uvx",
      "args": ["mcpampel"],
      "env": {
        "MCPAMPEL_API_KEY": "your_key_here"
      }
    }
  }
}
```

### Windsurf

Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "mcpampel": {
      "command": "uvx",
      "args": ["mcpampel"],
      "env": {
        "MCPAMPEL_API_KEY": "your_key_here"
      }
    }
  }
}
```

### Gemini CLI

Add to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "mcpampel": {
      "command": "uvx",
      "args": ["mcpampel"],
      "env": {
        "MCPAMPEL_API_KEY": "your_key_here"
      }
    }
  }
}
```

### Getting an API Key

Register for free at [mcpampel.com](https://mcpampel.com).

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MCPAMPEL_API_KEY` | Yes | - | Your API key (free at mcpampel.com) |
| `MCPAMPEL_BASE_URL` | No | `https://mcpampel.com` | API base URL |

## Tools

### `scan_my_servers`

Discovers all MCP servers from your editor config and scans them with 16 engines. Returns a summary table with trust scores. No input needed.

### `scan_url`

Scan a single GitHub, GitLab, npm, or PyPI URL. Returns trust score, engine breakdown, and findings.

| Parameter | Type | Required |
|-----------|------|----------|
| `url` | string | Yes |

### `check_status`

Show your daily quota usage and remaining scans.

### `get_scan_results`

Get detailed results for a specific scan by ID. Use after `scan_my_servers` or `scan_url` to drill into findings.

| Parameter | Type | Required |
|-----------|------|----------|
| `scan_id` | string | Yes |

## Development

```bash
cd mcp-plugin
uv sync
uv run pytest
```

## License

Apache License 2.0

---

[mcpampel.com](https://mcpampel.com)
