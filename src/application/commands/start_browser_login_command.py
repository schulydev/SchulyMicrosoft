from dataclasses import dataclass

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_browser_sign_in import IBrowserSignIn
from src.application.dtos.browser_start_response import BrowserStartResponse


@dataclass
class StartBrowserLoginCommand(ICommand[BrowserStartResponse]):
    pass


class StartBrowserLoginHandler(ICommandHandler[StartBrowserLoginCommand, BrowserStartResponse]):
    def __init__(self, browser: IBrowserSignIn):
        self._browser = browser

    async def handle(self, command: StartBrowserLoginCommand) -> BrowserStartResponse:
        url, verifier = self._browser.build_authorize_url()
        return BrowserStartResponse(authorize_url=url, redirect_uri=self._browser.NATIVE_REDIRECT, code_verifier=verifier)
