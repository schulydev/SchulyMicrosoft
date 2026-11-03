import asyncio
import logging
import threading
import time
from http.cookiejar import DefaultCookiePolicy
from urllib.parse import urljoin

import entrance
import httpx

from src.application.abstractions.i_microsoft_http_clients import IMicrosoftHttpClients
from src.application.options.microsoft_options import MicrosoftOptions
from src.application.services.retry_after import RetryAfter
from src.domain.errors.download_link_expired import DownloadLinkExpired
from src.domain.errors.service_error import ServiceError
from src.domain.files.byte_range import ByteRange
from src.domain.files.file_stream import FileStream
from src.infrastructure.logging_config import LoggerNames


class MicrosoftHttpClients(IMicrosoftHttpClients):
    """The shared keep-alive clients: one for capped or streamed bodies and one for the sign-in calls."""

    log = logging.getLogger(LoggerNames.SERVICE)
    MAX_DOWNLOAD_REDIRECTS = 3
    DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=5.0)

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

    def open_download(self, url: str, limit: int, allowed, content_type: str, file_name: str, byte_range: str | None = None) -> FileStream:
        """Opens a pre-authorized download URL (no bearer token is sent) and answers once its status and headers are known, so a refusal is a real status and not a broken 200.

        Every hop must pass `allowed`. It asks for the bytes as they are (`identity`) and passes them on raw, so a `Range` and the lengths stay true. The body is read chunk by chunk as the caller asks for it."""
        headers = {"Accept-Encoding": "identity"}
        if byte_range:
            headers["Range"] = byte_range
        client = self.download_client()
        for _ in range(self.MAX_DOWNLOAD_REDIRECTS + 1):
            if not allowed(url):
                raise ServiceError(502, "The file has an unexpected download location.")
            r = client.send(client.build_request("GET", url, headers=headers, timeout=self.DOWNLOAD_TIMEOUT), stream=True, follow_redirects=False)
            if not r.is_redirect:
                return self._opened(r, limit, content_type, file_name)
            location = r.headers.get("Location")
            r.close()
            if not location:
                raise ServiceError(502, "The download failed (a redirect with no location).")
            url = urljoin(url, location)
        raise ServiceError(502, "The download failed (too many redirects).")

    def _opened(self, r: httpx.Response, limit: int, content_type: str, file_name: str) -> FileStream:
        status = r.status_code
        if status in (200, 206):
            content_range = ByteRange.safe_content_range(r.headers.get("Content-Range")) if status == 206 else None
            if status == 206 and content_range is None:
                r.close()
                raise ServiceError(502, "The download failed (an unreadable range).")
            length = int(r.headers["Content-Length"]) if r.headers.get("Content-Length", "").isdigit() else None
            whole = ByteRange.total(content_range) if status == 206 else length
            if (whole or 0) > limit or (length or 0) > limit:
                r.close()
                raise ServiceError(413, "The file is too large.")
            return FileStream(self._body(r, limit), content_type, file_name, status, length, content_range)
        if status == 416:
            content_range = ByteRange.safe_content_range(r.headers.get("Content-Range"))
            r.close()
            return FileStream(iter(()), content_type, file_name, 416, 0, content_range)
        retry_after = r.headers.get("Retry-After", "")
        r.close()
        if status in (401, 403, 410):
            raise DownloadLinkExpired()
        if status in (429, 503):
            raise ServiceError(429, "Microsoft is throttling this download; try again later.", headers={"Retry-After": RetryAfter.header(float(retry_after) if retry_after.isdigit() else None)})
        raise ServiceError(404 if status == 404 else 502, f"The download failed ({status}).")

    @staticmethod
    def _body(r: httpx.Response, limit: int):
        """The body, broken off past `limit` rather than quietly cut short. Closing the iterator (a player that seeks elsewhere) closes the connection."""
        sent = 0
        try:
            for chunk in r.iter_raw(64 * 1024):
                sent += len(chunk)
                if sent > limit:
                    raise ServiceError(413, "The file is too large.")
                yield chunk
        finally:
            r.close()
