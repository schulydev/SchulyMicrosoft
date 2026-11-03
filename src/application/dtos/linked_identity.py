from pydantic import BaseModel


class LinkedIdentity(BaseModel):
    id: str | None = None
    email: str | None = None
    name: str | None = None
