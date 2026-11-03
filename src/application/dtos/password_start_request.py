from pydantic import BaseModel, Field, SecretStr


class PasswordStartRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=320)
    password: SecretStr = Field(..., min_length=1, max_length=256, description="Used once for this sign-in, held only in memory, never stored, logged or returned.")
