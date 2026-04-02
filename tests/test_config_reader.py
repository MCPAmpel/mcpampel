"""Tests for MCP config reader."""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from mcpampel.config_reader import (
    CONFIG_PATHS,
    _extract_urls_from_entry,
    _find_project_config_files,
    discover_mcp_servers,
    find_config_files,
    get_all_scannable_urls,
    read_config,
)


# --- Config path discovery ---


def test_config_paths_includes_claude_code():
    """Config paths include Claude Code settings locations."""
    path_strs = [str(p) for p in CONFIG_PATHS]
    assert any(".claude" in p and "settings" in p for p in path_strs)


def test_config_paths_includes_cursor():
    """Config paths include Cursor config location."""
    path_strs = [str(p) for p in CONFIG_PATHS]
    assert any(".cursor" in p for p in path_strs)


def test_config_paths_includes_windsurf():
    """Config paths include Windsurf config location."""
    path_strs = [str(p) for p in CONFIG_PATHS]
    assert any("windsurf" in p for p in path_strs)


def test_config_paths_includes_gemini():
    """Config paths include Gemini CLI config location."""
    path_strs = [str(p) for p in CONFIG_PATHS]
    assert any(".gemini" in p for p in path_strs)


# --- URL extraction ---


def test_extract_npx_scoped_package():
    entry = {"command": "npx", "args": ["@modelcontextprotocol/server-filesystem"]}
    urls = _extract_urls_from_entry("filesystem", entry)
    assert "https://github.com/modelcontextprotocol/server-filesystem" in urls


def test_extract_npx_scoped_with_flags():
    """npx -y @org/pkg skips the -y flag and finds the package."""
    entry = {"command": "npx", "args": ["-y", "@org/server"]}
    urls = _extract_urls_from_entry("test", entry)
    assert "https://github.com/org/server" in urls


def test_extract_npx_unscoped_generates_npm_url():
    """Unscoped npx packages generate npmjs.com URLs for backend resolution."""
    entry = {"command": "npx", "args": ["mcp-server-memory"]}
    urls = _extract_urls_from_entry("memory", entry)
    assert "https://www.npmjs.com/package/mcp-server-memory" in urls


def test_extract_github_url_from_args():
    entry = {
        "command": "node",
        "args": ["index.js"],
        "env": {"REPO": "https://github.com/owner/repo"},
    }
    urls = _extract_urls_from_entry("test", entry)
    assert "https://github.com/owner/repo" in urls


def test_extract_uvx_generates_pypi_url():
    """uvx packages generate pypi.org URLs for backend resolution."""
    entry = {"command": "uvx", "args": ["mcp-server-fetch"]}
    urls = _extract_urls_from_entry("fetch", entry)
    assert len(urls) == 1
    assert urls[0] == "https://pypi.org/project/mcp-server-fetch"


def test_extract_uvx_git_url():
    """uvx git+https:// URLs extract the GitHub URL."""
    entry = {"command": "uvx", "args": ["git+https://github.com/googlecolab/colab-mcp"]}
    urls = _extract_urls_from_entry("colab", entry)
    assert "https://github.com/googlecolab/colab-mcp" in urls


def test_extract_no_urls():
    entry = {"command": "/usr/local/bin/custom-server", "args": ["--port", "3000"]}
    urls = _extract_urls_from_entry("custom", entry)
    assert urls == []


def test_extract_github_url_from_command_args():
    entry = {
        "command": "git",
        "args": ["clone", "https://github.com/org/mcp-tool"],
    }
    urls = _extract_urls_from_entry("tool", entry)
    assert "https://github.com/org/mcp-tool" in urls


def test_extract_deduplicates():
    entry = {
        "command": "npx",
        "args": ["@org/pkg"],
        "env": {"SOURCE": "https://github.com/org/pkg"},
    }
    urls = _extract_urls_from_entry("test", entry)
    assert urls.count("https://github.com/org/pkg") == 1


# --- Config reading ---


def test_read_config_valid(tmp_path):
    config = {"mcpServers": {"test": {"command": "node"}}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    result = read_config(path)
    assert result == config


def test_read_config_invalid_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("not json")
    result = read_config(path)
    assert result == {}


def test_read_config_missing():
    result = read_config(Path("/nonexistent/path/config.json"))
    assert result == {}


# --- Server discovery ---


def test_discover_skips_own_plugin(tmp_path):
    """Both old (mcptotal) and new (mcpampel) plugin names are skipped."""
    config = {
        "mcpServers": {
            "mcptotal": {"command": "uvx", "args": ["mcptotal"]},
            "mcpampel": {"command": "uvx", "args": ["mcpampel"]},
            "other": {"command": "npx", "args": ["@org/server"]},
        }
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))

    with patch("mcpampel.config_reader.find_config_files", return_value=[path]):
        servers = discover_mcp_servers()

    assert len(servers) == 1
    assert servers[0]["name"] == "other"


def test_discover_handles_alternative_config_keys(tmp_path):
    """Discovers servers under 'mcp' key (used by some clients)."""
    config = {
        "mcp": {
            "my-server": {"command": "npx", "args": ["@org/server"]},
        }
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))

    with patch("mcpampel.config_reader.find_config_files", return_value=[path]):
        servers = discover_mcp_servers()

    assert len(servers) == 1
    assert servers[0]["name"] == "my-server"


def test_get_all_scannable_urls(tmp_path):
    config = {
        "mcpServers": {
            "a": {"command": "npx", "args": ["@org/server-a"]},
            "b": {"command": "npx", "args": ["@org/server-b"]},
        }
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))

    with patch("mcpampel.config_reader.find_config_files", return_value=[path]):
        urls = get_all_scannable_urls()

    assert len(urls) == 2
    assert "https://github.com/org/server-a" in urls
    assert "https://github.com/org/server-b" in urls


# --- Project-level .mcp.json discovery ---


def test_find_project_config_files_discovers_mcp_json(tmp_path):
    """Finds .mcp.json in current working directory."""
    mcp_json = tmp_path / ".mcp.json"
    mcp_json.write_text(json.dumps({"mcpServers": {"test": {"command": "node"}}}))

    with patch("mcpampel.config_reader.Path.cwd", return_value=tmp_path), \
         patch("mcpampel.config_reader.Path.home", return_value=tmp_path):
        found = _find_project_config_files()

    assert mcp_json in found


def test_find_project_config_files_walks_up_to_home(tmp_path):
    """Walks up from cwd to home, collecting .mcp.json files."""
    # Create directory structure: home/project/sub
    project_dir = tmp_path / "project"
    sub_dir = project_dir / "sub"
    sub_dir.mkdir(parents=True)

    # .mcp.json in project root only
    project_mcp = project_dir / ".mcp.json"
    project_mcp.write_text(json.dumps({"mcpServers": {}}))

    with patch("mcpampel.config_reader.Path.cwd", return_value=sub_dir), \
         patch("mcpampel.config_reader.Path.home", return_value=tmp_path):
        found = _find_project_config_files()

    assert project_mcp in found


def test_find_project_config_files_stops_at_home(tmp_path):
    """Does not traverse above the home directory."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    project_dir = home_dir / "project"
    project_dir.mkdir()

    # .mcp.json above home (should not be found)
    above_home = tmp_path / ".mcp.json"
    above_home.write_text(json.dumps({"mcpServers": {}}))

    with patch("mcpampel.config_reader.Path.cwd", return_value=project_dir), \
         patch("mcpampel.config_reader.Path.home", return_value=home_dir):
        found = _find_project_config_files()

    assert above_home not in found


def test_find_project_config_files_empty_when_none(tmp_path):
    """Returns empty list when no .mcp.json files exist."""
    with patch("mcpampel.config_reader.Path.cwd", return_value=tmp_path), \
         patch("mcpampel.config_reader.Path.home", return_value=tmp_path):
        found = _find_project_config_files()

    assert found == []


def test_discover_includes_project_mcp_json(tmp_path):
    """discover_mcp_servers includes servers from project-level .mcp.json."""
    config = {
        "mcpServers": {
            "project-server": {"command": "npx", "args": ["@org/project-tool"]},
        }
    }
    mcp_json = tmp_path / ".mcp.json"
    mcp_json.write_text(json.dumps(config))

    with patch("mcpampel.config_reader.find_config_files", return_value=[mcp_json]):
        servers = discover_mcp_servers()

    assert len(servers) == 1
    assert servers[0]["name"] == "project-server"


# --- Remote URL entry ---


def test_extract_url_field_github():
    """Extracts GitHub URL from the 'url' field (remote SSE servers)."""
    entry = {"url": "https://github.com/owner/mcp-server"}
    urls = _extract_urls_from_entry("remote", entry)
    assert "https://github.com/owner/mcp-server" in urls


def test_extract_url_field_non_github_ignored():
    """Non-GitHub 'url' field values are not extracted."""
    entry = {"url": "https://my-mcp-server.example.com/sse"}
    urls = _extract_urls_from_entry("remote", entry)
    assert urls == []


# --- Edge cases ---


def test_extract_handles_non_string_env_values():
    """Non-string env values do not cause errors."""
    entry = {"command": "node", "args": [], "env": {"PORT": 3000, "DEBUG": True}}
    urls = _extract_urls_from_entry("test", entry)
    assert urls == []


def test_extract_handles_non_list_args():
    """Entry with non-list args value does not crash."""
    entry = {"command": "npx", "args": "@org/server"}
    urls = _extract_urls_from_entry("test", entry)
    # Should not crash; the string args go through all_strings search
    assert isinstance(urls, list)


def test_discover_deduplicates_across_configs(tmp_path):
    """Same server name in two config files is only included once."""
    config = {"mcpServers": {"shared": {"command": "npx", "args": ["@org/server"]}}}
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    path_a.write_text(json.dumps(config))
    path_b.write_text(json.dumps(config))

    with patch("mcpampel.config_reader.find_config_files", return_value=[path_a, path_b]):
        servers = discover_mcp_servers()

    assert len(servers) == 1


def test_discover_skips_non_dict_entries(tmp_path):
    """Non-dict server entries (e.g. null, string) are skipped."""
    config = {"mcpServers": {"bad": "not a dict", "good": {"command": "npx", "args": ["@org/server"]}}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))

    with patch("mcpampel.config_reader.find_config_files", return_value=[path]):
        servers = discover_mcp_servers()

    assert len(servers) == 1
    assert servers[0]["name"] == "good"
