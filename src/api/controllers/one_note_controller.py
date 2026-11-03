from fastapi import APIRouter, Depends, Header, Query, Response
from mediatorx import Mediator

from src.api.controller import controller
from src.api.dependencies import get_mediator
from src.api.http_headers import HttpHeaders
from src.api.responses.file_responses import FileResponses
from src.application.commands.create_one_note_page_command import CreateOneNotePageCommand
from src.application.commands.delete_one_note_page_command import DeleteOneNotePageCommand
from src.application.commands.update_one_note_page_command import UpdateOneNotePageCommand
from src.application.dtos.one_note_page_create import OneNotePageCreate
from src.application.dtos.one_note_page_update import OneNotePageUpdate
from src.application.queries.get_one_note_page_query import GetOneNotePageQuery
from src.application.queries.get_one_note_resource_query import GetOneNoteResourceQuery
from src.application.queries.get_one_note_sections_query import GetOneNoteSectionsQuery
from src.application.queries.list_notebooks_query import ListNotebooksQuery
from src.application.queries.list_one_note_notebooks_query import ListOneNoteNotebooksQuery
from src.application.queries.list_one_note_pages_query import ListOneNotePagesQuery
from src.application.queries.search_one_note_query import SearchOneNoteQuery

router = APIRouter(prefix="/api")


@controller(router)
class OneNoteController:
    mediator: Mediator = Depends(get_mediator)

    @router.get("/notebooks", tags=["Microsoft 365"])
    async def notebooks(self, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        return await self.mediator.send(ListNotebooksQuery(token))

    @router.get("/onenote/notebooks", tags=["OneNote"])
    async def onenote_notebooks(self, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), teams: bool = Query(True)):
        """The person's own notebooks, then each joined team's (class notebooks), with where they come from and whether they may be changed."""
        return await self.mediator.send(ListOneNoteNotebooksQuery(token, teams))

    @router.get("/onenote/notebooks/{notebook_id}/sections", tags=["OneNote"])
    async def onenote_sections(self, notebook_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        """A notebook's sections and section groups as a tree."""
        return await self.mediator.send(GetOneNoteSectionsQuery(token, notebook_id))

    @router.get("/onenote/sections/{section_id}/pages", tags=["OneNote"])
    async def onenote_pages(self, section_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), top: int = Query(50, ge=1, le=100), skip: int = Query(0, ge=0, le=5000)):
        """One section's pages in OneNote's order, subpages with their level; `nextSkip` pages on."""
        return await self.mediator.send(ListOneNotePagesQuery(token, section_id, top, skip))

    @router.post("/onenote/sections/{section_id}/pages", status_code=201, tags=["OneNote"])
    async def onenote_create_page(self, section_id: str, body: OneNotePageCreate, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        return await self.mediator.send(CreateOneNotePageCommand(token, section_id, body))

    @router.get("/onenote/pages/{page_id}", tags=["OneNote"])
    async def onenote_page(self, page_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        """A page as sanitized HTML (pictures by resource id, ink as SVG), its resources and its text boxes."""
        return await self.mediator.send(GetOneNotePageQuery(token, page_id))

    @router.patch("/onenote/pages/{page_id}", tags=["OneNote"])
    async def onenote_update_page(self, page_id: str, body: OneNotePageUpdate, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        """Replaces the title and the text of editable text boxes, and appends text, as Graph PATCH commands. Answers the page as it is after the save."""
        return await self.mediator.send(UpdateOneNotePageCommand(token, page_id, body))

    @router.delete("/onenote/pages/{page_id}", status_code=204, tags=["OneNote"])
    async def onenote_delete_page(self, page_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        await self.mediator.send(DeleteOneNotePageCommand(token, page_id))
        return Response(status_code=204)

    @router.get("/onenote/resources/{resource_id}", tags=["OneNote"], response_class=Response, responses={200: {"content": {"image/png": {}, "application/octet-stream": {}}}})
    async def onenote_resource(self, resource_id: str, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), kind: str = Query("image"), name: str | None = Query(None, max_length=255)):
        """A picture (kind=image, served inline only when it is a PNG, JPEG, GIF or WEBP) or an attached file (kind=file, always a download) of a page."""
        content = await self.mediator.send(GetOneNoteResourceQuery(token, resource_id, kind, name))
        return FileResponses.image(content) if kind == "image" else FileResponses.attachment(content)

    @router.get("/onenote/search", tags=["OneNote"])
    async def onenote_search(self, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), q: str = Query(..., min_length=1, max_length=100), notebook: str | None = Query(None), top: int = Query(25, ge=1, le=50)):
        """Pages whose title holds `q` (Graph has no OneNote content search), in one notebook or everywhere. `partial` is true when a big class notebook was only searched in part."""
        return await self.mediator.send(SearchOneNoteQuery(token, q, notebook, top))
