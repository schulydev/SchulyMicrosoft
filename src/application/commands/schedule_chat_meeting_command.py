from dataclasses import dataclass, field
from datetime import timezone

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_chat_sender import IChatSender
from src.application.abstractions.i_profile_reader import IProfileReader
from src.application.dtos.meeting_request import MeetingRequest
from src.domain.errors.service_error import ServiceError
from src.domain.validation.graph_ids import GraphIds


@dataclass
class ScheduleChatMeetingCommand(ICommand[dict]):
    refresh_token: str = field(repr=False)
    chat_id: str
    body: MeetingRequest


class ScheduleChatMeetingHandler(ICommandHandler[ScheduleChatMeetingCommand, dict]):
    @staticmethod
    def _utc(value) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat()

    def __init__(self, accounts: IAccountRunner, sender: IChatSender, profile: IProfileReader):
        self._accounts = accounts
        self._sender = sender
        self._profile = profile

    async def handle(self, command: ScheduleChatMeetingCommand) -> dict:
        GraphIds.check(command.chat_id, GraphIds.CHAT_ID_PATTERN, "chat_id")
        body = command.body
        if body.end <= body.start:
            raise ServiceError(400, "end must be after start.")

        def create(note, broker):
            members = [] if command.chat_id == self._sender.SELF_CHAT else note.list(f"chats/{command.chat_id}/members")
            me = self._profile.get(note, broker)
            mine = {(me.get("mail") or "").lower(), (me.get("userPrincipalName") or "").lower()}
            attendees = [{"emailAddress": {"address": m["email"], "name": m.get("displayName") or m["email"]}, "type": "required"} for m in members if m.get("email") and m["email"].lower() not in mine]
            event = {
                "subject": body.subject,
                "start": {"dateTime": self._utc(body.start), "timeZone": "UTC"},
                "end": {"dateTime": self._utc(body.end), "timeZone": "UTC"},
                "isOnlineMeeting": True,
                "onlineMeetingProvider": "teamsForBusiness",
                "attendees": attendees,
            }
            if body.description:
                event["body"] = {"contentType": "text", "content": body.description}
            created = note.post("me/events", event)
            return {"id": created.get("id"), "subject": created.get("subject"), "start": created.get("start"), "end": created.get("end"), "webLink": created.get("webLink"), "joinUrl": (created.get("onlineMeeting") or {}).get("joinUrl"), "attendees": [a["emailAddress"] for a in attendees]}

        return await self._accounts.run(command.refresh_token, create)
