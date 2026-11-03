from src.api.di.service_collection import ServiceCollection
from src.application.queries.get_readiness_query import GetReadinessQuery, GetReadinessHandler
from src.application.services.application_lifetime import ApplicationLifetime
from src.application.services.warm_up_tracker import WarmUpTracker


class HealthExtensions:
    @staticmethod
    def add_health(services: ServiceCollection) -> ServiceCollection:
        """The warm-up state and the process lifetime are singletons."""
        services.add_singleton(WarmUpTracker)
        services.add_singleton(ApplicationLifetime)

        services.add_handler(GetReadinessQuery, GetReadinessHandler)
        return services
