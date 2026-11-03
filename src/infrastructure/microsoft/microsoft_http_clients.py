import asyncio
import logging
import threading
import time
from http.cookiejar import DefaultCookiePolicy

import entrance
import httpx

from src.application.abstractions.i_microsoft_http_clients import IMicrosoftHttpClients
from src.application.options.microsoft_options import MicrosoftOptions
from src.infrastructure.logging_config import LoggerNames


class MicrosoftHttpClients(IMicrosoftHttpClients):
    """The shared keep-alive clients: one for capped or streamed bodies and one for the sign-in calls."""

    log = logging.getLogger(LoggerNames.SERVICE)

    def __init__(self, options: MicrosoftOptions):
        self._options = options
        self._async_client: httpx.AsyncClient | None = None
        self._download_client: httpx.Client | None = None
        self._download_lock = threading.Lock()

    def download_client(self) -> httpx.Client:
        """One keep-alive client for bodies that must stay capped or be streamed: `entrance.http_client()` reads every body into memory first and has no stream.

        It is shared by all accounts, so it keeps no cookies (SharePoint sets them on downloads) and never holds a token; a bearer goes per request, with redirects off."""
        if self._download_client is None:
            with self._download_lock:
                if self._download_client is None:
                    client = httpx.Client(
                        timeout=httpx.Timeout(30.0, connect=5.0),
                        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=60),
                        transport=httpx.HTTPTransport(retries=3),
                        follow_redirects=False,
                    )
                    client.cookies.jar.set_policy(DefaultCookiePolicy(allowed_domains=[]))
                    self._download_client = client
        return self._download_client

    def shared_async_client(self) -> httpx.AsyncClient:
        """One keep-alive client for the sign-in calls (connect bounded to 5 s, connect retries)."""
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=5.0),
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=10, keepalive_expiry=60),
                transport=httpx.AsyncHTTPTransport(retries=3),
            )
        return self._async_client

    async def close_shared_client(self) -> None:
        client, self._async_client = self._async_client, None
        if client is not None:
            await client.aclose()
        with self._download_lock:
            download, self._download_client = self._download_client, None
        if download is not None:
            download.close()

    async def warm_up(self) -> None:
        """Open connections to Microsoft's login and Graph hosts so the first real call skips DNS, TCP and TLS."""
        await asyncio.to_thread(entrance.warm_up, [self._options.token_url, "https://graph.microsoft.com/v1.0/"])

    async def post_form(self, url: str, data: dict, client: httpx.AsyncClient | None = None) -> dict:
        client = client or self.shared_async_client()
        started = time.perf_counter()
        try:
            response = await client.post(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
            return response.json()
        finally:
            self.log.debug("POST %s took %.0f ms", url, (time.perf_counter() - started) * 1000)

    def stream_download(self, url: str, limit: int, follow_redirects: bool = True):
        """Yields a pre-authorized download URL's bytes in chunks (no bearer token is sent), stopping past `limit` bytes."""
        with self.download_client().stream("GET", url, timeout=httpx.Timeout(60.0, connect=5.0), follow_redirects=follow_redirects) as r:
            r.raise_for_status()
            sent = 0
            for chunk in r.iter_bytes(64 * 1024):
                sent += len(chunk)
                if sent > limit:
                    return
                yield chunk
