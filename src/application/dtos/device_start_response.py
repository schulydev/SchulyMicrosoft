from pydantic import BaseModel, Field


class DeviceStartResponse(BaseModel):
    user_code: str = Field(..., description="Shown to the user; they enter it at verification_uri.")
    verification_uri: str
    device_code: str = Field(..., description="Opaque; the caller holds it and sends it to /poll.")
    interval: int = 5
    expires_in: int = 900
    message: str | None = None
