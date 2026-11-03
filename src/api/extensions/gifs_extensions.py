from src.api.di.service_collection import ServiceCollection
from src.application.abstractions.i_gif_search import IGifSearch
from src.application.options.giphy_options import GiphyOptions
from src.application.queries.search_gifs_query import SearchGifsQuery, SearchGifsHandler
from src.infrastructure.giphy.gif_search import GifSearch


class GifsExtensions:
    @staticmethod
    def add_gifs(services: ServiceCollection) -> ServiceCollection:
        """The search result cache is process-wide."""
        services.add_instance(GiphyOptions, GiphyOptions.from_environment())
        services.add_singleton(IGifSearch, GifSearch)

        services.add_handler(SearchGifsQuery, SearchGifsHandler)
        return services
