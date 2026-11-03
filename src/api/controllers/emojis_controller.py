from fastapi import APIRouter, Depends, Header, Query, Response
from mediatorx import Mediator

from src.api.controller import controller
from src.api.dependencies import get_mediator
from src.api.http_headers import HttpHeaders
from src.api.responses.file_responses import FileResponses
from src.application.queries.get_custom_emoji_query import GetCustomEmojiQuery
from src.application.queries.get_emoji_catalogue_query import GetEmojiCatalogueQuery

router = APIRouter(prefix="/api")


@controller(router)
class EmojisController:
    mediator: Mediator = Depends(get_mediator)

    @router.get("/emojis/catalogue", tags=["Emojis"])
    async def emoji_catalogue(self, response: Response, locale: str = Query("default", max_length=20)):
        """Teams' emoji catalogue `{locale, version, assetBase, sizes, fps, categories: [{id, title, emojis: [{id, shortcuts, unicode, title, keywords, diverse, animated, staticUrl, animatedUrl, frames, frameMs, firstFrame, etag}]}], custom}`.

        Public data (no token involved), cached for 24 hours per locale. The URLs are 30 px; swap the size in the file name (20, 30, 40, 50, 60, 100) for another. An animated emoji is a vertical sprite strip of `frames` square frames shown at `frameMs` each."""
        catalogue = await self.mediator.send(GetEmojiCatalogueQuery(locale))
        response.headers["Cache-Control"] = "public, max-age=3600"
        return catalogue

    @router.get("/emojis/custom/{document_id}", tags=["Emojis"], response_class=Response, responses={200: {"content": {"image/png": {}}}})
    async def custom_emoji(self, document_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), animated: bool = Query(True)):
        """A tenant custom emoji's picture (`emojis[].documentId` of a message emoji with kind custom). Animated is a GIF/WEBP that plays in a plain image tag."""
        return FileResponses.image(await self.mediator.send(GetCustomEmojiQuery(token, document_id, animated)))
