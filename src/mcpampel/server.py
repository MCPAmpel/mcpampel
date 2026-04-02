"""MCPAmpel MCP server - security scanner for installed MCP servers.

Scans MCP servers from your Claude Code, Cursor, Windsurf, or Gemini CLI
configuration against 16 detection engines. Returns trust scores and findings.

Tools:
- scan_my_servers: Discover and scan all installed MCP servers
- scan_url: Scan a single URL
- check_status: Show usage and remaining quota
- get_scan_results: Get full results for a specific scan
"""
from __future__ import annotations

import argparse
import asyncio
import os

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mcpampel.config_reader import discover_mcp_servers, get_all_scannable_urls
from mcpampel.scanner import ScannerClient

server = Server("mcpampel")


def _format_scan_summary(scan: dict) -> str:
    """Format a scan result as a readable summary line."""
    status = scan.get("status", "unknown")
    score = scan.get("trust_score")
    url = scan.get("url", "?")
    score_str = f"{score:.1f}/10" if score is not None else "pending"
    flagged = scan.get("engines_flagged", 0)
    total = scan.get("engines_total", 0)
    return f"  {url}: {score_str} ({flagged}/{total} engines flagged) [{status}]"


def _format_detailed_results(scan: dict) -> str:
    """Format full scan results with engine details."""
    lines = [
        f"URL: {scan.get('url', '?')}",
        f"Status: {scan.get('status', 'unknown')}",
        f"Trust Score: {scan.get('trust_score', 'N/A')}",
        f"Engines: {scan.get('engines_flagged', 0)} flagged / {scan.get('engines_total', 0)} total",
        "",
    ]

    for er in scan.get("engine_results", []):
        safe = "SAFE" if er.get("is_safe") else "FLAGGED"
        severity = er.get("severity", "unknown")
        lines.append(f"  [{safe}] {er.get('engine_name', '?')} - severity: {severity}")
        if er.get("findings_count", 0) > 0:
            for finding in (er.get("findings") or [])[:5]:
                desc = finding.get("description", finding.get("rule", "?"))
                lines.append(f"    - {desc}")
            remaining = er.get("findings_count", 0) - 5
            if remaining > 0:
                lines.append(f"    ... and {remaining} more findings")

    return "\n".join(lines)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="scan_my_servers",
            description=(
                "Discover all MCP servers installed in your editor/agent config "
                "(Claude Code, Cursor, Windsurf, Gemini CLI) and scan them for "
                "security issues with 16 engines. Returns trust scores."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="scan_url",
            description="Scan a single URL (GitHub, GitLab, npm, or PyPI) for security issues with 16 engines.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to scan (GitHub, GitLab, npm, or PyPI)"},
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="check_status",
            description="Show your daily quota usage and remaining scans.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_scan_results",
            description="Get full detailed results for a specific scan by its ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "scan_id": {"type": "string", "description": "UUID of the scan"},
                },
                "required": ["scan_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        client = ScannerClient()
    except ValueError as e:
        return [TextContent(type="text", text=str(e))]

    async with client:
        if name == "scan_my_servers":
            return await _handle_scan_my_servers(client)
        elif name == "scan_url":
            return await _handle_scan_url(client, arguments)
        elif name == "check_status":
            return await _handle_check_status(client)
        elif name == "get_scan_results":
            return await _handle_get_scan_results(client, arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def _handle_scan_my_servers(client: ScannerClient) -> list[TextContent]:
    servers = discover_mcp_servers()
    if not servers:
        return [TextContent(
            type="text",
            text="No MCP servers found in your configuration.",
        )]

    urls = get_all_scannable_urls()
    if not urls:
        names = [s["name"] for s in servers]
        return [TextContent(
            type="text",
            text=(
                f"Found {len(servers)} MCP servers ({', '.join(names)}) but could not "
                "extract any scannable URLs from their configurations."
            ),
        )]

    # Submit batch scan
    try:
        result = await client.scan_urls(urls)
    except Exception as e:
        return [TextContent(type="text", text=f"Scan request failed: {e}")]

    # Poll all pending scans in parallel
    async def _poll_one(scan: dict) -> dict:
        scan_id = scan.get("id")
        if scan_id and scan.get("status") not in ("completed", "failed"):
            try:
                return await client.poll_scan(scan_id)
            except Exception:
                pass  # use the original scan data
        return scan

    completed_scans = await asyncio.gather(
        *(_poll_one(s) for s in result.get("scans", []))
    )

    lines = [f"Scanned {len(urls)} URLs from {len(servers)} installed MCP servers:", ""]

    # Map URLs back to server names for context
    url_to_server: dict[str, str] = {}
    for s in servers:
        for u in s["urls"]:
            url_to_server[u] = s["name"]

    for scan in completed_scans:
        server_name = url_to_server.get(scan.get("url", ""), "?")
        lines.append(f"  [{server_name}] {_format_scan_summary(scan).strip()}")

    for err in result.get("errors", []):
        lines.append(f"  ERROR: {err.get('url', '?')}: {err.get('error', 'unknown')}")

    lines.append("")
    lines.append("Use get_scan_results with a scan ID for detailed findings.")

    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_scan_url(client: ScannerClient, arguments: dict) -> list[TextContent]:
    url = arguments.get("url", "").strip()
    if not url:
        return [TextContent(type="text", text="Error: url parameter is required")]

    try:
        result = await client.scan_urls([url])
    except Exception as e:
        return [TextContent(type="text", text=f"Scan request failed: {e}")]

    scans = result.get("scans", [])
    errors = result.get("errors", [])

    if errors:
        return [TextContent(type="text", text=f"Error: {errors[0].get('error', 'unknown')}")]

    if not scans:
        return [TextContent(type="text", text="No scan results returned.")]

    scan = scans[0]
    scan_id = scan.get("id")
    if scan_id and scan.get("status") not in ("completed", "failed"):
        try:
            scan = await client.poll_scan(scan_id)
        except Exception:
            pass  # use the original scan data

    return [TextContent(type="text", text=_format_detailed_results(scan))]


async def _handle_check_status(client: ScannerClient) -> list[TextContent]:
    try:
        sub = await client.get_subscription()
    except Exception as e:
        return [TextContent(type="text", text=f"Failed to get subscription info: {e}")]

    limit = sub.get("daily_limit", "?")
    limit_str = "unlimited" if limit == -1 else str(limit)
    remaining = sub.get("daily_remaining", "?")
    remaining_str = "unlimited" if remaining == -1 else str(remaining)
    lines = [
        "MCPAmpel API Status",
        f"  Daily limit: {limit_str} calls",
        f"  Used today: {sub.get('daily_used', '?')}",
        f"  Remaining: {remaining_str}",
        f"  Active: {'yes' if sub.get('is_active') else 'no'}",
    ]
    return [TextContent(type="text", text="\n".join(lines))]


async def _handle_get_scan_results(client: ScannerClient, arguments: dict) -> list[TextContent]:
    scan_id = arguments.get("scan_id", "").strip()
    if not scan_id:
        return [TextContent(type="text", text="Error: scan_id parameter is required")]

    try:
        scan = await client.get_scan(scan_id)
    except Exception as e:
        return [TextContent(type="text", text=f"Failed to get scan results: {e}")]

    return [TextContent(type="text", text=_format_detailed_results(scan))]


def main():
    """Entry point for the MCP server."""
    parser = argparse.ArgumentParser(description="MCPAmpel MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default=os.environ.get("MCPAMPEL_TRANSPORT") or os.environ.get("MCPTOTAL_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    if args.transport == "sse":
        asyncio.run(_run_sse(args.host, args.port))
    else:
        asyncio.run(_run_stdio())


async def _run_stdio():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def _run_sse(host: str, port: int):
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    from starlette.responses import Response

    import uvicorn

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())
        return Response()

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    config = uvicorn.Config(app, host=host, port=port)
    await uvicorn.Server(config).serve()


if __name__ == "__main__":
    main()
