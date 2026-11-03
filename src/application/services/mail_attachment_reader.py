from src.application.abstractions.i_graph_client import IGraphClient
from src.domain.errors.service_error import ServiceError
from src.domain.files.file_limits import FileLimits
from src.domain.validation.graph_ids import GraphIds


class MailAttachmentReader:
    """A mail attachment's metadata and bytes, capped."""

    @staticmethod
    def metadata(note: IGraphClient, message_id: str, attachment_id: str) -> dict:
        # Look the attachment up in the metadata list first: it carries the type and size, so an oversized one is refused before downloading it.
        meta = next((a for a in note.list(f"me/messages/{GraphIds.seg(message_id)}/attachments") if a.get("id") == attachment_id), None)
        if meta is None:
            raise ServiceError(404, "Attachment not found.")
        return meta

    @staticmethod
    def check_declared_size(meta: dict) -> None:
        if (meta.get("size") or 0) > FileLimits.MAX_DOWNLOAD_BYTES:
            raise ServiceError(413, "The attachment is larger than 25 MB.")

    @staticmethod
    def download(note: IGraphClient, message_id: str, attachment_id: str) -> bytes:
        try:
            data = note.download_attachment(GraphIds.seg(message_id), GraphIds.seg(attachment_id))
        except ValueError as ex:
            raise ServiceError(422, str(ex))
        if len(data) > FileLimits.MAX_DOWNLOAD_BYTES:
            raise ServiceError(413, "The attachment is larger than 25 MB.")
        return data

    @staticmethod
    def attachment_meta(item: dict) -> dict:
        keep = ("id", "name", "contentType", "size", "isInline", "contentId")
        return {k: item.get(k) for k in keep}
