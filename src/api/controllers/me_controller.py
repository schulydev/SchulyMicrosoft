from fastapi import APIRouter, Depends, Header, Query
from mediatorx import Mediator

from src.api.controller import controller
from src.api.dependencies import get_mediator
from src.api.http_headers import HttpHeaders
from src.application.queries.get_profile_query import GetProfileQuery
from src.application.queries.list_calendar_events_query import ListCalendarEventsQuery

router = APIRouter(prefix="/api")


@controller(router)
class MeController:
    mediator: Mediator = Depends(get_mediator)

    @router.get("/me", tags=["Microsoft 365"])
    async def me(self, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        return await self.mediator.send(GetProfileQuery(token))

    @router.get("/calendar", tags=["Microsoft 365"])
    async def calendar(self, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), top: int = Query(25, le=500), start: str | None = Query(None), end: str | None = Query(None)):
        return await self.mediator.send(ListCalendarEventsQuery(token, top, start, end))
