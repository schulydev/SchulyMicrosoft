from datetime import datetime

from pydantic import BaseModel, Field


class MeetingRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=255)
    start: datetime = Field(..., description="ISO 8601 with an offset, e.g. 2026-11-02T14:00:00+01:00.")
    end: datetime
    description: str | None = Field(None, max_length=4000)
