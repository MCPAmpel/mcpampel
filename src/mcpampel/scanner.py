"""HTTP client for the MCPAmpel backend API."""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://mcpampel.com"
_MAX_RETRIES = 3
_BACKOFF_SECONDS = [1, 2, 4]


def _is_retryable(exc: Exception) -> bool:
    """Return True for transient errors worth retrying."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500:
        return True
    return False


class ScannerClient:
    """Authenticated client for the MCPAmpel backend API.

    Use as an async context manager to ensure the underlying HTTP connection
    pool is properly closed::

        async with ScannerClient() as client:
            result = await client.scan_urls([...])

    Or call ``aclose()`` explicitly when done.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("MCPAMPEL_API_KEY") or os.environ.get("MCPTOTAL_API_KEY", "")
        self.base_url = (
            base_url
            or os.environ.get("MCPAMPEL_BASE_URL")
            or os.environ.get("MCPTOTAL_BASE_URL", _DEFAULT_BASE_URL)
        ).rstrip("/")

        if not self.api_key:
            raise ValueError(
                "MCPAMPEL_API_KEY not set. Get your free key at https://mcpampel.com "
                "or set the MCPAMPEL_API_KEY environment variable."
            )

        if not self.base_url.startswith("https://"):
            logger.warning(
                "MCPAMPEL_BASE_URL does not use HTTPS: %s. "
                "This is insecure and should only be used for local development.",
                self.base_url,
            )

        if self.base_url.rstrip("/") != _DEFAULT_BASE_URL:
            logger.warning(
                "MCPAMPEL_BASE_URL overridden from default: %s",
                self.base_url,
            )

        self._client = httpx.AsyncClient(base_url=self.base_url)

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> ScannerClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float = 15,
        **kwargs,
    ) -> httpx.Response:
        """Execute an HTTP request with retry and exponential backoff."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await self._client.request(
                    method, path, headers=self._headers(), timeout=timeout, **kwargs,
                )
                resp.raise_for_status()
                return resp
            except Exception as exc:
                last_exc = exc
                if not _is_retryable(exc) or attempt == _MAX_RETRIES - 1:
                    raise
                delay = _BACKOFF_SECONDS[attempt]
                logger.warning(
                    "Request %s %s failed (attempt %d/%d): %s. Retrying in %ds.",
                    method, path, attempt + 1, _MAX_RETRIES, exc, delay,
                )
                await asyncio.sleep(delay)
        # Unreachable, but keeps type checkers happy.
        raise last_exc  # type: ignore[misc]

    async def scan_urls(self, urls: list[str]) -> dict:
        """Submit a batch of URLs for scanning."""
        resp = await self._request("POST", "/api/v1/scan-urls", timeout=30, json={"urls": urls})
        return resp.json()

    async def get_my_scans(self, page: int = 1, per_page: int = 20) -> list[dict]:
        """Get scan history for this API key."""
        resp = await self._request(
            "GET", "/api/v1/scans/mine", params={"page": page, "per_page": per_page},
        )
        return resp.json()

    async def get_subscription(self) -> dict:
        """Get subscription tier and usage info."""
        resp = await self._request("GET", "/api/v1/subscription", timeout=10)
        return resp.json()

    async def get_scan(self, scan_id: str) -> dict:
        """Get full results for a specific scan."""
        resp = await self._request("GET", f"/api/v1/scans/{scan_id}")
        return resp.json()

    async def poll_scan(self, scan_id: str, interval: float = 5, timeout: float = 300) -> dict:
        """Poll a scan until it reaches a terminal status or timeout.

        Returns the scan result dict. If the timeout expires, returns the
        last polled state (which may be partial / still in progress).
        """
        elapsed = 0.0
        scan: dict | None = None
        while elapsed < timeout:
            scan = await self.get_scan(scan_id)
            status = scan.get("status", "")
            if status in ("completed", "failed"):
                return scan
            logger.info(
                "Scan %s status: %s (%s/%s engines). Polling again in %ds.",
                scan_id, status,
                scan.get("engines_completed", "?"), scan.get("engines_total", "?"),
                int(interval),
            )
            await asyncio.sleep(interval)
            elapsed += interval
        if scan is not None:
            logger.warning("Scan %s did not finish within %ds. Returning partial results.", scan_id, int(timeout))
            return scan
        # Fallback: fetch once if timeout was <= 0 (should not happen in practice)
        return await self.get_scan(scan_id)
