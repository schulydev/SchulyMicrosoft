from fastapi import APIRouter, Depends, Header, Response
from mediatorx import Mediator

from src.api.controller import controller
from src.api.dependencies import get_mediator
from src.api.http_headers import HttpHeaders
from src.application.dtos.files_search_request import FilesSearchRequest
from src.application.dtos.search_request import SearchRequest
from src.application.queries.search_query import SearchQuery

router = APIRouter(prefix="/api")


@controller(router)
class SearchController:
    mediator: Mediator = Depends(get_mediator)

    @router.post("/files/search", tags=["Search"])
    async def files_search(self, body: FilesSearchRequest, response: Response, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        """SearchResult with file hits only. With `teamId` that team's library is searched. The query never reaches a log."""
        response.headers["Cache-Control"] = "no-store"
        return await self.mediator.send(SearchQuery(token, body.q, ["files"], body.start, body.size, body.teamId))

    @router.post("/search", tags=["Search"])
    async def search_all(self, body: SearchRequest, response: Response, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        """SearchResult over files, mail, chats and channel posts (`types`), each hit with the place it lives in."""
        response.headers["Cache-Control"] = "no-store"
        return await self.mediator.send(SearchQuery(token, body.q, body.types, body.start, body.size, body.teamId))
