from pydantic import BaseModel


class SessionCookie(BaseModel):
    """One cookie of the Microsoft sign-in session, as the app's WebView capture sends it."""

    domain: str
    name: str
    path: str
    value: str
