import asyncio
from collections.abc import Callable

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_microsoft_http_clients import IMicrosoftHttpClients
from src.application.abstractions.i_teams_files import ITeamsFiles
from src.application.services.content_names import ContentNames
from src.domain.errors.download_link_expired import DownloadLinkExpired
from src.domain.errors.service_error import ServiceError
from src.domain.files.byte_range import ByteRange
from src.domain.files.file_stream import FileStream


class FileDownloads:
    """Opens a file's bytes for streaming. The link is kept per account for minutes, so a video's seeks don't each cost Graph calls; a link SharePoint refuses is replaced once."""

    def __init__(self, accounts: IAccountRunner, files: ITeamsFiles, http: IMicrosoftHttpClients):
        self._accounts = accounts
        self._files = files
        self._http = http

    async def open(self, token: str, key: tuple, read: Callable, limit: int, byte_range: str | None) -> FileStream:
        """`read(note, broker)` answers `(item, link)` when no link is kept."""

        def target(note, broker, again=False):
            kept = None if again else self._files.cached_download(broker, key)
            if kept:
                return kept
            item, url = read(note, broker)
            name = item.get("name")
            found = {"url": url, "name": ContentNames.safe_name(name), "type": ContentNames.media_type(name, (item.get("file") or {}).get("mimeType"))}
            self._files.remember_download(broker, key, found)
            return found

        found = await self._accounts.run(token, target)
        try:
            return await self._open(found, limit, byte_range)
        except DownloadLinkExpired:
            pass
        found = await self._accounts.run(token, lambda note, broker: target(note, broker, again=True))
        try:
            return await self._open(found, limit, byte_range)
        except DownloadLinkExpired:
            await self._accounts.run(token, lambda note, broker: self._files.forget_download(broker, key))
            raise ServiceError(502, "SharePoint refused the download.")

    async def _open(self, found: dict, limit: int, byte_range: str | None) -> FileStream:
        return await asyncio.to_thread(self._http.open_download, found["url"], limit, self._files.is_download_url, found["type"], found["name"], ByteRange.parse(byte_range))
