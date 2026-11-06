from src.api.di.service_collection import ServiceCollection
from src.application.abstractions.i_chat_presence import IChatPresence
from src.application.abstractions.i_chat_live import IChatLive
from src.application.abstractions.i_chat_reader import IChatReader
from src.application.abstractions.i_chat_sender import IChatSender
from src.application.abstractions.i_teams_chat import ITeamsChat
from src.application.commands.mark_chat_read_command import MarkChatReadCommand, MarkChatReadHandler
from src.application.commands.schedule_chat_meeting_command import ScheduleChatMeetingCommand, ScheduleChatMeetingHandler
from src.application.commands.send_chat_message_command import SendChatMessageCommand, SendChatMessageHandler
from src.application.queries.get_chat_file_pdf_query import GetChatFilePdfQuery, GetChatFilePdfHandler
from src.application.queries.get_chat_file_query import GetChatFileQuery, GetChatFileHandler
from src.application.queries.get_chat_file_thumbnail_query import GetChatFileThumbnailQuery, GetChatFileThumbnailHandler
from src.application.queries.get_chat_hosted_content_query import GetChatHostedContentQuery, GetChatHostedContentHandler
from src.application.queries.get_chat_photo_query import GetChatPhotoQuery, GetChatPhotoHandler
from src.application.queries.list_chat_messages_query import ListChatMessagesQuery, ListChatMessagesHandler
from src.application.queries.get_chat_presence_query import GetChatPresenceQuery, GetChatPresenceHandler
from src.application.queries.list_chats_query import ListChatsQuery, ListChatsHandler
from src.application.queries.open_chat_live_query import OpenChatLiveQuery, OpenChatLiveHandler
from src.application.services.chat_html_sanitizer import ChatHtmlSanitizer
from src.infrastructure.teams.chat_presence import ChatPresence
from src.infrastructure.teams.chat_live import ChatLive
from src.infrastructure.teams.chat_reader import ChatReader
from src.infrastructure.teams.chat_sender import ChatSender
from src.infrastructure.teams.teams_chat_client import TeamsChatClient


class ChatsExtensions:
    @staticmethod
    def add_chats(services: ServiceCollection) -> ServiceCollection:
        services.add_singleton(ChatHtmlSanitizer)
        services.add_singleton(ITeamsChat, TeamsChatClient)
        services.add_singleton(IChatReader, ChatReader)
        services.add_singleton(IChatLive, ChatLive)
        services.add_singleton(IChatPresence, ChatPresence)
        services.add_singleton(IChatSender, ChatSender)

        services.add_handler(ListChatsQuery, ListChatsHandler)
        services.add_handler(ListChatMessagesQuery, ListChatMessagesHandler)
        services.add_handler(GetChatHostedContentQuery, GetChatHostedContentHandler)
        services.add_handler(GetChatFileQuery, GetChatFileHandler)
        services.add_handler(GetChatFileThumbnailQuery, GetChatFileThumbnailHandler)
        services.add_handler(GetChatFilePdfQuery, GetChatFilePdfHandler)
        services.add_handler(SendChatMessageCommand, SendChatMessageHandler)
        services.add_handler(ScheduleChatMeetingCommand, ScheduleChatMeetingHandler)
        services.add_handler(MarkChatReadCommand, MarkChatReadHandler)
        services.add_handler(GetChatPhotoQuery, GetChatPhotoHandler)
        services.add_handler(OpenChatLiveQuery, OpenChatLiveHandler)
        services.add_handler(GetChatPresenceQuery, GetChatPresenceHandler)
        return services
