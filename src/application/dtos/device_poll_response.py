from pydantic import BaseModel, Field

from src.application.dtos.linked_identity import LinkedIdentity


class DevicePollResponse(BaseModel):
    status: str = Field(..., description="pending | complete | error")
    refresh_token: str | None = None
    account: LinkedIdentity | None = None
    message: str | None = None
