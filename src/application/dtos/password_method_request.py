from typing import Literal

from pydantic import BaseModel


class PasswordMethodRequest(BaseModel):
    method: Literal["push", "otp"]
