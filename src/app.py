"""SchulyMicrosoft: stateless Microsoft 365 access for Schuly, over OutNote / Entrance.

The user signs in once with the device-code flow on Microsoft's real page (no password
reaches this service); the caller stores the returned FOCI refresh token and sends it back
on each read. Reads return the rotated refresh token in the X-MS-Refresh-Token header.
"""

import asyncio
from collections.abc import Callable

from fastapi import FastAPI, Header, HTTPException, Query, Response

from src import config, outnote_client
from src.models import DevicePollRequest, DevicePollResponse, DeviceStartResponse, LinkedIdentity

app = FastAPI(title="SchulyMicrosoft", description="Microsoft 365 access for Schuly via OutNote.")


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


@app.get("/api/me", tags=["Microsoft 365"])
async def me(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    return await _read(response, token, lambda note: note.me())


@app.get("/api/mail", tags=["Microsoft 365"])
async def mail(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), folder: str = Query("inbox"), top: int = Query(25, le=100), unread: bool = Query(False), search: str | None = Query(None)):
    return await _read(response, token, lambda note: note.emails(folder=folder, top=top, unread=unread, search=search))


@app.get("/api/calendar", tags=["Microsoft 365"])
async def calendar(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), top: int = Query(25, le=100)):
    return await _read(response, token, lambda note: note.events(top=top))


@app.get("/api/files", tags=["Microsoft 365"])
async def files(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), path: str = Query("root"), top: int = Query(100, le=200)):
    return await _read(response, token, lambda note: note.files(path=path, top=top))


@app.get("/api/chats", tags=["Microsoft 365"])
async def chats(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER), top: int = Query(25, le=50)):
    return await _read(response, token, lambda note: note.chats(top=top))


@app.get("/api/notebooks", tags=["Microsoft 365"])
async def notebooks(response: Response, token: str = Header(..., alias=config.REFRESH_TOKEN_HEADER)):
    return await _read(response, token, lambda note: note.notebooks())


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
    except Exception as ex:
        if "invalid_grant" in str(ex):
            raise HTTPException(status_code=401, detail="The Microsoft sign-in expired; reconnect the account.")
        raise HTTPException(status_code=502, detail=f"Microsoft Graph error: {ex}")
    # Hand back the rotated refresh token so the caller can persist it.
    if broker.refresh_token and broker.refresh_token != refresh_token:
        response.headers[config.REFRESH_TOKEN_HEADER] = broker.refresh_token
    return data
