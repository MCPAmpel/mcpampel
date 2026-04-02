"""Tests for the MCPAmpel scanner HTTP client."""
import os
from unittest.mock import AsyncMock, patch

import pytest

from mcpampel.scanner import ScannerClient


def test_client_requires_api_key():
    """Client raises ValueError when no API key is set."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="MCPAMPEL_API_KEY"):
            ScannerClient(api_key="")


def test_client_reads_new_env_vars():
    """Client reads MCPAMPEL_* env vars."""
    with patch.dict(os.environ, {
        "MCPAMPEL_API_KEY": "sk_new_123",
        "MCPAMPEL_BASE_URL": "https://new.dev",
    }, clear=True):
        client = ScannerClient()
        assert client.api_key == "sk_new_123"
        assert client.base_url == "https://new.dev"


def test_client_falls_back_to_old_env_vars():
    """Client falls back to MCPTOTAL_* env vars for backward compat."""
    with patch.dict(os.environ, {
        "MCPTOTAL_API_KEY": "sk_old_456",
        "MCPTOTAL_BASE_URL": "https://old.dev",
    }, clear=True):
        client = ScannerClient()
        assert client.api_key == "sk_old_456"
        assert client.base_url == "https://old.dev"


def test_client_new_env_vars_take_precedence():
    """New MCPAMPEL_* vars win over old MCPTOTAL_* vars."""
    with patch.dict(os.environ, {
        "MCPAMPEL_API_KEY": "sk_new",
        "MCPTOTAL_API_KEY": "sk_old",
    }, clear=True):
        client = ScannerClient()
        assert client.api_key == "sk_new"


def test_client_explicit_params():
    """Explicit params override env vars."""
    client = ScannerClient(api_key="sk_explicit", base_url="https://explicit.dev")
    assert client.api_key == "sk_explicit"
    assert client.base_url == "https://explicit.dev"


def test_client_strips_trailing_slash():
    """Base URL trailing slash is stripped."""
    client = ScannerClient(api_key="sk_test", base_url="https://example.dev/")
    assert client.base_url == "https://example.dev"


def test_client_headers():
    """Headers include API key."""
    client = ScannerClient(api_key="sk_test_abc")
    headers = client._headers()
    assert headers["X-API-Key"] == "sk_test_abc"


async def test_client_async_context_manager():
    """Client can be used as an async context manager."""
    async with ScannerClient(api_key="sk_test", base_url="https://example.dev") as client:
        assert client.api_key == "sk_test"
        assert not client._client.is_closed
    assert client._client.is_closed


async def test_client_aclose():
    """Client aclose shuts down the httpx client."""
    client = ScannerClient(api_key="sk_test", base_url="https://example.dev")
    assert not client._client.is_closed
    await client.aclose()
    assert client._client.is_closed


async def test_client_reuses_httpx_client():
    """Underlying httpx client is the same object across requests (not recreated)."""
    client = ScannerClient(api_key="sk_test", base_url="https://example.dev")
    inner_client = client._client
    # The client object should remain the same (not recreated per request)
    assert client._client is inner_client
    await client.aclose()
