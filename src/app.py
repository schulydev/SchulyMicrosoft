"""SchulyMicrosoft: stateless Microsoft 365 access for Schuly, over OutNote / Entrance.

The user signs in once with the device-code or browser flow on Microsoft's real page (no password
reaches this service; the one exception is the web password sign-in route, which uses the password
once in memory and never stores or logs it); the caller stores the returned FOCI refresh token and sends it back
on each read. Reads return the rotated refresh token in the X-MS-Refresh-Token header.
"""

import asyncio
import base64
import binascii
import hmac
import os
import json
import logging
import posixpath
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import timezone
from urllib.parse import quote
from collections.abc import Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.datastructures import UploadFile

import entrance
from outnote import GraphError

from src import password_signin, browser_auth, chat_html, chat_read, chat_send, config, emojis, file_pdf, file_thumbs, folder_roles, gifs, onenote, onenote_html, outnote_client, people_photos, teams_chat
from src.models import PasswordMethodRequest, PasswordOtpRequest, PasswordSignInResponse, PasswordStartRequest, BrowserCompleteRequest, BrowserStartResponse, DevicePollRequest, DevicePollResponse, DeviceStartResponse, LinkedIdentity, MailFlagRequest, MailForwardRequest, MailMessageIn, MailMoveRequest, MailReadRequest, MailReplyRequest, MeetingRequest, OneNotePageCreate, OneNotePageUpdate

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Pre-open the TLS connections to Microsoft in the background: the first call after a cold start otherwise pays DNS, TCP and TLS (and any dead-address timeout) itself.
    warm = asyncio.create_task(outnote_client.warm_up())
    sweeper = asyncio.create_task(_sweep_sign_ins())
    yield
    warm.cancel()
    sweeper.cancel()
    password_signin.store.clear()
    await outnote_client.close_shared_client()


log = logging.getLogger("schuly.microsoft")


async def _sweep_sign_ins():
    """Drop expired password sign-in jobs (and stale rate-limit windows) every few seconds."""
    while True:
        await asyncio.sleep(15)
        password_signin.store.sweep()


app = FastAPI(title="SchulyMicrosoft", description="Microsoft 365 access for Schuly via OutNote.", lifespan=lifespan)

CHAT_ID_PATTERN = re.compile(r"[A-Za-z0-9:@._=-]{1,300}")
USER_ID_PATTERN = re.compile(r"[A-Za-z0-9@._-]{1,200}")
PHOTO_SIZES = (48, 64, 96, 120, 240)
GRAPH_ID_PATTERN = re.compile(r"[A-Za-z0-9=_\-+/.]{1,512}")
EMAIL_PATTERN = re.compile(r"[^@\s<>(),;:\\\"\[\]]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.[A-Za-z]{2,}")
CONTENT_TYPE_PATTERN = re.compile(r"[A-Za-z0-9][\w.+-]{0,126}/[A-Za-z0-9][\w.+-]{0,126}")
MESSAGE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
ATTACHMENT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,100}")
DOCUMENT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,120}")
DRIVE_ITEM_PATTERN = re.compile(r"[A-Za-z0-9!=_\-+.]{1,512}")
MAX_CHAT_FILE_BYTES = 100 * 1024 * 1024
MAX_SEND_BYTES = 105 * 1024 * 1024  # a whole chat send: one 100 MB file plus the message and inline images
MAX_JSON_SEND_BYTES = 256 * 1024
TOKEN_PATTERN = re.compile(r"[\x21-\x7e]{4,16384}")  # printable ASCII, no whitespace
ACTIVE_TYPE_PARTS = ("html", "svg", "xml", "javascript", "ecmascript", "multipart")
MAX_RECIPIENTS = 100
MAX_SUBJECT = 255
MAX_BODY_BYTES = 1024 * 1024
MAX_SEND_ATTACHMENT_BYTES = 3 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
# Field lists keep list responses small: no mail body in lists (the single-message route returns it), and no unused chat metadata.
MAIL_LIST_FIELDS = "id,subject,from,toRecipients,receivedDateTime,bodyPreview,isRead,flag,hasAttachments,importance,conversationId"
CHAT_FIELDS = "id,topic,chatType,createdDateTime,lastUpdatedDateTime,webUrl,viewpoint"
# Graph answers 500 when $select is set on chat messages, so they are fetched whole.


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    # FastAPI's default 422 echoes the rejected input; for the password routes that would be the password.
    if request.url.path.startswith("/api/auth/password"):
        details = [{"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"status": "error", "code": "invalid_request", "message": "The request is invalid.", "detail": details})
    return await request_validation_exception_handler(request, exc)


@app.get("/", include_in_schema=False)
async def root():
    return {"service": "SchulyMicrosoft", "status": "ok"}


@app.post("/api/auth/device/start", response_model=DeviceStartResponse, tags=["Auth"])
async def device_start():
    try:
        data = await outnote_client.start_device_login()
    except outnote_client.MicrosoftError as ex:
        raise HTTPException(status_code=502, detail=str(ex))
    return DeviceStartResponse(
        user_code=data["user_code"],
        verification_uri=data.get("verification_uri") or data.get("verification_url"),
        device_code=data["device_code"],
        interval=data.get("interval", 5),
        expires_in=data.get("expires_in", 900),
        message=data.get("message"),
    )


@app.post("/api/auth/device/poll", response_model=DevicePollResponse, tags=["Auth"])
async def device_poll(body: DevicePollRequest):
    try:
        result = await outnote_client.poll_device_login(body.device_code)
    except outnote_client.MicrosoftError as ex:
        raise HTTPException(status_code=502, detail=str(ex))

    if result.get("access_token"):
        refresh_token = result.get("refresh_token")
        if not refresh_token:
            return DevicePollResponse(status="error", message="No refresh token in the response.")
        account = await _identity(refresh_token)
        return DevicePollResponse(status="complete", refresh_token=refresh_token, account=account)

    error = result.get("error")
    if error in ("authorization_pending", "slow_down"):
        return DevicePollResponse(status="pending", message=error)
    return DevicePollResponse(status="error", message=result.get("error_description") or error or "sign-in failed")


@app.post("/api/auth/browser/start", response_model=BrowserStartResponse, tags=["Auth"])
async def browser_start():
    url, verifier = browser_auth.build_authorize_url()
    return BrowserStartResponse(authorize_url=url, redirect_uri=browser_auth.NATIVE_REDIRECT, code_verifier=verifier)


@app.post("/api/auth/browser/complete", response_model=DevicePollResponse, tags=["Auth"])
async def browser_complete(body: BrowserCompleteRequest):
    try:
        result = await browser_auth.exchange_code(body.code, body.code_verifier)
    except outnote_client.MicrosoftError as ex:
        raise HTTPException(status_code=502, detail=str(ex))

    if not result.get("access_token") or not result.get("refresh_token"):
        return DevicePollResponse(status="error", message=result.get("error_description") or result.get("error") or "sign-in failed")
    refresh_token = result["refresh_token"]
    account = await _identity(refresh_token)
    return DevicePollResponse(status="complete", refresh_token=refresh_token, account=account)


USER_ID_PATTERN_SCHULY = re.compile(r"[A-Za-z0-9._:@-]{1,128}")


def _password_caller(request: Request) -> str:
    """Gate for the password routes: the shared service key plus the Schuly user id. Returns the user id."""
    expected = os.getenv(config.SERVICE_KEY_ENV, "")
    if not expected:
        raise HTTPException(status_code=503, detail="Password sign-in is disabled: no service key is configured.")
    given = request.headers.get(config.SERVICE_KEY_HEADER, "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Missing or invalid service key.")
    user_id = request.headers.get(config.USER_ID_HEADER, "")
    if not USER_ID_PATTERN_SCHULY.fullmatch(user_id):
        raise HTTPException(status_code=401, detail="Missing or invalid user id.")
    return user_id


SIGN_IN_WAIT = 60  # seconds /start waits for the sign-in to finish or reach the method choice
METHOD_WAIT = 30  # seconds /method waits for the push number / the code prompt
OTP_WAIT = 45  # seconds /otp waits for Microsoft's verdict
_sign_in_waiters = ThreadPoolExecutor(max_workers=password_signin.MAX_JOBS + 20, thread_name_prefix="pwd-wait")


def _sign_in_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"status": "error", "code": code, "message": message})


async def _wait_settled(job: password_signin.SignInJob, after_version: int, timeout: float) -> None:
    await asyncio.get_running_loop().run_in_executor(_sign_in_waiters, job.wait_settled, after_version, timeout)


async def _sign_in_response(job: password_signin.SignInJob) -> PasswordSignInResponse:
    """The job's current place as a response. Reads progress only; the password is not on the job."""
    snap = job.snapshot()
    state = snap["state"]
    base = {"sign_in_id": job.id}
    if state == password_signin.COMPLETE:
        if job.account is None:
            job.account = await _identity(snap["refresh_token"])
        return PasswordSignInResponse(**base, status="complete", refresh_token=snap["refresh_token"], account=job.account)
    if state == password_signin.ERROR:
        return PasswordSignInResponse(**base, status="error", code=snap["code"], message=snap["message"])
    if state == password_signin.PUSH_PENDING:
        return PasswordSignInResponse(**base, status="push_pending", number=snap["number"], expires_in=snap["expires_in"], methods=snap["methods"])
    if state == password_signin.OTP_REQUIRED:
        status = "otp_invalid" if snap.get("otp_invalid") else "otp_required"
        return PasswordSignInResponse(**base, status=status, attempts_left=snap["attempts_left"], methods=snap["methods"])
    if state in (password_signin.MFA_REQUIRED, password_signin.DENIED, password_signin.TIMED_OUT):
        if snap["notice"] == "otp_exhausted":
            return PasswordSignInResponse(**base, status="otp_invalid", attempts_left=0, methods=snap["methods"], message="Too many wrong codes; choose a method again.")
        return PasswordSignInResponse(**base, status=state, methods=snap["methods"])
    return PasswordSignInResponse(**base, status="working")


@app.post("/api/auth/password/start", response_model=PasswordSignInResponse, response_model_exclude_none=True, tags=["Auth"])
async def password_start(body: PasswordStartRequest, user_id: str = Depends(_password_caller)):
    """Sign in with the Microsoft password. The password is used once, held only in memory for this
    sign-in and never stored, cached, logged or returned. Completes straight away when Microsoft asks
    for no MFA; otherwise returns mfa_required with the methods Microsoft offers."""
    secret = entrance.Secret(body.password.get_secret_value())
    username = body.username
    body.password = None  # the request model no longer references the password
    try:
        job = password_signin.store.start(user_id, username, secret)
    except password_signin.RateLimited as ex:
        return _sign_in_error(429, "rate_limited", str(ex))
    finally:
        del secret
    await _wait_settled(job, -1, SIGN_IN_WAIT)
    snap = job.snapshot()
    if snap["state"] != password_signin.WORKING and snap.get("code") != "invalid_credentials":
        password_signin.store.promote(job)  # the password passed: this replaces the user's earlier attempt
    return await _sign_in_response(job)


@app.post("/api/auth/password/{sign_in_id}/method", response_model=PasswordSignInResponse, response_model_exclude_none=True, tags=["Auth"])
async def password_method(sign_in_id: str, body: PasswordMethodRequest, user_id: str = Depends(_password_caller)):
    """Choose (or switch to) push or otp. push -> push_pending with the number to tap; otp -> otp_required."""
    job = password_signin.store.get(sign_in_id, user_id)
    if job is None:
        return _sign_in_error(404, "not_found", "Unknown or expired sign-in.")
    version = job.snapshot()["version"]
    outcome = job.request_method(body.method)
    if outcome == "unavailable":
        return _sign_in_error(409, "method_unavailable", "Microsoft doesn't offer that method for this account.")
    if outcome == "invalid_state":
        return _sign_in_error(409, "invalid_state", "The sign-in isn't waiting for a method.")
    if outcome == "ok":
        await _wait_settled(job, version, METHOD_WAIT)
    return await _sign_in_response(job)


@app.post("/api/auth/password/{sign_in_id}/otp", response_model=PasswordSignInResponse, response_model_exclude_none=True, tags=["Auth"])
async def password_otp(sign_in_id: str, body: PasswordOtpRequest, user_id: str = Depends(_password_caller)):
    """Submit the authenticator code. complete, or otp_invalid with attempts_left (3 tries per method choice)."""
    job = password_signin.store.get(sign_in_id, user_id)
    if job is None:
        return _sign_in_error(404, "not_found", "Unknown or expired sign-in.")
    code = re.sub(r"[\s-]", "", body.code)
    if not code.isdigit() or not 6 <= len(code) <= 8:
        return _sign_in_error(422, "invalid_request", "The code must be 6 digits.")
    version = job.snapshot()["version"]
    if not job.submit_code(code):
        return _sign_in_error(409, "invalid_state", "The sign-in isn't waiting for a code.")
    await _wait_settled(job, version, OTP_WAIT)
    return await _sign_in_response(job)


@app.get("/api/auth/password/{sign_in_id}", response_model=PasswordSignInResponse, response_model_exclude_none=True, tags=["Auth"])
async def password_status(sign_in_id: str, user_id: str = Depends(_password_caller)):
    job = password_signin.store.get(sign_in_id, user_id)
    if job is None:
        return _sign_in_error(404, "not_found", "Unknown or expired sign-in.")
    return await _sign_in_response(job)


@app.delete("/api/auth/password/{sign_in_id}", status_code=204, tags=["Auth"])
async def password_cancel(sign_in_id: str, user_id: str = Depends(_password_caller)):
    password_signin.store.remove(sign_in_id, user_id)
    return Response(status_code=204)


@app.get("/api/me", tags=["Microsoft 365"])
async def me(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    return await _read(response, token, lambda note: note.me())


@app.get("/api/mail", tags=["Microsoft 365"])
async def mail(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), folder: str = Query("inbox"), top: int = Query(25, ge=1, le=500), skip: int = Query(0, ge=0, le=10000), unread: bool = Query(False), search: str | None = Query(None)):
    _check_id(folder, GRAPH_ID_PATTERN, "folder")
    if skip and search:
        raise HTTPException(status_code=400, detail="skip cannot be combined with search.")
    if not skip:
        return await _read(response, token, lambda note: note.emails(folder=_seg(folder), top=top, unread=unread, search=search, select=MAIL_LIST_FIELDS))
    # Paging: newest first, `skip` messages in. Graph does not allow $skip together with $search.
    params = {"$top": min(top, 100), "$skip": skip, "$select": MAIL_LIST_FIELDS, "$orderby": "receivedDateTime desc"}
    if unread:
        params["$filter"] = "isRead eq false"
    return await _read(response, token, lambda note: note.list(f"me/mailFolders/{_seg(folder)}/messages", params, limit=top))


# Fixed paths (folders/send/drafts) are declared before the {message_id} routes so they can never be read as an id.
@app.get("/api/mail/folders", tags=["Microsoft 365"])
async def mail_folders(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    return await _read(response, token, _folders, with_broker=True)


@app.post("/api/mail/send", status_code=204, tags=["Microsoft 365"])
async def mail_send(body: MailMessageIn, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    args = _message_args(body)
    return await _no_content(token, lambda note: note.send_mail(**args))


@app.post("/api/mail/drafts", status_code=201, tags=["Microsoft 365"])
async def mail_create_draft(body: MailMessageIn, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    args = _message_args(body)
    return await _read(response, token, lambda note: note.create_draft(**args))


@app.post("/api/mail/drafts/{message_id}/send", status_code=204, tags=["Microsoft 365"])
async def mail_send_draft(message_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(message_id, GRAPH_ID_PATTERN, "message_id")
    return await _no_content(token, lambda note: note.send_draft(_seg(message_id)))


@app.get("/api/mail/{message_id}", tags=["Microsoft 365"])
async def mail_message(message_id: str, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(message_id, GRAPH_ID_PATTERN, "message_id")
    return await _read(response, token, lambda note: note.email(_seg(message_id)))


@app.get("/api/mail/{message_id}/attachments", tags=["Microsoft 365"])
async def mail_attachments(message_id: str, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(message_id, GRAPH_ID_PATTERN, "message_id")
    return await _read(response, token, lambda note: [_attachment_meta(a) for a in note.list(f"me/messages/{_seg(message_id)}/attachments")])


@app.get("/api/mail/{message_id}/attachments/{attachment_id}", tags=["Microsoft 365"], response_class=Response, responses={200: {"content": {"application/octet-stream": {}}}})
async def mail_attachment(message_id: str, attachment_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(message_id, GRAPH_ID_PATTERN, "message_id")
    _check_id(attachment_id, GRAPH_ID_PATTERN, "attachment_id")

    def fetch(note):
        # Look the attachment up in the metadata list first: it carries the type and size, so an oversized one is refused before downloading it.
        meta = next((a for a in note.list(f"me/messages/{_seg(message_id)}/attachments") if a.get("id") == attachment_id), None)
        if meta is None:
            raise HTTPException(status_code=404, detail="Attachment not found.")
        if (meta.get("size") or 0) > MAX_DOWNLOAD_BYTES:
            raise HTTPException(status_code=413, detail="The attachment is larger than 25 MB.")
        try:
            data = note.download_attachment(_seg(message_id), _seg(attachment_id))
        except ValueError as ex:
            raise HTTPException(status_code=422, detail=str(ex))
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise HTTPException(status_code=413, detail="The attachment is larger than 25 MB.")
        return meta, data

    carrier = Response()
    meta, data = await _read(carrier, token, fetch)
    name = _safe_name(meta.get("name"))
    is_item = str(meta.get("@odata.type", "")).endswith("itemAttachment")
    content_type = _safe_content_type("message/rfc822" if is_item else meta.get("contentType"))
    if is_item and "." not in name:
        name += ".eml"
    headers = _token_headers(carrier)
    headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name, safe='')}"
    headers["Cache-Control"] = "no-store"
    headers["X-Content-Type-Options"] = "nosniff"
    headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return Response(content=data, media_type=content_type, headers=headers)


@app.get("/api/mail/{message_id}/attachments/{attachment_id}/pdf", tags=["Files as PDF"], response_class=StreamingResponse, responses={200: {"content": {"application/pdf": {}}}})
async def mail_attachment_pdf(message_id: str, attachment_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    """A mail attachment (Word, Excel, PowerPoint, OpenDocument, RTF, CSV) converted to PDF through a temporary file in the app folder. 415 when the type can't be converted."""
    _check_id(message_id, GRAPH_ID_PATTERN, "message_id")
    _check_id(attachment_id, GRAPH_ID_PATTERN, "attachment_id")

    def convert(note, broker):
        meta = next((a for a in note.list(f"me/messages/{_seg(message_id)}/attachments") if a.get("id") == attachment_id), None)
        if meta is None:
            raise HTTPException(status_code=404, detail="Attachment not found.")
        if str(meta.get("@odata.type", "")).endswith("itemAttachment") or not file_pdf.is_convertible(meta.get("name")):
            raise HTTPException(status_code=415, detail="This file type cannot be converted to PDF.")
        if (meta.get("size") or 0) > MAX_DOWNLOAD_BYTES:
            raise HTTPException(status_code=413, detail="The attachment is larger than 25 MB.")
        try:
            data = note.download_attachment(_seg(message_id), _seg(attachment_id))
        except ValueError as ex:
            raise HTTPException(status_code=422, detail=str(ex))
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise HTTPException(status_code=413, detail="The attachment is larger than 25 MB.")
        return meta.get("name"), _converted(lambda: file_pdf.bytes_pdf(note, broker, data, meta.get("name")))

    return await _pdf(token, convert)


@app.post("/api/mail/{message_id}/reply", status_code=204, tags=["Microsoft 365"])
async def mail_reply(message_id: str, body: MailReplyRequest, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(message_id, GRAPH_ID_PATTERN, "message_id")
    _check_text(body.comment, "comment")
    return await _no_content(token, lambda note: note.reply(_seg(message_id), body.comment, reply_all=body.replyAll))


@app.post("/api/mail/{message_id}/forward", status_code=204, tags=["Microsoft 365"])
async def mail_forward(message_id: str, body: MailForwardRequest, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(message_id, GRAPH_ID_PATTERN, "message_id")
    _check_text(body.comment, "comment")
    to = _addresses(body.to, "to")
    if not to:
        raise HTTPException(status_code=400, detail="At least one recipient is required.")
    if len(to) > MAX_RECIPIENTS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_RECIPIENTS} recipients are allowed.")
    return await _no_content(token, lambda note: note.forward(_seg(message_id), to, body.comment))


@app.post("/api/mail/{message_id}/read", tags=["Microsoft 365"])
async def mail_mark_read(message_id: str, body: MailReadRequest, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(message_id, GRAPH_ID_PATTERN, "message_id")
    return await _read(response, token, lambda note: note.mark_read(_seg(message_id), body.read) or {"isRead": body.read})


@app.post("/api/mail/{message_id}/flag", tags=["Microsoft 365"])
async def mail_flag(message_id: str, body: MailFlagRequest, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(message_id, GRAPH_ID_PATTERN, "message_id")
    return await _read(response, token, lambda note: note.flag(_seg(message_id), body.status) or {"flag": {"flagStatus": body.status}})


@app.post("/api/mail/{message_id}/move", tags=["Microsoft 365"])
async def mail_move(message_id: str, body: MailMoveRequest, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(message_id, GRAPH_ID_PATTERN, "message_id")
    _check_id(body.folder, GRAPH_ID_PATTERN, "folder")
    return await _read(response, token, lambda note: note.move_email(_seg(message_id), _seg(body.folder)))


@app.delete("/api/mail/{message_id}", status_code=204, tags=["Microsoft 365"])
async def mail_delete(message_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(message_id, GRAPH_ID_PATTERN, "message_id")
    return await _no_content(token, lambda note: note.delete_email(_seg(message_id)))


@app.get("/api/calendar", tags=["Microsoft 365"])
async def calendar(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), top: int = Query(25, le=500), start: str | None = Query(None), end: str | None = Query(None)):
    return await _read(response, token, lambda note: note.events(start=start, end=end, top=top))


@app.get("/api/files", tags=["Microsoft 365"])
async def files(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), path: str = Query("root"), top: int = Query(100, le=1000)):
    if _has_dot_segment(path) or "%" in path:
        raise HTTPException(status_code=400, detail="Invalid path.")
    return await _read(response, token, lambda note: note.files(path=path, top=top))


@app.get("/api/chats", tags=["Microsoft 365"])
async def chats(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), top: int = Query(25, le=200)):
    def fetch(note, broker):
        items = note.list("me/chats", {"$top": min(top, 50), "$select": CHAT_FIELDS, "$expand": "members,lastMessagePreview", "$orderby": "lastMessagePreview/createdDateTime desc"}, limit=top)
        try:
            return teams_chat.mark_images(broker, items)
        except Exception as ex:
            # The picture flag is a nicety; the chat list never fails over it.
            log.info("chat picture lookup failed: %s", type(ex).__name__)
            for item in items:
                item["hasImage"] = False
            return items

    return await _read(response, token, fetch, with_broker=True)


@app.get("/api/notebooks", tags=["Microsoft 365"])
async def notebooks(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    return await _read(response, token, lambda note: note.notebooks())


@app.get("/api/onenote/notebooks", tags=["OneNote"])
async def onenote_notebooks(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), teams: bool = Query(True)):
    """The person's own notebooks, then each joined team's (class notebooks), with where they come from and whether they may be changed."""
    return await _onenote(response, token, lambda note, broker: onenote.notebooks(note, broker, teams))


@app.get("/api/onenote/notebooks/{notebook_id}/sections", tags=["OneNote"])
async def onenote_sections(notebook_id: str, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    """A notebook's sections and section groups as a tree."""
    _check_onenote_id(notebook_id, "notebook_id")
    return await _onenote(response, token, lambda note, broker: onenote.tree(note, broker, notebook_id))


@app.get("/api/onenote/sections/{section_id}/pages", tags=["OneNote"])
async def onenote_pages(section_id: str, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), top: int = Query(50, ge=1, le=100), skip: int = Query(0, ge=0, le=5000)):
    """One section's pages in OneNote's order, subpages with their level; `nextSkip` pages on."""
    _check_onenote_id(section_id, "section_id")
    return await _onenote(response, token, lambda note, broker: onenote.pages(note, section_id, top, skip))


@app.post("/api/onenote/sections/{section_id}/pages", status_code=201, tags=["OneNote"])
async def onenote_create_page(section_id: str, body: OneNotePageCreate, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_onenote_id(section_id, "section_id")
    _check_text(body.html or "", "html")
    return await _onenote(response, token, lambda note, broker: onenote.create_page(note, broker, section_id, body.title, body.html))


@app.get("/api/onenote/pages/{page_id}", tags=["OneNote"])
async def onenote_page(page_id: str, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    """A page as sanitized HTML (pictures by resource id, ink as SVG), its resources and its text boxes."""
    _check_onenote_id(page_id, "page_id")
    return await _onenote(response, token, lambda note, broker: onenote.page(note, page_id))


@app.patch("/api/onenote/pages/{page_id}", tags=["OneNote"])
async def onenote_update_page(page_id: str, body: OneNotePageUpdate, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    """Replaces the title and the text of editable text boxes, and appends text, as Graph PATCH commands. Answers the page as it is after the save."""
    _check_onenote_id(page_id, "page_id")
    outlines = [{"id": o.id, "html": o.html} for o in body.outlines or []]
    for item in outlines:
        _check_id(item["id"], onenote_html.SAFE_ID, "outline id")
    _check_text((body.append or "") + "".join(o["html"] for o in outlines), "html")
    return await _onenote(response, token, lambda note, broker: onenote.update_page(note, broker, page_id, body.title, outlines, body.append))


@app.delete("/api/onenote/pages/{page_id}", status_code=204, tags=["OneNote"])
async def onenote_delete_page(page_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_onenote_id(page_id, "page_id")
    carrier = Response()
    await _onenote(carrier, token, lambda note, broker: onenote.delete_page(note, broker, page_id))
    return Response(status_code=204, headers=_token_headers(carrier))


@app.get("/api/onenote/resources/{resource_id}", tags=["OneNote"], response_class=Response, responses={200: {"content": {"image/png": {}, "application/octet-stream": {}}}})
async def onenote_resource(resource_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), kind: str = Query("image"), name: str | None = Query(None, max_length=255)):
    """A picture (kind=image, served inline only when it is a PNG, JPEG, GIF or WEBP) or an attached file (kind=file, always a download) of a page."""
    _check_onenote_id(resource_id, "resource_id")
    if kind not in ("image", "file"):
        raise HTTPException(status_code=400, detail="kind must be image or file")

    def fetch(note, broker):
        try:
            return onenote.resource(broker, resource_id, MAX_DOWNLOAD_BYTES)
        except onenote.ResourceTooLarge:
            raise HTTPException(status_code=413, detail="The resource is larger than 25 MB.")

    carrier = Response()
    data = await _onenote(carrier, token, fetch)
    headers = _token_headers(carrier)
    # The rotated refresh token may ride on this response, so nothing may store it; the plugin caches images itself.
    headers["Cache-Control"] = "no-store"
    headers["X-Content-Type-Options"] = "nosniff"
    if kind == "image":
        mime = chat_send.image_type((data or b"")[:12])
        if mime is None:
            raise HTTPException(status_code=415, detail="The resource is not a PNG, JPEG, GIF or WEBP image.", headers=headers)
        return Response(content=data, media_type=mime, headers=headers)
    headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(_safe_name(name), safe='')}"
    headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return Response(content=data, media_type="application/octet-stream", headers=headers)


@app.get("/api/onenote/search", tags=["OneNote"])
async def onenote_search(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), q: str = Query(..., min_length=1, max_length=100), notebook: str | None = Query(None), top: int = Query(25, ge=1, le=50)):
    """Pages whose title holds `q` (Graph has no OneNote content search), in one notebook or everywhere. `partial` is true when a big class notebook was only searched in part."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="q is empty.")
    if notebook:
        _check_onenote_id(notebook, "notebook")
    return await _onenote(response, token, lambda note, broker: onenote.search(note, broker, q, notebook, top))


@app.get("/api/chats/{chat_id}/messages", tags=["Microsoft 365"])
async def chat_messages(chat_id: str, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), top: int = Query(30, ge=1, le=300)):
    _check_id(chat_id, CHAT_ID_PATTERN, "chat_id")
    # No $select: Graph answers 500 for chat messages when one is set.
    return await _read(response, token, lambda note, broker: chat_read.enrich(note, broker, note.list(f"me/chats/{chat_id}/messages", {"$top": min(top, 50)}, limit=top)), with_broker=True)


@app.get("/api/chats/{chat_id}/messages/{message_id}/hostedContents/{hosted_id:path}", tags=["Microsoft 365"], response_class=Response, responses={200: {"content": {"image/png": {}}}})
async def chat_hosted_content(chat_id: str, message_id: str, hosted_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(chat_id, CHAT_ID_PATTERN, "chat_id")
    _check_id(message_id, MESSAGE_ID_PATTERN, "message_id")
    _check_id(hosted_id, GRAPH_ID_PATTERN, "hosted_id")
    carrier = Response()
    data = await _read(carrier, token, lambda note: note.get(f"{chat_read.message_path(chat_id, message_id)}/hostedContents/{_seg(hosted_id)}/$value", raw="bytes"))
    headers = _token_headers(carrier)
    mime = chat_send.image_type((data or b"")[:12])
    if mime is None:
        # Only images are proxied; anything else a hosted content could hold is refused.
        raise HTTPException(status_code=415, detail="The hosted content is not a PNG, JPEG, GIF or WEBP image.", headers=headers)
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The image is larger than 25 MB.", headers=headers)
    # The rotated refresh token may ride on this response, so nothing may store it; the plugin caches the image itself.
    headers["Cache-Control"] = "no-store"
    headers["X-Content-Type-Options"] = "nosniff"
    return Response(content=data, media_type=mime, headers=headers)


@app.get("/api/chats/{chat_id}/messages/{message_id}/files/{attachment_id}", tags=["Microsoft 365"], response_class=StreamingResponse, responses={200: {"content": {"application/octet-stream": {}}}})
async def chat_file(chat_id: str, message_id: str, attachment_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(chat_id, CHAT_ID_PATTERN, "chat_id")
    _check_id(message_id, MESSAGE_ID_PATTERN, "message_id")
    _check_id(attachment_id, ATTACHMENT_ID_PATTERN, "attachment_id")

    def resolve(note):
        message = note.get(chat_read.message_path(chat_id, message_id))
        ref = next((f for f in chat_html.reference_files(message) if f.get("id") == attachment_id), None)
        if ref is None:
            raise HTTPException(status_code=404, detail="File not found in the message.")
        item = note.get(chat_read.drive_item_path(ref["contentUrl"], "name,size,file,@microsoft.graph.downloadUrl"))
        if (item.get("size") or 0) > MAX_CHAT_FILE_BYTES:
            raise HTTPException(status_code=413, detail="The file is larger than 100 MB.")
        url = item.get("@microsoft.graph.downloadUrl")
        if not url:
            raise HTTPException(status_code=404, detail="The file has no download link.")
        return item, url

    carrier = Response()
    item, url = await _read(carrier, token, resolve)
    headers = _token_headers(carrier)
    name = _safe_name(item.get("name"))
    headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name, safe='')}"
    headers["Cache-Control"] = "no-store"
    headers["X-Content-Type-Options"] = "nosniff"
    headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    # The download URL is pre-authorized and short-lived; the bytes stream through without being held.
    return StreamingResponse(outnote_client.stream_download(url, MAX_CHAT_FILE_BYTES), media_type=_safe_content_type((item.get("file") or {}).get("mimeType")), headers=headers)


@app.get("/api/chats/{chat_id}/messages/{message_id}/files/{attachment_id}/thumbnail", tags=["Microsoft 365"], response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
async def chat_file_thumbnail(chat_id: str, message_id: str, attachment_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), size: str = Query("medium")):
    """The preview image of a file shared in a message (`files[].hasThumbnail`): JPEG, PNG or WEBP; 404 when the file has none. size is small, medium or large."""
    _check_id(chat_id, CHAT_ID_PATTERN, "chat_id")
    _check_id(message_id, MESSAGE_ID_PATTERN, "message_id")
    _check_id(attachment_id, ATTACHMENT_ID_PATTERN, "attachment_id")
    _check_thumbnail_size(size)

    def fetch(note, broker):
        message = note.get(chat_read.message_path(chat_id, message_id))
        ref = next((f for f in chat_html.reference_files(message) if f.get("id") == attachment_id), None)
        if ref is None or not file_thumbs.is_share_url(ref["contentUrl"]):
            return None
        return file_thumbs.chat_file_thumbnail(note, broker, ref["contentUrl"], size)

    return await _thumbnail(token, fetch)


@app.get("/api/files/{item_id}/thumbnail", tags=["Microsoft 365"], response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
async def drive_thumbnail(item_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), size: str = Query("medium")):
    """The preview image of a OneDrive item (an `id` from /api/files); 404 when it has none."""
    _check_id(item_id, DRIVE_ITEM_PATTERN, "item_id")
    _check_thumbnail_size(size)
    return await _thumbnail(token, lambda note, broker: file_thumbs.drive_item_thumbnail(note, item_id, size))


def _check_thumbnail_size(size: str):
    if size not in file_thumbs.SIZES:
        raise HTTPException(status_code=400, detail=f"size must be one of {', '.join(file_thumbs.SIZES)}")


async def _thumbnail(token: str, fetch):
    carrier = Response()
    data = await _read(carrier, token, fetch, with_broker=True)
    headers = _token_headers(carrier)
    mime = file_thumbs.image_type((data or b"")[:12])
    if mime is None:
        raise HTTPException(status_code=404, detail="The file has no thumbnail.", headers=headers)
    # The rotated refresh token may ride on this response, so nothing may store it; the plugin caches the image itself.
    headers["Cache-Control"] = "no-store"
    headers["X-Content-Type-Options"] = "nosniff"
    return Response(content=data, media_type=mime, headers=headers)


@app.get("/api/files/{item_id}/pdf", tags=["Files as PDF"], response_class=StreamingResponse, responses={200: {"content": {"application/pdf": {}}}})
async def drive_item_pdf(item_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    """A OneDrive item (an `id` from /api/files) converted to PDF by Microsoft 365. 415 when the type can't be converted."""
    _check_id(item_id, DRIVE_ITEM_PATTERN, "item_id")

    def convert(note, broker):
        item = note.get(f"me/drive/items/{_seg(item_id)}", {"$select": "id,name,size,file"})
        _check_source(item)
        return item.get("name"), _converted(lambda: file_pdf.drive_item_pdf(note, item_id))

    return await _pdf(token, convert)


@app.get("/api/chats/{chat_id}/messages/{message_id}/files/{attachment_id}/pdf", tags=["Files as PDF"], response_class=StreamingResponse, responses={200: {"content": {"application/pdf": {}}}})
async def chat_file_pdf(chat_id: str, message_id: str, attachment_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    """A file shared in a chat message (`files[].id`) converted to PDF where it lives (SharePoint / OneDrive). 415 when the type can't be converted."""
    _check_id(chat_id, CHAT_ID_PATTERN, "chat_id")
    _check_id(message_id, MESSAGE_ID_PATTERN, "message_id")
    _check_id(attachment_id, ATTACHMENT_ID_PATTERN, "attachment_id")

    def convert(note, broker):
        message = note.get(chat_read.message_path(chat_id, message_id))
        ref = next((f for f in chat_html.reference_files(message) if f.get("id") == attachment_id), None)
        if ref is None:
            raise HTTPException(status_code=404, detail="File not found in the message.")
        if not file_thumbs.is_share_url(ref.get("contentUrl")):
            raise HTTPException(status_code=415, detail="Only files in SharePoint or OneDrive can be converted.")
        item = note.get(chat_read.drive_item_path(ref["contentUrl"], "id,name,size,file,parentReference"))
        _check_source(item)
        drive_id = (item.get("parentReference") or {}).get("driveId")
        if not file_thumbs.safe_graph_id(drive_id) or not file_thumbs.safe_graph_id(item.get("id")):
            raise HTTPException(status_code=404, detail="File not found.")
        return item.get("name"), _converted(lambda: file_pdf.drive_item_pdf(note, item["id"], drive_id))

    return await _pdf(token, convert)


@app.post("/api/convert/pdf", tags=["Files as PDF"], response_class=StreamingResponse, responses={200: {"content": {"application/pdf": {}}}})
async def convert_pdf(request: Request, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), name: str = Query(..., min_length=1, max_length=255)):
    """The request body (raw bytes, up to 105 MB) converted to PDF; `name` is the file name, whose extension picks the type (Word, Excel, PowerPoint, OpenDocument, RTF, CSV).

    For files that aren't in a drive: they go to a temporary file in the app folder, which is deleted right after the conversion."""
    _check_token(token)
    safe = _safe_name(name)
    if not file_pdf.is_convertible(safe):
        raise HTTPException(status_code=415, detail="This file type cannot be converted to PDF.")
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > MAX_SEND_BYTES):
        raise HTTPException(status_code=413, detail="The file is larger than the conversion limit.")
    body = bytearray()
    async for chunk in _limited(request, MAX_SEND_BYTES).stream():
        body.extend(chunk)
    if not body:
        raise HTTPException(status_code=400, detail="The body is empty.")
    data = bytes(body)
    del body
    return await _pdf(token, lambda note, broker: (safe, _converted(lambda: file_pdf.bytes_pdf(note, broker, data, safe))))


def _check_source(item: dict):
    if not isinstance(item, dict) or item.get("file") is None:
        raise HTTPException(status_code=404, detail="File not found.")
    if not file_pdf.is_convertible(item.get("name")):
        raise HTTPException(status_code=415, detail="This file type cannot be converted to PDF.")
    if (item.get("size") or 0) > MAX_CHAT_FILE_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 100 MB.")


def _converted(run):
    try:
        return run()
    except file_pdf.ConvertError as ex:
        raise HTTPException(status_code=ex.status, detail=str(ex))


async def _pdf(token: str, convert):
    """Runs `convert(note, broker) -> (source name, spooled PDF)` and streams the PDF: inline (it was checked to be a PDF), sandboxed, never stored."""
    carrier = Response()
    name, spooled = await _read(carrier, token, convert, with_broker=True)
    headers = _token_headers(carrier)
    pdf_name = posixpath.splitext(_safe_name(name))[0] + ".pdf"
    headers["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(pdf_name, safe='')}"
    # The rotated refresh token may ride on this response, so nothing may store it.
    headers["Cache-Control"] = "no-store"
    headers["X-Content-Type-Options"] = "nosniff"
    headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    size = spooled.seek(0, 2)
    spooled.seek(0)
    headers["Content-Length"] = str(size)

    def body():
        try:
            while chunk := spooled.read(64 * 1024):
                yield chunk
        finally:
            spooled.close()

    return StreamingResponse(body(), media_type="application/pdf", headers=headers)


@app.get("/api/emojis/catalogue", tags=["Emojis"])
async def emoji_catalogue(response: Response, locale: str = Query("default", max_length=20)):
    """Teams' emoji catalogue `{locale, version, assetBase, sizes, fps, categories: [{id, title, emojis: [{id, shortcuts, unicode, title, keywords, diverse, animated, staticUrl, animatedUrl, frames, frameMs, firstFrame, etag}]}], custom}`.

    Public data (no token involved), cached for 24 hours per locale. The URLs are 30 px; swap the size in the file name (20, 30, 40, 50, 60, 100) for another. An animated emoji is a vertical sprite strip of `frames` square frames shown at `frameMs` each."""
    name = emojis.normalize_locale(locale)
    if name is None:
        raise HTTPException(status_code=400, detail="Invalid locale.")
    try:
        cat = await asyncio.to_thread(emojis.catalogue, name)
    except emojis.EmojiError as ex:
        raise HTTPException(status_code=502, detail=str(ex))
    response.headers["Cache-Control"] = "public, max-age=3600"
    return cat.payload()


@app.get("/api/emojis/custom/{document_id}", tags=["Emojis"], response_class=Response, responses={200: {"content": {"image/png": {}}}})
async def custom_emoji(document_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), animated: bool = Query(True)):
    """A tenant custom emoji's picture (`emojis[].documentId` of a message emoji with kind custom). Animated is a GIF/WEBP that plays in a plain image tag."""
    _check_id(document_id, DOCUMENT_ID_PATTERN, "document_id")

    def fetch(note, broker):
        try:
            return teams_chat.custom_emoji(broker, document_id, animated)
        except teams_chat.ChatServiceError as ex:
            if ex.status in (401, 403):
                return None
            raise

    carrier = Response()
    data = await _read(carrier, token, fetch, with_broker=True)
    headers = _token_headers(carrier)
    mime = chat_send.image_type((data or b"")[:12])
    if mime is None:
        raise HTTPException(status_code=404, detail="No such custom emoji.", headers=headers)
    headers["Cache-Control"] = "no-store"
    headers["X-Content-Type-Options"] = "nosniff"
    return Response(content=data, media_type=mime, headers=headers)


@app.post("/api/chats/{chat_id}/messages", tags=["Microsoft 365"])
async def send_chat_message(chat_id: str, request: Request, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    """JSON `{content, contentType, importance, mentions, gif}` (or the legacy `{text}`), or multipart/form-data with the same fields (mentions and gif as JSON strings) plus `images` and `files` parts."""
    _check_id(chat_id, CHAT_ID_PATTERN, "chat_id")
    _check_token(token)
    multipart = request.headers.get("content-type", "").lower().startswith("multipart/form-data")
    cap = MAX_SEND_BYTES if multipart else MAX_JSON_SEND_BYTES
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > cap):
        raise HTTPException(status_code=413, detail="The message is larger than the send limit.")
    request = _limited(request, cap)
    form = None
    try:
        if multipart:
            # Starlette spools each file part to a temporary file past 1 MB; form.close() deletes them.
            form = await request.form(max_files=chat_send.MAX_IMAGES + chat_send.MAX_FILES, max_fields=20, max_part_size=256 * 1024)
            fields = {k: form.get(k) for k in ("content", "text", "contentType", "importance") if isinstance(form.get(k), str)}
            fields["mentions"] = _json_field(form.get("mentions"), "mentions")
            fields["gif"] = _json_field(form.get("gif"), "gif")
            images = [_upload(f) for f in form.getlist("images") if isinstance(f, UploadFile)]
            files = [_upload(f) for f in form.getlist("files") if isinstance(f, UploadFile)]
        else:
            try:
                fields = await request.json()
            except ValueError:
                raise HTTPException(status_code=400, detail="The body must be JSON or multipart/form-data.")
            if not isinstance(fields, dict):
                raise HTTPException(status_code=400, detail="The body must be a JSON object.")
            images, files = [], []
        msg = _outgoing(fields, images, files)

        def send(note, broker):
            try:
                created = chat_send.send(note, chat_id, msg)
            except chat_send.SendError as ex:
                raise HTTPException(status_code=ex.status, detail=str(ex))
            return chat_read.enrich(note, broker, [created or {}])[0]

        return await _read(response, token, send, with_broker=True)
    finally:
        if form is not None:
            await form.close()


@app.post("/api/chats/{chat_id}/meeting", status_code=201, tags=["Microsoft 365"])
async def schedule_chat_meeting(chat_id: str, body: MeetingRequest, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    """Creates a Teams meeting in the user's calendar with the chat's members as attendees."""
    _check_id(chat_id, CHAT_ID_PATTERN, "chat_id")
    if body.end <= body.start:
        raise HTTPException(status_code=400, detail="end must be after start.")

    def create(note):
        members = [] if chat_id == chat_send.SELF_CHAT else note.list(f"chats/{chat_id}/members")
        me = note.get("me", {"$select": "mail,userPrincipalName"})
        mine = {(me.get("mail") or "").lower(), (me.get("userPrincipalName") or "").lower()}
        attendees = [{"emailAddress": {"address": m["email"], "name": m.get("displayName") or m["email"]}, "type": "required"} for m in members if m.get("email") and m["email"].lower() not in mine]
        event = {
            "subject": body.subject,
            "start": {"dateTime": _utc(body.start), "timeZone": "UTC"},
            "end": {"dateTime": _utc(body.end), "timeZone": "UTC"},
            "isOnlineMeeting": True,
            "onlineMeetingProvider": "teamsForBusiness",
            "attendees": attendees,
        }
        if body.description:
            event["body"] = {"contentType": "text", "content": body.description}
        created = note.post("me/events", event)
        return {"id": created.get("id"), "subject": created.get("subject"), "start": created.get("start"), "end": created.get("end"), "webLink": created.get("webLink"), "joinUrl": (created.get("onlineMeeting") or {}).get("joinUrl"), "attendees": [a["emailAddress"] for a in attendees]}

    return await _read(response, token, create)


@app.get("/api/gifs/search", tags=["GIFs"])
async def gif_search(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), q: str = Query(..., min_length=1, max_length=100), limit: int = Query(24, ge=1, le=50)):
    return await _gifs(response, token, q, limit)


@app.get("/api/gifs/trending", tags=["GIFs"])
async def gif_trending(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), limit: int = Query(24, ge=1, le=50)):
    return await _gifs(response, token, None, limit)


async def _gifs(response: Response, token: str, query: str | None, limit: int):
    _check_token(token)

    def run(note, broker):
        # Only a live Microsoft sign-in may spend the GIF key: the token must mint a Graph token (cached after the first call), and each account is rate limited.
        broker(config.DEVICE_CLIENT_ID)
        if not gifs.allow(broker):
            raise HTTPException(status_code=429, detail="Too many GIF searches; wait a minute.", headers={"Retry-After": "60"})
        try:
            return gifs.search(query, limit)
        except gifs.GifSearchUnavailable as ex:
            raise HTTPException(status_code=503, detail=str(ex))
        except Exception as ex:
            raise HTTPException(status_code=502, detail=f"GIF search failed: {type(ex).__name__}")

    return await _read(response, token, run, with_broker=True)


def _check_token(token: str):
    if not TOKEN_PATTERN.fullmatch(token):
        raise HTTPException(status_code=401, detail="Missing or malformed Microsoft token.")


def _utc(value) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def _limited(request: Request, cap: int) -> Request:
    """The request with its body cut off past `cap` bytes, whatever Content-Length claims."""
    received = 0
    upstream = request.receive

    async def receive():
        nonlocal received
        message = await upstream()
        if message.get("type") == "http.request":
            received += len(message.get("body", b""))
            if received > cap:
                raise HTTPException(status_code=413, detail="The message is larger than the send limit.")
        return message

    return Request(request.scope, receive)


def _json_field(value, name: str):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{name} must be a JSON string.")
    try:
        return json.loads(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{name} is not valid JSON.")


def _upload(part: UploadFile) -> chat_send.Upload:
    size = part.size
    if size is None:
        part.file.seek(0, 2)
        size = part.file.tell()
    part.file.seek(0)
    return chat_send.Upload(name=part.filename or "file", file=part.file, size=size, content_type=part.content_type)


def _outgoing(fields: dict, images: list, files: list) -> chat_send.OutgoingMessage:
    content = fields.get("content")
    if content is None:
        content = fields.get("text")
    mentions = fields.get("mentions") or []
    gif = fields.get("gif")
    if not isinstance(content, (str, type(None))) or not isinstance(mentions, list) or not isinstance(gif, (dict, type(None))):
        raise HTTPException(status_code=400, detail="Invalid message fields.")
    content_type, importance = fields.get("contentType") or "text", fields.get("importance") or None
    if not isinstance(content_type, str) or not isinstance(importance, (str, type(None))):
        raise HTTPException(status_code=400, detail="Invalid message fields.")
    msg = chat_send.OutgoingMessage(content=content or "", content_type=content_type, importance=importance, mentions=mentions, gif=gif, images=images, files=files)
    try:
        return chat_send.validate(msg)
    except chat_send.SendError as ex:
        raise HTTPException(status_code=ex.status, detail=str(ex))


@app.post("/api/chats/{chat_id}/read", status_code=204, tags=["Microsoft 365"])
async def mark_chat_read(chat_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(chat_id, CHAT_ID_PATTERN, "chat_id")
    carrier = Response()
    await _read(carrier, token, lambda note: note.mark_chat_read(chat_id))
    return Response(status_code=204, headers=_token_headers(carrier))


@app.get("/api/chats/{chat_id}/photo", tags=["Microsoft 365"], response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
async def chat_photo(chat_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(chat_id, CHAT_ID_PATTERN, "chat_id")

    def fetch(note, broker):
        try:
            return teams_chat.picture(broker, chat_id)
        except teams_chat.ChatServiceError as ex:
            if ex.status in (401, 403):
                # Teams refused this account (tenant policy, no Teams licence): there is no picture to show.
                return None
            raise

    carrier = Response()
    data = await _read(carrier, token, fetch, with_broker=True)
    headers = _token_headers(carrier)
    if not data:
        raise HTTPException(status_code=404, detail="The chat has no picture.", headers=headers)
    headers["Cache-Control"] = "no-store"
    headers["X-Content-Type-Options"] = "nosniff"
    return Response(content=data, media_type=_image_type(data), headers=headers)


@app.get("/api/people/photo", tags=["Microsoft 365"], response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
async def people_photo(email: str = Query(..., max_length=254), token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), size: int = Query(48)):
    """A person's profile photo by e-mail address (mail senders); 404 when they have none or are outside the tenant."""
    if not EMAIL_PATTERN.fullmatch(email.strip()):
        raise HTTPException(status_code=400, detail="Invalid email.")
    if size not in PHOTO_SIZES:
        raise HTTPException(status_code=400, detail=f"size must be one of {', '.join(str(s) for s in PHOTO_SIZES)}")

    def fetch(note, broker):
        try:
            return people_photos.photo(note, broker, email, size)
        except people_photos.Throttled:
            raise HTTPException(status_code=429, detail="Microsoft is throttling photo requests.", headers={"Retry-After": "30"})

    carrier = Response()
    data = await _read(carrier, token, fetch, with_broker=True)
    headers = _token_headers(carrier)
    if not data:
        raise HTTPException(status_code=404, detail="No profile photo for that address.", headers=headers)
    headers["Cache-Control"] = "no-store"
    headers["X-Content-Type-Options"] = "nosniff"
    return Response(content=data, media_type=_image_type(data), headers=headers)


@app.get("/api/users/{user_id}/photo", tags=["Microsoft 365"], response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
async def user_photo(user_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), size: int = Query(64)):
    _check_id(user_id, USER_ID_PATTERN, "user_id")
    if size not in PHOTO_SIZES:
        raise HTTPException(status_code=400, detail=f"size must be one of {', '.join(str(s) for s in PHOTO_SIZES)}")

    def fetch(note):
        for path in (f"users/{user_id}/photos/{size}x{size}/$value", f"users/{user_id}/photo/$value"):
            try:
                return note.get(path, raw="bytes")
            except GraphError as ex:
                if ex.status != 404:
                    raise
        return None

    carrier = Response()
    data = await _read(carrier, token, fetch)
    headers = _token_headers(carrier)
    if not data:
        raise HTTPException(status_code=404, detail="The user has no profile photo.", headers=headers)
    # The rotated refresh token rides on this response, so nothing may store it; the caller caches the photo itself.
    headers["Cache-Control"] = "no-store"
    return Response(content=data, media_type=_image_type(data), headers=headers)


async def _identity(refresh_token: str) -> LinkedIdentity:
    try:
        note, _ = outnote_client.build_client(refresh_token)
        profile = await asyncio.to_thread(note.me)
        return LinkedIdentity(id=profile.get("id"), email=profile.get("mail") or profile.get("userPrincipalName"), name=profile.get("displayName"))
    except Exception:
        return LinkedIdentity()


async def _read(response: Response, refresh_token: str, action: Callable[..., object], with_broker: bool = False):
    note, broker = outnote_client.build_client(refresh_token)
    try:
        data = await asyncio.to_thread(action, note, broker) if with_broker else await asyncio.to_thread(action, note)
    except HTTPException as ex:
        # The token may have rotated before the action refused; keep it for the caller.
        if broker.refresh_token and broker.refresh_token != refresh_token:
            ex.headers = {**(ex.headers or {}), config.REFRESH_TOKEN_HEADER: broker.refresh_token}
        raise
    except Exception as ex:
        if "invalid_grant" in str(ex):
            raise HTTPException(status_code=401, detail="The Microsoft sign-in expired; reconnect the account.")
        if isinstance(ex, GraphError) and ex.status == 404:
            raise HTTPException(status_code=404, detail="Not found in Microsoft 365.")
        raise HTTPException(status_code=502, detail=f"Microsoft Graph error: {ex}")
    # Hand back the rotated refresh token so the caller can persist it.
    if broker.refresh_token and broker.refresh_token != refresh_token:
        response.headers[config.REFRESH_TOKEN_HEADER] = broker.refresh_token
    return data


async def _no_content(token: str, action: Callable[[object], object]):
    carrier = Response()
    await _read(carrier, token, action)
    return Response(status_code=204, headers=_token_headers(carrier))


def _seg(value: str) -> str:
    # OutNote does not escape path segments; ids may hold "+" or "/", so percent-encode them for Graph.
    return quote(value, safe="")


def _check_text(value: str, name: str):
    if len(value.encode("utf-8")) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail=f"{name} is larger than 1 MB.")


def _addresses(values: list[str] | None, name: str) -> list[str]:
    out = [v.strip() for v in values or []]
    for address in out:
        if len(address) > 254 or not EMAIL_PATTERN.fullmatch(address):
            raise HTTPException(status_code=400, detail=f"Invalid address in {name}.")
    return out


def _safe_content_type(value: str | None) -> str:
    # Attachments are untrusted: anything that could run as a page or script is served as opaque bytes.
    content_type = (value or "").split(";")[0].strip().lower()
    if not CONTENT_TYPE_PATTERN.fullmatch(content_type) or any(part in content_type for part in ACTIVE_TYPE_PARTS):
        return "application/octet-stream"
    return content_type


def _safe_name(name: str | None) -> str:
    cleaned = re.sub(r'[\x00-\x1f\x7f\\/:*?"<>|]', "_", name or "")
    return cleaned.strip(" .")[:255] or "attachment"


def _message_args(body: MailMessageIn) -> dict:
    to, cc, bcc = _addresses(body.to, "to"), _addresses(body.cc, "cc"), _addresses(body.bcc, "bcc")
    if not to and not cc and not bcc:
        raise HTTPException(status_code=400, detail="At least one recipient is required.")
    if len(to) + len(cc) + len(bcc) > MAX_RECIPIENTS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_RECIPIENTS} recipients are allowed.")
    if len(body.subject) > MAX_SUBJECT:
        raise HTTPException(status_code=400, detail=f"The subject may be at most {MAX_SUBJECT} characters.")
    _check_text(body.body, "body")
    attachments, total = [], 0
    for item in body.attachments or []:
        try:
            data = base64.b64decode(item.contentBase64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail="An attachment is not valid base64.")
        total += len(data)
        if total > MAX_SEND_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413, detail="Attachments may total at most 3 MB.")
        attachments.append((_safe_name(item.name), data))
    return {"to": to, "subject": body.subject, "body": body.body, "html": body.html, "cc": cc or None, "bcc": bcc or None, "attachments": attachments or None}


def _attachment_meta(item: dict) -> dict:
    keep = ("id", "name", "contentType", "size", "isInline", "contentId")
    return {k: item.get(k) for k in keep}


def _folders(note, broker) -> list[dict]:
    roles = folder_roles.cached(broker)
    if roles is not None:
        return _folder_tree(note.mail_folders(include_children=True), roles)
    # First list this hour: resolve the well-known roles in parallel with the folder walk, so they cost no extra round trip.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(folder_roles.lookup, note)
        flat = note.mail_folders(include_children=True)
        try:
            roles = pending.result()
        except Exception as ex:
            # Roles only label folders; the tree is still useful without them.
            log.info("mail folder role lookup failed: %s", type(ex).__name__)
            roles = {}
    folder_roles.remember(broker, roles)
    return _folder_tree(flat, roles)


def _folder_tree(flat: list[dict], roles: dict[str, str] | None = None) -> list[dict]:
    # OutNote walks the subfolders breadth-first into a flat list; rebuild the nesting from parentFolderId.
    roles = roles or {}
    nodes = {f["id"]: {**f, "wellKnownName": roles.get(f["id"]), "childFolders": []} for f in flat}
    roots = []
    for f in flat:
        parent = nodes.get(f.get("parentFolderId"))
        (parent["childFolders"] if parent is not None and f["id"] != f.get("parentFolderId") else roots).append(nodes[f["id"]])
    return roots


def _check_onenote_id(value: str, name: str):
    """OneNote ids (bare, or `<group>@<id>` for a team's notebook) through the shared validator, then the scope check."""
    _check_id(value, onenote.ID_PATTERN, name)
    if not onenote.is_id(value):
        raise HTTPException(status_code=400, detail=f"Invalid {name}.")


async def _onenote(response: Response, token: str, action: Callable[..., object]):
    """`_read` for OneNote: refusals OneNote gives as such keep their meaning instead of becoming a 502."""

    def run(note, broker):
        try:
            return action(note, broker)
        except onenote.OneNoteError as ex:
            raise HTTPException(status_code=ex.status, detail=str(ex))
        except GraphError as ex:
            if ex.status == 403:
                raise HTTPException(status_code=403, detail="OneNote refused access to this notebook.")
            if ex.status in (400, 409, 422):
                raise HTTPException(status_code=422, detail=f"OneNote refused the request: {str(ex)[:200]}")
            raise

    return await _read(response, token, run, with_broker=True)


def _check_id(value: str, pattern: re.Pattern, name: str):
    """The one validator for ids that become upstream path segments: the pattern, and no dot segment ("." / ".." collapse in URL handling and retarget the call)."""
    if not pattern.fullmatch(value) or _has_dot_segment(value):
        raise HTTPException(status_code=400, detail=f"Invalid {name}.")


def _has_dot_segment(value: str) -> bool:
    return ".." in value or any(part == "." for part in re.split(r"[/\\]", value))


def _token_headers(carrier: Response) -> dict[str, str]:
    rotated = carrier.headers.get(config.REFRESH_TOKEN_HEADER)
    return {config.REFRESH_TOKEN_HEADER: rotated} if rotated else {}


def _image_type(data: bytes) -> str:
    # OutNote's public getter returns only the body bytes, so sniff the format from the magic number.
    if data[1:4] == b"PNG":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"
