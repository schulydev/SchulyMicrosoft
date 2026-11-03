"""SchulyMicrosoft: stateless Microsoft 365 access for Schuly, over OutNote / Entrance.

The user signs in once with the device-code or browser flow on Microsoft's real page (no password
reaches this service; the one exception is the web password sign-in route, which uses the password
once in memory and never stores or logs it); the caller stores the returned FOCI refresh token and sends it back
on each read. Reads return the rotated refresh token in the X-MS-Refresh-Token header.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.controllers import auth_controller, chats_controller, emojis_controller, files_controller, gifs_controller, health_controller, mail_controller, me_controller, one_note_controller, people_controller, search_controller, teams_controller
from src.api.di.service_collection import ServiceCollection, ServiceProvider
from src.api.extensions.chats_extensions import ChatsExtensions
from src.api.extensions.emojis_extensions import EmojisExtensions
from src.api.extensions.exception_handling_extensions import ExceptionHandlingExtensions
from src.api.extensions.files_extensions import FilesExtensions
from src.api.extensions.gifs_extensions import GifsExtensions
from src.api.extensions.health_extensions import HealthExtensions
from src.api.extensions.mail_extensions import MailExtensions
from src.api.extensions.me_extensions import MeExtensions
from src.api.extensions.microsoft_extensions import MicrosoftExtensions
from src.api.extensions.one_note_extensions import OneNoteExtensions
from src.api.extensions.open_api_extensions import OpenApiExtensions
from src.api.extensions.people_extensions import PeopleExtensions
from src.api.extensions.search_extensions import SearchExtensions
from src.api.extensions.sign_in_extensions import SignInExtensions
from src.api.extensions.teams_extensions import TeamsExtensions
from src.api.middleware.token_rotation_middleware import TokenRotationMiddleware
from src.application.abstractions.i_token_rotation import ITokenRotation
from src.application.services.application_lifetime import ApplicationLifetime


class Program:
    """The composition root, like Program.cs: what exists and for how long, then how a request flows."""

    @staticmethod
    def add_services() -> ServiceProvider:
        services = ServiceCollection()
        MicrosoftExtensions.add_microsoft_access(services)
        HealthExtensions.add_health(services)
        SignInExtensions.add_sign_in(services)
        MeExtensions.add_me(services)
        MailExtensions.add_mail(services)
        OneNoteExtensions.add_one_note(services)
        ChatsExtensions.add_chats(services)
        PeopleExtensions.add_people(services)
        FilesExtensions.add_files(services)
        TeamsExtensions.add_teams(services)
        SearchExtensions.add_search(services)
        EmojisExtensions.add_emojis(services)
        GifsExtensions.add_gifs(services)
        return services.build()

    @classmethod
    def create_app(cls) -> FastAPI:
        provider = cls.add_services()

        @asynccontextmanager
        async def lifespan(_: FastAPI):
            lifetime = provider.get(ApplicationLifetime)
            lifetime.start()
            yield
            await lifetime.stop()

        app = FastAPI(title="SchulyMicrosoft", description="Microsoft 365 access for Schuly via OutNote.", lifespan=lifespan)
        app.state.services = provider
        ExceptionHandlingExtensions.use_schuly_exception_handling(app)
        app.add_middleware(TokenRotationMiddleware, rotation=provider.get(ITokenRotation))
        for module in (health_controller, auth_controller, me_controller, mail_controller, one_note_controller, chats_controller, people_controller, files_controller, teams_controller, search_controller, emojis_controller, gifs_controller):
            app.include_router(module.router)
        OpenApiExtensions.use_plain_operation_names(app)
        return app


app = Program.create_app()
