from pydantic import BaseModel, Field


class OneNoteOutlineUpdate(BaseModel):
    id: str = Field(..., min_length=1, max_length=200, description="An editable outline id from the page content.")
    html: str
