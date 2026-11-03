from pydantic import BaseModel, Field

from src.application.dtos.mail_attachment_in import MailAttachmentIn


class MailMessageIn(BaseModel):
    to: list[str] = Field(default_factory=list)
    cc: list[str] | None = None
    bcc: list[str] | None = None
    subject: str
    body: str
    html: bool = False
    attachments: list[MailAttachmentIn] | None = None
