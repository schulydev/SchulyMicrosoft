from collections.abc import Callable

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_file_thumbnails import IFileThumbnails
from src.application.services.image_sniffer import ImageSniffer
from src.domain.errors.service_error import ServiceError
from src.domain.files.binary_content import BinaryContent


class AccountImageReader:
    """Images read for an account: thumbnails, and photos and pictures with a 404 of their own when there are none."""

    def __init__(self, accounts: IAccountRunner, thumbnails: IFileThumbnails):
        self._accounts = accounts
        self._thumbnails = thumbnails

    def check_thumbnail_size(self, size: str) -> None:
        if size not in self._thumbnails.SIZES:
            raise ServiceError(400, f"size must be one of {', '.join(self._thumbnails.SIZES)}")

    async def thumbnail(self, token: str, fetch: Callable) -> BinaryContent:
        data = await self._accounts.run(token, fetch)
        mime = self._thumbnails.image_type((data or b"")[:12])
        if mime is None:
            raise ServiceError(404, "The file has no thumbnail.")
        return BinaryContent(data, mime)

    async def photo(self, token: str, fetch: Callable, missing: str) -> BinaryContent:
        data = await self._accounts.run(token, fetch)
        if not data:
            raise ServiceError(404, missing)
        return BinaryContent(data, ImageSniffer.photo(data))
