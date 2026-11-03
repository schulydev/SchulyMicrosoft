from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class FilesSearchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    q: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    start: int = Field(0, ge=0, le=5000, alias="from")
    size: int = Field(25, ge=1, le=50)
    teamId: str | None = Field(None, max_length=36)
