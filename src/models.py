from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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
