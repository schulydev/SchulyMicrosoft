from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_browser_sign_in import IBrowserSignIn
from src.application.dtos.device_poll_response import DevicePollResponse
from src.application.services.linked_identity_reader import LinkedIdentityReader


@dataclass
class CompleteBrowserLoginCommand(ICommand[DevicePollResponse]):
    code: str = field(repr=False)
    code_verifier: str = field(repr=False)


class CompleteBrowserLoginHandler(ICommandHandler[CompleteBrowserLoginCommand, DevicePollResponse]):
    def __init__(self, browser: IBrowserSignIn, identities: LinkedIdentityReader):
        self._browser = browser
        self._identities = identities

    async def handle(self, command: CompleteBrowserLoginCommand) -> DevicePollResponse:
        result = await self._browser.exchange_code(command.code, command.code_verifier)

        if not result.get("access_token") or not result.get("refresh_token"):
            return DevicePollResponse(status="error", message=result.get("error_description") or result.get("error") or "sign-in failed")
        refresh_token = result["refresh_token"]
        account = await self._identities.read(refresh_token)
        return DevicePollResponse(status="complete", refresh_token=refresh_token, account=account)
