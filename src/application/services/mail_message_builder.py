import base64
import binascii
import re

from src.application.dtos.mail_message_in import MailMessageIn
from src.application.services.content_names import ContentNames
from src.domain.errors.service_error import ServiceError
from src.domain.files.file_limits import FileLimits


class MailMessageBuilder:
    """A mail message from the caller's input, checked: recipients, subject, body size and attachments."""

    EMAIL_PATTERN = re.compile(r"[^@\s<>(),;:\\\"\[\]]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.[A-Za-z]{2,}")
    MAX_RECIPIENTS = 100
    MAX_SUBJECT = 255

    @staticmethod
    def check_text(value: str, name: str) -> None:
        if len(value.encode("utf-8")) > FileLimits.MAX_BODY_BYTES:
            raise ServiceError(413, f"{name} is larger than 1 MB.")

    def addresses(self, values: list[str] | None, name: str) -> list[str]:
        out = [v.strip() for v in values or []]
        for address in out:
            if len(address) > 254 or not self.EMAIL_PATTERN.fullmatch(address):
                raise ServiceError(400, f"Invalid address in {name}.")
        return out

    def message_args(self, body: MailMessageIn) -> dict:
        to, cc, bcc = self.addresses(body.to, "to"), self.addresses(body.cc, "cc"), self.addresses(body.bcc, "bcc")
        if not to and not cc and not bcc:
            raise ServiceError(400, "At least one recipient is required.")
        if len(to) + len(cc) + len(bcc) > self.MAX_RECIPIENTS:
            raise ServiceError(400, f"At most {self.MAX_RECIPIENTS} recipients are allowed.")
        if len(body.subject) > self.MAX_SUBJECT:
            raise ServiceError(400, f"The subject may be at most {self.MAX_SUBJECT} characters.")
        self.check_text(body.body, "body")
        attachments, total = [], 0
        for item in body.attachments or []:
            try:
                data = base64.b64decode(item.contentBase64, validate=True)
            except (binascii.Error, ValueError):
                raise ServiceError(400, "An attachment is not valid base64.")
            total += len(data)
            if total > FileLimits.MAX_SEND_ATTACHMENT_BYTES:
                raise ServiceError(413, "Attachments may total at most 3 MB.")
            attachments.append((ContentNames.safe_name(item.name), data))
        return {"to": to, "subject": body.subject, "body": body.body, "html": body.html, "cc": cc or None, "bcc": bcc or None, "attachments": attachments or None}
