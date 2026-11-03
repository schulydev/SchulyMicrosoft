from src.api.di.service_collection import ServiceCollection
from src.application.abstractions.i_emoji_catalogue import IEmojiCatalogue
from src.application.options.emoji_options import EmojiOptions
from src.application.queries.get_custom_emoji_query import GetCustomEmojiQuery, GetCustomEmojiHandler
from src.application.queries.get_emoji_catalogue_query import GetEmojiCatalogueQuery, GetEmojiCatalogueHandler
from src.infrastructure.teams.emoji_catalogue import EmojiCatalogue


class EmojisExtensions:
    @staticmethod
    def add_emojis(services: ServiceCollection) -> ServiceCollection:
        """The catalogue cache is process-wide."""
        services.add_instance(EmojiOptions, EmojiOptions.from_environment())
        services.add_singleton(IEmojiCatalogue, EmojiCatalogue)

        services.add_handler(GetEmojiCatalogueQuery, GetEmojiCatalogueHandler)
        services.add_handler(GetCustomEmojiQuery, GetCustomEmojiHandler)
        return services
