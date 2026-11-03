from dataclasses import dataclass

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_sign_in_store import ISignInStore
from src.application.dtos.password_sign_in_response import PasswordSignInResponse
from src.application.services.password_sign_in_responder import PasswordSignInResponder
from src.domain.errors.sign_in_refused import SignInRefused


@dataclass
class ChoosePasswordMethodCommand(ICommand[PasswordSignInResponse]):
    user_id: str
    sign_in_id: str
    method: str


class ChoosePasswordMethodHandler(ICommandHandler[ChoosePasswordMethodCommand, PasswordSignInResponse]):
    METHOD_WAIT = 30  # seconds /method waits for the push number / the code prompt

    def __init__(self, store: ISignInStore, responder: PasswordSignInResponder):
        self._store = store
        self._responder = responder

    async def handle(self, command: ChoosePasswordMethodCommand) -> PasswordSignInResponse:
        job = self._store.get(command.sign_in_id, command.user_id)
        if job is None:
            raise SignInRefused(404, "not_found", "Unknown or expired sign-in.")
        version = job.snapshot()["version"]
        outcome = job.request_method(command.method)
        if outcome == "unavailable":
            raise SignInRefused(409, "method_unavailable", "Microsoft doesn't offer that method for this account.")
        if outcome == "invalid_state":
            raise SignInRefused(409, "invalid_state", "The sign-in isn't waiting for a method.")
        if outcome == "ok":
            await self._store.wait_settled(job, version, self.METHOD_WAIT)
        return await self._responder.respond(job)
