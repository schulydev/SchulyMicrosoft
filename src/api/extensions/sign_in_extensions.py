from src.api.di.service_collection import ServiceCollection
from src.application.abstractions.i_browser_sign_in import IBrowserSignIn
from src.application.abstractions.i_device_login import IDeviceLogin
from src.application.abstractions.i_sign_in_store import ISignInStore
from src.application.commands.cancel_password_sign_in_command import CancelPasswordSignInCommand, CancelPasswordSignInHandler
from src.application.commands.choose_password_method_command import ChoosePasswordMethodCommand, ChoosePasswordMethodHandler
from src.application.commands.complete_browser_login_command import CompleteBrowserLoginCommand, CompleteBrowserLoginHandler
from src.application.commands.poll_device_login_command import PollDeviceLoginCommand, PollDeviceLoginHandler
from src.application.commands.start_browser_login_command import StartBrowserLoginCommand, StartBrowserLoginHandler
from src.application.commands.start_device_login_command import StartDeviceLoginCommand, StartDeviceLoginHandler
from src.application.commands.start_password_sign_in_command import StartPasswordSignInCommand, StartPasswordSignInHandler
from src.application.commands.submit_password_otp_command import SubmitPasswordOtpCommand, SubmitPasswordOtpHandler
from src.application.options.password_sign_in_options import PasswordSignInOptions
from src.application.options.service_auth_options import ServiceAuthOptions
from src.application.queries.get_password_sign_in_query import GetPasswordSignInQuery, GetPasswordSignInHandler
from src.application.services.linked_identity_reader import LinkedIdentityReader
from src.application.services.password_sign_in_responder import PasswordSignInResponder
from src.infrastructure.microsoft.browser_sign_in_client import BrowserSignInClient
from src.infrastructure.microsoft.device_login_client import DeviceLoginClient
from src.infrastructure.password_signin.job_store import JobStore


class SignInExtensions:
    @staticmethod
    def add_sign_in(services: ServiceCollection) -> ServiceCollection:
        """Password sign-in jobs are in memory, so the store is one singleton for the process (asgi.py pins workers=1)."""
        services.add_instance(PasswordSignInOptions, PasswordSignInOptions.from_environment())
        services.add_instance(ServiceAuthOptions, ServiceAuthOptions())
        services.add_singleton(IDeviceLogin, DeviceLoginClient)
        services.add_singleton(IBrowserSignIn, BrowserSignInClient)
        services.add_singleton(ISignInStore, JobStore)
        services.add_singleton(LinkedIdentityReader)
        services.add_singleton(PasswordSignInResponder)

        services.add_handler(StartDeviceLoginCommand, StartDeviceLoginHandler)
        services.add_handler(PollDeviceLoginCommand, PollDeviceLoginHandler)
        services.add_handler(StartBrowserLoginCommand, StartBrowserLoginHandler)
        services.add_handler(CompleteBrowserLoginCommand, CompleteBrowserLoginHandler)
        services.add_handler(StartPasswordSignInCommand, StartPasswordSignInHandler)
        services.add_handler(ChoosePasswordMethodCommand, ChoosePasswordMethodHandler)
        services.add_handler(SubmitPasswordOtpCommand, SubmitPasswordOtpHandler)
        services.add_handler(GetPasswordSignInQuery, GetPasswordSignInHandler)
        services.add_handler(CancelPasswordSignInCommand, CancelPasswordSignInHandler)
        return services
