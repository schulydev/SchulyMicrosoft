from pydantic import BaseModel, Field

from src.application.dtos.one_note_outline_update import OneNoteOutlineUpdate


class OneNotePageUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    outlines: list[OneNoteOutlineUpdate] | None = Field(None, max_length=50)
    append: str | None = Field(None, description="Rich text appended to the page as a new text box.")
