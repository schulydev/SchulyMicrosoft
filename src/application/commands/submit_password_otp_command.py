import re
from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_sign_in_store import ISignInStore
from src.application.dtos.password_sign_in_response import PasswordSignInResponse
from src.application.services.password_sign_in_responder import PasswordSignInResponder
from src.domain.errors.sign_in_refused import SignInRefused


@dataclass
class SubmitPasswordOtpCommand(ICommand[PasswordSignInResponse]):
    user_id: str
    sign_in_id: str
    code: str = field(repr=False)


class SubmitPasswordOtpHandler(ICommandHandler[SubmitPasswordOtpCommand, PasswordSignInResponse]):
    OTP_WAIT = 45  # seconds /otp waits for Microsoft's verdict

    def __init__(self, store: ISignInStore, responder: PasswordSignInResponder):
        self._store = store
        self._responder = responder

    async def handle(self, command: SubmitPasswordOtpCommand) -> PasswordSignInResponse:
        job = self._store.get(command.sign_in_id, command.user_id)
        if job is None:
            raise SignInRefused(404, "not_found", "Unknown or expired sign-in.")
        code = re.sub(r"[\s-]", "", command.code)
        if not code.isdigit() or not 6 <= len(code) <= 8:
            raise SignInRefused(422, "invalid_request", "The code must be 6 digits.")
        version = job.snapshot()["version"]
        if not job.submit_code(code):
            raise SignInRefused(409, "invalid_state", "The sign-in isn't waiting for a code.")
        await self._store.wait_settled(job, version, self.OTP_WAIT)
        return await self._responder.respond(job)
