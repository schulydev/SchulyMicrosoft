from pydantic import BaseModel


class MailMoveRequest(BaseModel):
    folder: str
