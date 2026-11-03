from src.api.di.service_collection import ServiceCollection
from src.application.abstractions.i_profile_reader import IProfileReader
from src.application.queries.get_profile_query import GetProfileQuery, GetProfileHandler
from src.application.queries.list_calendar_events_query import ListCalendarEventsQuery, ListCalendarEventsHandler
from src.infrastructure.microsoft.profile_reader import ProfileReader


class MeExtensions:
    @staticmethod
    def add_me(services: ServiceCollection) -> ServiceCollection:
        """The profile lives on the account's broker, so the reader holds no state of its own."""
        services.add_singleton(IProfileReader, ProfileReader)

        services.add_handler(GetProfileQuery, GetProfileHandler)
        services.add_handler(ListCalendarEventsQuery, ListCalendarEventsHandler)
        return services
