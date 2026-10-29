from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class DeviceStartResponse(BaseModel):
    user_code: str = Field(..., description="Shown to the user; they enter it at verification_uri.")
    verification_uri: str
    device_code: str = Field(..., description="Opaque; the caller holds it and sends it to /poll.")
    interval: int = 5
    expires_in: int = 900
    message: str | None = None


class DevicePollRequest(BaseModel):
    device_code: str


class BrowserStartResponse(BaseModel):
    authorize_url: str = Field(..., description="Open in a WebView; wait for the redirect to redirect_uri carrying ?code=.")
    redirect_uri: str = Field(..., description="The URL the code comes back on; the app watches for it and then closes the WebView.")
    code_verifier: str = Field(..., description="Opaque PKCE value; the caller holds it and sends it to /complete.")


class BrowserCompleteRequest(BaseModel):
    code: str
    code_verifier: str


class LinkedIdentity(BaseModel):
    id: str | None = None
    email: str | None = None
    name: str | None = None


class DevicePollResponse(BaseModel):
    status: str = Field(..., description="pending | complete | error")
    refresh_token: str | None = None
    account: LinkedIdentity | None = None
    message: str | None = None


class PasswordStartRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=320)
    password: SecretStr = Field(..., min_length=1, max_length=256, description="Used once for this sign-in, held only in memory, never stored, logged or returned.")


class PasswordMethodRequest(BaseModel):
    method: Literal["push", "otp"]


class PasswordOtpRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=12, description="The authenticator app code (digits; spaces are ignored).")


class PasswordSignInResponse(BaseModel):
    sign_in_id: str | None = None
    status: str = Field(..., description="complete | mfa_required | push_pending | otp_required | otp_invalid | denied | timed_out | working | error")
    methods: list[str] | None = Field(None, description="Only the methods Microsoft offers for the account: push, otp.")
    number: str | None = Field(None, description="push_pending: the number to tap in Microsoft Authenticator.")
    expires_in: int | None = Field(None, description="push_pending: seconds left to approve.")
    attempts_left: int | None = None
    refresh_token: str | None = None
    account: LinkedIdentity | None = None
    code: str | None = Field(None, description="error: invalid_credentials | unsupported | blocked | rate_limited | failed")
    message: str | None = None


class MeetingRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=255)
    start: datetime = Field(..., description="ISO 8601 with an offset, e.g. 2026-11-02T14:00:00+01:00.")
    end: datetime
    description: str | None = Field(None, max_length=4000)


class MailAttachmentIn(BaseModel):
    name: str
    contentType: str | None = None
    contentBase64: str


class MailMessageIn(BaseModel):
    to: list[str] = Field(default_factory=list)
    cc: list[str] | None = None
    bcc: list[str] | None = None
    subject: str
    body: str
    html: bool = False
    attachments: list[MailAttachmentIn] | None = None


class MailReplyRequest(BaseModel):
    comment: str
    replyAll: bool = False


class MailForwardRequest(BaseModel):
    to: list[str]
    comment: str = ""


class MailReadRequest(BaseModel):
    read: bool


class MailFlagRequest(BaseModel):
    status: Literal["flagged", "complete", "notFlagged"]


class MailMoveRequest(BaseModel):
    folder: str


class OneNotePageCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    html: str | None = Field(None, description="Rich text for the page body; cut down to the text formatting OneNote keeps.")


class OneNoteOutlineUpdate(BaseModel):
    id: str = Field(..., min_length=1, max_length=200, description="An editable outline id from the page content.")
    html: str


class OneNotePageUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    outlines: list[OneNoteOutlineUpdate] | None = Field(None, max_length=50)
    append: str | None = Field(None, description="Rich text appended to the page as a new text box.")
