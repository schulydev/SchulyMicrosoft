from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_file_thumbnails import IFileThumbnails
from src.application.services.account_image_reader import AccountImageReader
from src.domain.files.binary_content import BinaryContent
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetDriveThumbnailQuery(IQuery[BinaryContent]):
    refresh_token: str = field(repr=False)
    item_id: str
    size: str


class GetDriveThumbnailHandler(IQueryHandler[GetDriveThumbnailQuery, BinaryContent]):
    def __init__(self, images: AccountImageReader, thumbnails: IFileThumbnails):
        self._images = images
        self._thumbnails = thumbnails

    async def handle(self, query: GetDriveThumbnailQuery) -> BinaryContent:
        GraphIds.check(query.item_id, GraphIds.DRIVE_ITEM_PATTERN, "item_id")
        self._images.check_thumbnail_size(query.size)
        return await self._images.thumbnail(query.refresh_token, lambda note, broker: self._thumbnails.drive_item_thumbnail(note, query.item_id, query.size))
