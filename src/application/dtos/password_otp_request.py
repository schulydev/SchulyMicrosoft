from pydantic import BaseModel, Field


class PasswordOtpRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=12, description="The authenticator app code (digits; spaces are ignored).")
