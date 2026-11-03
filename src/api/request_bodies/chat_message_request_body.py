import json

from fastapi import Request
from starlette.datastructures import UploadFile

from src.api.request_bodies.limited_request import LimitedRequest
from src.application.abstractions.i_chat_message_body import IChatMessageBody
from src.domain.chat.chat_send_limits import ChatSendLimits
from src.domain.chat.upload import Upload
from src.domain.errors.service_error import ServiceError


class ChatMessageRequestBody(IChatMessageBody):
    """A chat send's JSON or multipart body."""

    def __init__(self, request: Request):
        self._request = request
        self._form = None

    @property
    def is_multipart(self) -> bool:
        return self._request.headers.get("content-type", "").lower().startswith("multipart/form-data")

    @property
    def declared_length(self) -> str | None:
        return self._request.headers.get("content-length")

    async def read(self, cap: int) -> tuple[dict, list[Upload], list[Upload]]:
        multipart = self.is_multipart
        request = LimitedRequest.limit(self._request, cap)
        if multipart:
            # Starlette spools each file part to a temporary file past 1 MB; close() deletes them.
            form = self._form = await request.form(max_files=ChatSendLimits.MAX_IMAGES + ChatSendLimits.MAX_FILES, max_fields=ChatSendLimits.MAX_FIELDS, max_part_size=ChatSendLimits.MAX_PART_SIZE)
            fields = {k: form.get(k) for k in ("content", "text", "contentType", "importance") if isinstance(form.get(k), str)}
            fields["mentions"] = self._json_field(form.get("mentions"), "mentions")
            fields["gif"] = self._json_field(form.get("gif"), "gif")
            images = [self._upload(f) for f in form.getlist("images") if isinstance(f, UploadFile)]
            files = [self._upload(f) for f in form.getlist("files") if isinstance(f, UploadFile)]
            return fields, images, files
        try:
            fields = await request.json()
        except ValueError:
            raise ServiceError(400, "The body must be JSON or multipart/form-data.")
        if not isinstance(fields, dict):
            raise ServiceError(400, "The body must be a JSON object.")
        return fields, [], []

    async def close(self) -> None:
        if self._form is not None:
            await self._form.close()

    @staticmethod
    def _json_field(value, name: str):
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ServiceError(400, f"{name} must be a JSON string.")
        try:
            return json.loads(value)
        except ValueError:
            raise ServiceError(400, f"{name} is not valid JSON.")

    @staticmethod
    def _upload(part: UploadFile) -> Upload:
        size = part.size
        if size is None:
            part.file.seek(0, 2)
            size = part.file.tell()
        part.file.seek(0)
        return Upload(name=part.filename or "file", file=part.file, size=size, content_type=part.content_type)
