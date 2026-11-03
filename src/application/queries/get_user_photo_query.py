from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_people_photos import IPeoplePhotos
from src.application.services.account_image_reader import AccountImageReader
from src.domain.errors.service_error import ServiceError
from src.domain.files.binary_content import BinaryContent
from src.domain.validation.graph_ids import GraphIds


@dataclass
class GetUserPhotoQuery(IQuery[BinaryContent]):
    refresh_token: str = field(repr=False)
    user_id: str
    size: int


class GetUserPhotoHandler(IQueryHandler[GetUserPhotoQuery, BinaryContent]):
    PHOTO_SIZES = (48, 64, 96, 120, 240)

    def __init__(self, images: AccountImageReader, photos: IPeoplePhotos):
        self._images = images
        self._photos = photos

    async def handle(self, query: GetUserPhotoQuery) -> BinaryContent:
        GraphIds.check(query.user_id, GraphIds.USER_ID_PATTERN, "user_id")
        if query.size not in self.PHOTO_SIZES:
            raise ServiceError(400, f"size must be one of {', '.join(str(s) for s in self.PHOTO_SIZES)}")
        return await self._images.photo(query.refresh_token, lambda note, broker: self._photos.user_photo(note, query.user_id, query.size), "The user has no profile photo.")
