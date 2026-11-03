from pydantic import BaseModel


class MailAttachmentIn(BaseModel):
    name: str
    contentType: str | None = None
    contentBase64: str
