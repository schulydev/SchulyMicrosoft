from pydantic import BaseModel


class MailForwardRequest(BaseModel):
    to: list[str]
    comment: str = ""
