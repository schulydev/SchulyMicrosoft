from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_people_photos import IPeoplePhotos
from src.application.services.account_image_reader import AccountImageReader
from src.application.services.mail_message_builder import MailMessageBuilder
from src.application.services.retry_after import RetryAfter
from src.domain.errors.photo_throttled import PhotoThrottled
from src.domain.errors.service_error import ServiceError
from src.domain.files.binary_content import BinaryContent


@dataclass
class GetPersonPhotoQuery(IQuery[BinaryContent]):
    refresh_token: str = field(repr=False)
    email: str
    size: int


class GetPersonPhotoHandler(IQueryHandler[GetPersonPhotoQuery, BinaryContent]):
    PHOTO_SIZES = (48, 64, 96, 120, 240)

    def __init__(self, images: AccountImageReader, photos: IPeoplePhotos):
        self._images = images
        self._photos = photos

    async def handle(self, query: GetPersonPhotoQuery) -> BinaryContent:
        if not MailMessageBuilder.EMAIL_PATTERN.fullmatch(query.email.strip()):
            raise ServiceError(400, "Invalid email.")
        if query.size not in self.PHOTO_SIZES:
            raise ServiceError(400, f"size must be one of {', '.join(str(s) for s in self.PHOTO_SIZES)}")

        def fetch(note, broker):
            try:
                return self._photos.photo(note, broker, query.email, query.size)
            except PhotoThrottled as ex:
                raise ServiceError(429, "Microsoft is throttling photo requests.", headers={"Retry-After": RetryAfter.header(ex.retry_after)})

        return await self._images.photo(query.refresh_token, fetch, "No profile photo for that address.")
