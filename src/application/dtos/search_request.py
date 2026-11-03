from typing import Literal

from pydantic import Field

from src.application.dtos.files_search_request import FilesSearchRequest


class SearchRequest(FilesSearchRequest):
    types: list[Literal["files", "mail", "chats", "channels"]] = Field(["files", "mail", "chats", "channels"], min_length=1, max_length=4)
