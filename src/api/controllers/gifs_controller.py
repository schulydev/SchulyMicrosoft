from fastapi import APIRouter, Depends, Header, Query
from mediatorx import Mediator

from src.api.controller import controller
from src.api.dependencies import get_mediator
from src.api.http_headers import HttpHeaders
from src.application.queries.search_gifs_query import SearchGifsQuery

router = APIRouter(prefix="/api")


@controller(router)
class GifsController:
    mediator: Mediator = Depends(get_mediator)

    @router.get("/gifs/search", tags=["GIFs"])
    async def gif_search(self, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), q: str = Query(..., min_length=1, max_length=100), limit: int = Query(24, ge=1, le=50)):
        return await self.mediator.send(SearchGifsQuery(token, q, limit))

    @router.get("/gifs/trending", tags=["GIFs"])
    async def gif_trending(self, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), limit: int = Query(24, ge=1, le=50)):
        return await self.mediator.send(SearchGifsQuery(token, None, limit))
