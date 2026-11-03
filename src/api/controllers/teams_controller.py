from fastapi import APIRouter, Depends, Header, Query, Response
from mediatorx import Mediator

from src.api.controller import controller
from src.api.dependencies import get_mediator
from src.api.http_headers import HttpHeaders
from src.application.queries.list_channel_message_replies_query import ListChannelMessageRepliesQuery
from src.application.queries.list_channel_messages_query import ListChannelMessagesQuery
from src.application.queries.list_joined_teams_query import ListJoinedTeamsQuery
from src.application.queries.list_team_channels_query import ListTeamChannelsQuery
from src.application.queries.list_team_files_query import ListTeamFilesQuery
from src.domain.files.teams_path_limits import TeamsPathLimits

router = APIRouter(prefix="/api")


@controller(router)
class TeamsController:
    mediator: Mediator = Depends(get_mediator)

    @router.get("/teams", tags=["Teams files"])
    async def joined_teams(self, response: Response, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        """The joined teams `[{id, displayName, description}]`, cached 10 minutes per account."""
        response.headers["Cache-Control"] = "no-store"
        return await self.mediator.send(ListJoinedTeamsQuery(token))

    @router.get("/teams/{team_id}/channels", tags=["Teams files"])
    async def team_channels(self, team_id: str, response: Response, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER)):
        response.headers["Cache-Control"] = "no-store"
        return await self.mediator.send(ListTeamChannelsQuery(token, team_id))

    @router.get("/teams/{team_id}/files", tags=["Teams files"])
    async def team_files(self, team_id: str, response: Response, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), channel_id: str | None = Query(None), path: str | None = Query(None, max_length=TeamsPathLimits.MAX_PATH_CHARS), top: int = Query(100, ge=1, le=1000)):
        """`{driveId, folder: {id, name, path}, items}`: the team library root, a channel's folder (`channel_id`) or a sub-folder (`path`, folder names under that folder)."""
        response.headers["Cache-Control"] = "no-store"
        return await self.mediator.send(ListTeamFilesQuery(token, team_id, channel_id, path, top))

    @router.get("/teams/{team_id}/channels/{channel_id}/messages", tags=["Teams files"])
    async def channel_message_list(self, team_id: str, channel_id: str, response: Response, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), top: int = Query(30, ge=1, le=200)):
        response.headers["Cache-Control"] = "no-store"
        return await self.mediator.send(ListChannelMessagesQuery(token, team_id, channel_id, top))

    @router.get("/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies", tags=["Teams files"])
    async def channel_message_replies(self, team_id: str, channel_id: str, message_id: str, response: Response, token: str = Header(..., alias=HttpHeaders.REFRESH_TOKEN_HEADER), top: int = Query(50, ge=1, le=200)):
        response.headers["Cache-Control"] = "no-store"
        return await self.mediator.send(ListChannelMessageRepliesQuery(token, team_id, channel_id, message_id, top))
