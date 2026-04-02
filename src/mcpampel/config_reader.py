"""Read MCP client configurations from multiple editors and agents.

Discovers installed MCP servers and extracts scannable URLs
(GitHub repos, npm packages, PyPI packages) from their command/args/env.
Supports Claude Code, Claude Desktop, Cursor, Windsurf, and Gemini CLI.
"""
from __future__ import annotations

import json
import platform
import re
from pathlib import Path

# Patterns for extracting scannable URLs from MCP server entries
GITHUB_URL_RE = re.compile(r"https?://github\.com/[\w\-\.]+/[\w\-\.]+")
NPM_PACKAGE_RE = re.compile(r"^@?[a-zA-Z0-9][\w\-]*(?:/[a-zA-Z0-9][\w\-]*)?$")


def _build_config_paths() -> list[Path]:
    """Build list of MCP config file paths for all known clients."""
    home = Path.home()
    paths = [
        # Claude Desktop
        home / ".claude" / "claude_desktop_config.json",
        home / ".config" / "claude" / "claude_desktop_config.json",
        # Claude Code
        home / ".claude.json",
        home / ".claude" / "settings.json",
        home / ".claude" / "settings.local.json",
        # Cursor
        home / ".cursor" / "mcp.json",
        # Windsurf
        home / ".codeium" / "windsurf" / "mcp_config.json",
        # Gemini CLI
        home / ".gemini" / "settings.json",
    ]
    # macOS-specific paths
    if platform.system() == "Darwin":
        app_support = home / "Library" / "Application Support"
        paths.append(app_support / "Claude" / "claude_desktop_config.json")
    return paths


CONFIG_PATHS = _build_config_paths()


def _find_project_config_files() -> list[Path]:
    """Find .mcp.json files from cwd up to home directory.

    Claude Code stores project-level MCP server configs in .mcp.json files
    in the project root. Walk up from cwd to home, collecting any found.
    """
    home = Path.home()
    found: list[Path] = []
    try:
        current = Path.cwd().resolve()
    except OSError:
        return found

    home_resolved = home.resolve()

    while True:
        candidate = current / ".mcp.json"
        if candidate.is_file():
            found.append(candidate)
        # Stop at home directory or filesystem root
        if current == home_resolved or current == current.parent:
            break
        current = current.parent

    return found


def find_config_files() -> list[Path]:
    """Return all existing config file paths (global + project-level)."""
    global_files = [p for p in CONFIG_PATHS if p.exists()]
    project_files = _find_project_config_files()
    # Project files first so project-level servers take precedence in dedup
    return project_files + global_files


def read_config(path: Path) -> dict:
    """Read and parse a config JSON file. Returns empty dict on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _extract_urls_from_entry(name: str, entry: dict) -> list[str]:
    """Extract scannable URLs from a single MCP server entry.

    Handles common patterns:
    - npx @org/package -> https://github.com/org/package
    - npx unscoped-pkg -> https://www.npmjs.com/package/pkg (backend resolves)
    - uvx package -> https://pypi.org/project/package (backend resolves)
    - uvx git+https://github.com/... -> GitHub URL
    - Direct GitHub URLs in args or env values
    """
    urls: list[str] = []
    command = entry.get("command", "")
    args = entry.get("args", [])
    env = entry.get("env", {})

    # Handle "url" field (remote SSE/streamable-http servers) - extract GitHub URLs
    entry_url = entry.get("url", "")
    if isinstance(entry_url, str) and GITHUB_URL_RE.match(entry_url):
        urls.append(entry_url)

    # Collect all string values to search for GitHub URLs
    all_strings = [command] + list(args) + list(env.values())

    for s in all_strings:
        if not isinstance(s, str):
            continue
        for match in GITHUB_URL_RE.findall(s):
            if match not in urls:
                urls.append(match)

    # Handle npx @org/package pattern
    if command in ("npx", "npx.cmd") and args:
        pkg_args = list(args) if isinstance(args, list) else [str(args)]
        pkg = None
        for arg in pkg_args:
            if not arg.startswith("-"):
                pkg = arg
                break
        if pkg:
            if pkg.startswith("@") and "/" in pkg:
                # Scoped package: @org/pkg -> try GitHub
                org, repo = pkg.lstrip("@").split("/", 1)
                github_url = f"https://github.com/{org}/{repo}"
                if github_url not in urls:
                    urls.append(github_url)
            elif NPM_PACKAGE_RE.match(pkg):
                # Unscoped package: let the backend resolve via npm registry
                npm_url = f"https://www.npmjs.com/package/{pkg}"
                if npm_url not in urls:
                    urls.append(npm_url)

    # Handle uvx/uv package pattern
    if command in ("uvx", "uv") and args:
        pkg_args = list(args) if isinstance(args, list) else [str(args)]
        pkg_name = None
        for arg in pkg_args:
            if not arg.startswith("-") and arg != "run":
                pkg_name = arg
                break
        if pkg_name:
            # Handle git+https:// URLs
            if pkg_name.startswith("git+https://"):
                clean = pkg_name[4:]  # strip "git+"
                if clean.endswith(".git"):
                    clean = clean[:-4]
                match = GITHUB_URL_RE.match(clean)
                if match and match.group(0) not in urls:
                    urls.append(match.group(0))
            elif GITHUB_URL_RE.match(pkg_name):
                if pkg_name not in urls:
                    urls.append(pkg_name)
            elif NPM_PACKAGE_RE.match(pkg_name):
                # PyPI package: let the backend resolve via PyPI API
                pypi_url = f"https://pypi.org/project/{pkg_name}"
                if pypi_url not in urls:
                    urls.append(pypi_url)

    return urls


def discover_mcp_servers() -> list[dict]:
    """Discover all installed MCP servers and their scannable URLs.

    Returns a list of dicts with:
        - name: server name from config
        - urls: list of discovered GitHub/package URLs
        - config: raw config entry
    """
    servers: list[dict] = []
    seen_names: set[str] = set()

    for config_path in find_config_files():
        config = read_config(config_path)

        # Different clients use different config keys
        mcp_servers: dict = {}
        for key in ("mcpServers", "mcp", "mcp_servers"):
            candidate = config.get(key, {})
            if isinstance(candidate, dict) and candidate:
                mcp_servers = candidate
                break

        for name, entry in mcp_servers.items():
            if name in seen_names:
                continue
            seen_names.add(name)

            # Skip our own plugin (old and new name)
            if name in ("mcptotal", "mcpampel"):
                continue

            if not isinstance(entry, dict):
                continue

            urls = _extract_urls_from_entry(name, entry)
            servers.append({
                "name": name,
                "urls": urls,
                "config": entry,
            })

    return servers


def get_all_scannable_urls() -> list[str]:
    """Get a flat, deduplicated list of all scannable URLs from installed MCP servers."""
    urls: list[str] = []
    for server in discover_mcp_servers():
        for url in server["urls"]:
            if url not in urls:
                urls.append(url)
    return urls
