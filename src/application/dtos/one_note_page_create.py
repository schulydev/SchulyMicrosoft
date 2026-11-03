from pydantic import BaseModel, Field


class OneNotePageCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    html: str | None = Field(None, description="Rich text for the page body; cut down to the text formatting OneNote keeps.")
