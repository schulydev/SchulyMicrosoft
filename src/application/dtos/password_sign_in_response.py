from pydantic import BaseModel, Field

from src.application.dtos.linked_identity import LinkedIdentity
from src.application.dtos.session_cookie import SessionCookie


class PasswordSignInResponse(BaseModel):
    sign_in_id: str | None = None
    status: str = Field(..., description="complete | mfa_required | push_pending | otp_required | otp_invalid | denied | timed_out | working | error")
    methods: list[str] | None = Field(None, description="Only the methods Microsoft offers for the account: push, otp.")
    number: str | None = Field(None, description="push_pending: the number to tap in Microsoft Authenticator.")
    expires_in: int | None = Field(None, description="push_pending: seconds left to approve.")
    attempts_left: int | None = None
    refresh_token: str | None = None
    session_cookies: list[SessionCookie] | None = Field(None, description="complete: the Microsoft sign-in session (cookies of login.microsoftonline.com, login.microsoft.com and login.live.com) in the shape of the app's WebView capture, for the caller to store encrypted. A credential, like refresh_token: never log it.")
    account: LinkedIdentity | None = None
    code: str | None = Field(None, description="error: invalid_credentials (wrong email or password) | password_expired (change it at office.com first) | no_password (passwordless account: use the app's Microsoft sign-in) | unsupported | blocked | otp_exhausted | rate_limited | failed")
    message: str | None = None
