from src.api.di.service_collection import ServiceCollection
from src.application.abstractions.i_graph_search import IGraphSearch
from src.application.queries.search_query import SearchQuery, SearchHandler
from src.infrastructure.graph.graph_search import GraphSearch


class SearchExtensions:
    @staticmethod
    def add_search(services: ServiceCollection) -> ServiceCollection:
        services.add_singleton(IGraphSearch, GraphSearch)

        services.add_handler(SearchQuery, SearchHandler)
        return services
