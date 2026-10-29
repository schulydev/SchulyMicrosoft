"""SchulyMicrosoft: stateless Microsoft 365 access for Schuly, over OutNote / Entrance.

The user signs in once with the device-code flow on Microsoft's real page (no password
reaches this service); the caller stores the returned FOCI refresh token and sends it back
on each read. Reads return the rotated refresh token in the X-MS-Refresh-Token header.
"""

import asyncio
import re
from collections.abc import Callable

from fastapi import FastAPI, Header, HTTPException, Query, Response

from outnote import GraphError

from src import browser_auth, config, outnote_client
from src.models import BrowserCompleteRequest, BrowserStartResponse, DevicePollRequest, DevicePollResponse, DeviceStartResponse, LinkedIdentity, SendMessageRequest

app = FastAPI(title="SchulyMicrosoft", description="Microsoft 365 access for Schuly via OutNote.")

CHAT_ID_PATTERN = re.compile(r"[A-Za-z0-9:@._=-]{1,300}")
USER_ID_PATTERN = re.compile(r"[A-Za-z0-9@._-]{1,200}")
PHOTO_SIZES = (48, 64, 96, 120, 240)


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
async def mail(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), folder: str = Query("inbox"), top: int = Query(25, le=100), unread: bool = Query(False), search: str | None = Query(None)):
    return await _read(response, token, lambda note: note.emails(folder=folder, top=top, unread=unread, search=search))


@app.get("/api/calendar", tags=["Microsoft 365"])
async def calendar(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), top: int = Query(25, le=500), start: str | None = Query(None), end: str | None = Query(None)):
    return await _read(response, token, lambda note: note.events(start=start, end=end, top=top))


@app.get("/api/files", tags=["Microsoft 365"])
async def files(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), path: str = Query("root"), top: int = Query(100, le=200)):
    return await _read(response, token, lambda note: note.files(path=path, top=top))


@app.get("/api/chats", tags=["Microsoft 365"])
async def chats(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), top: int = Query(25, le=50)):
    return await _read(response, token, lambda note: note.chats(top=top))


@app.get("/api/notebooks", tags=["Microsoft 365"])
async def notebooks(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    return await _read(response, token, lambda note: note.notebooks())


@app.get("/api/chats/{chat_id}/messages", tags=["Microsoft 365"])
async def chat_messages(chat_id: str, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), top: int = Query(30, ge=1, le=50)):
    _check_id(chat_id, CHAT_ID_PATTERN, "chat_id")
    return await _read(response, token, lambda note: note.chat_messages(chat_id, top=top))


@app.post("/api/chats/{chat_id}/messages", tags=["Microsoft 365"])
async def send_chat_message(chat_id: str, body: SendMessageRequest, response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(chat_id, CHAT_ID_PATTERN, "chat_id")
    return await _read(response, token, lambda note: note.send_chat_message(chat_id, body.text))


@app.post("/api/chats/{chat_id}/read", status_code=204, tags=["Microsoft 365"])
async def mark_chat_read(chat_id: str, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    _check_id(chat_id, CHAT_ID_PATTERN, "chat_id")
    carrier = Response()
    await _read(carrier, token, lambda note: note.mark_chat_read(chat_id))
    return Response(status_code=204, headers=_token_headers(carrier))


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
    headers["Cache-Control"] = "private, max-age=3600"
    return Response(content=data, media_type=_image_type(data), headers=headers)


async def _identity(refresh_token: str) -> LinkedIdentity:
    try:
        note, _ = outnote_client.build_client(refresh_token)
        profile = await asyncio.to_thread(note.me)
        return LinkedIdentity(id=profile.get("id"), email=profile.get("mail") or profile.get("userPrincipalName"), name=profile.get("displayName"))
    except Exception:
        return LinkedIdentity()


async def _read(response: Response, refresh_token: str, action: Callable[[object], object]):
    note, broker = outnote_client.build_client(refresh_token)
    try:
        data = await asyncio.to_thread(action, note)
    except HTTPException:
        raise
    except Exception as ex:
        if "invalid_grant" in str(ex):
            raise HTTPException(status_code=401, detail="The Microsoft sign-in expired; reconnect the account.")
        raise HTTPException(status_code=502, detail=f"Microsoft Graph error: {ex}")
    # Hand back the rotated refresh token so the caller can persist it.
    if broker.refresh_token and broker.refresh_token != refresh_token:
        response.headers[config.REFRESH_TOKEN_HEADER] = broker.refresh_token
    return data


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
