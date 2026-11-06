from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler
from pydantic import SecretStr

from src.application.abstractions.i_sign_in_store import ISignInStore
from src.application.dtos.password_sign_in_response import PasswordSignInResponse
from src.application.services.password_sign_in_responder import PasswordSignInResponder
from src.domain.errors.rate_limited import RateLimited
from src.domain.errors.sign_in_refused import SignInRefused
from src.domain.sign_in.sign_in_state import SignInState


@dataclass
class StartPasswordSignInCommand(ICommand[PasswordSignInResponse]):
    user_id: str
    username: str
    password: SecretStr | None = field(repr=False)


class StartPasswordSignInHandler(ICommandHandler[StartPasswordSignInCommand, PasswordSignInResponse]):
    SIGN_IN_WAIT = 60  # seconds /start waits for the sign-in to finish or reach the method choice

    def __init__(self, store: ISignInStore, responder: PasswordSignInResponder):
        self._store = store
        self._responder = responder

    async def handle(self, command: StartPasswordSignInCommand) -> PasswordSignInResponse:
        password, command.password = command.password, None  # the command no longer references the password
        try:
            job = self._store.start(command.user_id, command.username, password)
        except RateLimited as ex:
            raise SignInRefused(429, "rate_limited", str(ex))
        finally:
            del password
        await self._store.wait_settled(job, -1, self.SIGN_IN_WAIT)
        snap = job.snapshot()
        if snap["state"] != SignInState.WORKING and snap.get("code") not in SignInState.PASSWORD_REFUSED:
            self._store.promote(job)  # the password passed: this replaces the user's earlier attempt
        return await self._responder.respond(job)
