from typing import Literal

from pydantic import BaseModel


class MailFlagRequest(BaseModel):
    status: Literal["flagged", "complete", "notFlagged"]
