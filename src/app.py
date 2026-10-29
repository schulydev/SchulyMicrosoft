"""SchulyMicrosoft: stateless Microsoft 365 access for Schuly, over OutNote / Entrance.

The user signs in once with the device-code flow on Microsoft's real page (no password
reaches this service); the caller stores the returned FOCI refresh token and sends it back
on each read. Reads return the rotated refresh token in the X-MS-Refresh-Token header.
"""

import asyncio
import base64
import binascii
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import timezone
from urllib.parse import quote
from collections.abc import Callable

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile

from outnote import GraphError

from src import browser_auth, chat_html, chat_read, chat_send, config, folder_roles, gifs, outnote_client, teams_chat
from src.models import BrowserCompleteRequest, BrowserStartResponse, DevicePollRequest, DevicePollResponse, DeviceStartResponse, LinkedIdentity, MailFlagRequest, MailForwardRequest, MailMessageIn, MailMoveRequest, MailReadRequest, MailReplyRequest, MeetingRequest

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Pre-open the TLS connections to Microsoft in the background: the first call after a cold start otherwise pays DNS, TCP and TLS (and any dead-address timeout) itself.
    warm = asyncio.create_task(outnote_client.warm_up())
    yield
    warm.cancel()
    await outnote_client.close_shared_client()


log = logging.getLogger("schuly.microsoft")

app = FastAPI(title="SchulyMicrosoft", description="Microsoft 365 access for Schuly via OutNote.", lifespan=lifespan)

CHAT_ID_PATTERN = re.compile(r"[A-Za-z0-9:@._=-]{1,300}")
USER_ID_PATTERN = re.compile(r"[A-Za-z0-9@._-]{1,200}")
PHOTO_SIZES = (48, 64, 96, 120, 240)
GRAPH_ID_PATTERN = re.compile(r"[A-Za-z0-9=_\-+/.]{1,512}")
EMAIL_PATTERN = re.compile(r"[^@\s<>(),;:\\\"\[\]]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.[A-Za-z]{2,}")
CONTENT_TYPE_PATTERN = re.compile(r"[A-Za-z0-9][\w.+-]{0,126}/[A-Za-z0-9][\w.+-]{0,126}")
MESSAGE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
ATTACHMENT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,100}")
MAX_CHAT_FILE_BYTES = 100 * 1024 * 1024
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
    headers["Cache-Control"] = "private, max-age=3600"
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


@app.post("/api/chats/{chat_id}/messages", tags=["Microsoft 365"])
async def send_chat_message(chat_id: str, request: Request, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    """JSON `{content, contentType, importance, mentions, gif}` (or the legacy `{text}`), or multipart/form-data with the same fields (mentions and gif as JSON strings) plus `images` and `files` parts."""
    _check_id(chat_id, CHAT_ID_PATTERN, "chat_id")
    form = None
    try:
        if request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
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
async def gif_search(q: str = Query(..., min_length=1, max_length=100), limit: int = Query(24, ge=1, le=50)):
    return await _gifs(q, limit)


@app.get("/api/gifs/trending", tags=["GIFs"])
async def gif_trending(limit: int = Query(24, ge=1, le=50)):
    return await _gifs(None, limit)


async def _gifs(query: str | None, limit: int):
    try:
        return await asyncio.to_thread(gifs.search, query, limit)
    except gifs.GifSearchUnavailable as ex:
        raise HTTPException(status_code=503, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"GIF search failed: {type(ex).__name__}")


def _utc(value) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


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


def _check_id(value: str, pattern: re.Pattern, name: str):
    if not pattern.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"Invalid {name}.")


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
