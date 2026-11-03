from pydantic import BaseModel


class MailReplyRequest(BaseModel):
    comment: str
    replyAll: bool = False
