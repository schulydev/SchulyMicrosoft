from fastapi import APIRouter, Depends, Header, Query, Response
from mediatorx import Mediator

from src.api.controller import controller
from src.api.dependencies import get_mediator
from src.api.http_headers import HttpHeaders
from src.api.responses.file_responses import FileResponses
from src.application.queries.get_person_photo_query import GetPersonPhotoQuery
from src.application.queries.get_user_photo_query import GetUserPhotoQuery

router = APIRouter(prefix="/api")


@controller(router)
class PeopleController:
    mediator: Mediator = Depends(get_mediator)

    @router.get("/people/photo", tags=["Microsoft 365"], response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
    async def people_photo(self, email: str = Query(..., max_length=254), token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), size: int = Query(48)):
        """A person's profile photo by e-mail address (mail senders); 404 when they have none or are outside the tenant."""
        return FileResponses.image(await self.mediator.send(GetPersonPhotoQuery(token, email, size)))

    @router.get("/users/{user_id}/photo", tags=["Microsoft 365"], response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
    async def user_photo(self, user_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), size: int = Query(64)):
        return FileResponses.user_photo(await self.mediator.send(GetUserPhotoQuery(token, user_id, size)))
