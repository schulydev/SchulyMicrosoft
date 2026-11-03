from src.api.di.service_collection import ServiceCollection
from src.api.token_rotation.context_token_rotation import ContextTokenRotation
from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_graph_client_factory import IGraphClientFactory
from src.application.abstractions.i_microsoft_http_clients import IMicrosoftHttpClients
from src.application.abstractions.i_token_rotation import ITokenRotation
from src.application.options.microsoft_options import MicrosoftOptions
from src.infrastructure.microsoft.account_runner import AccountRunner
from src.infrastructure.microsoft.microsoft_http_clients import MicrosoftHttpClients
from src.infrastructure.microsoft.outnote_client_factory import OutNoteClientFactory


class MicrosoftExtensions:
    @staticmethod
    def add_microsoft_access(services: ServiceCollection) -> ServiceCollection:
        """The shared HTTP clients and the per-token brokers are singletons: a broker per request would redeem the refresh token on every call."""
        services.add_instance(MicrosoftOptions, MicrosoftOptions.from_environment())
        services.add_singleton(IMicrosoftHttpClients, MicrosoftHttpClients)
        services.add_singleton(IGraphClientFactory, OutNoteClientFactory)
        services.add_singleton(ITokenRotation, ContextTokenRotation)
        services.add_singleton(IAccountRunner, AccountRunner)
        return services
