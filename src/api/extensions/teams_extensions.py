from src.api.di.service_collection import ServiceCollection
from src.application.abstractions.i_channel_messages import IChannelMessages
from src.application.queries.list_channel_message_replies_query import ListChannelMessageRepliesQuery, ListChannelMessageRepliesHandler
from src.application.queries.list_channel_messages_query import ListChannelMessagesQuery, ListChannelMessagesHandler
from src.application.queries.list_joined_teams_query import ListJoinedTeamsQuery, ListJoinedTeamsHandler
from src.application.queries.list_team_channels_query import ListTeamChannelsQuery, ListTeamChannelsHandler
from src.application.queries.list_team_files_query import ListTeamFilesQuery, ListTeamFilesHandler
from src.infrastructure.graph.channel_messages import ChannelMessages


class TeamsExtensions:
    @staticmethod
    def add_teams(services: ServiceCollection) -> ServiceCollection:
        services.add_singleton(IChannelMessages, ChannelMessages)

        services.add_handler(ListJoinedTeamsQuery, ListJoinedTeamsHandler)
        services.add_handler(ListTeamChannelsQuery, ListTeamChannelsHandler)
        services.add_handler(ListTeamFilesQuery, ListTeamFilesHandler)
        services.add_handler(ListChannelMessagesQuery, ListChannelMessagesHandler)
        services.add_handler(ListChannelMessageRepliesQuery, ListChannelMessageRepliesHandler)
        return services
