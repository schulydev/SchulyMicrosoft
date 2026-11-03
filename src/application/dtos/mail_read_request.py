from pydantic import BaseModel


class MailReadRequest(BaseModel):
    read: bool
