from fastapi import APIRouter, Depends, Response
from mediatorx import Mediator

from src.api.controller import controller
from src.api.dependencies import get_mediator, get_password_caller
from src.application.commands.cancel_password_sign_in_command import CancelPasswordSignInCommand
from src.application.commands.choose_password_method_command import ChoosePasswordMethodCommand
from src.application.commands.complete_browser_login_command import CompleteBrowserLoginCommand
from src.application.commands.poll_device_login_command import PollDeviceLoginCommand
from src.application.commands.start_browser_login_command import StartBrowserLoginCommand
from src.application.commands.start_device_login_command import StartDeviceLoginCommand
from src.application.commands.start_password_sign_in_command import StartPasswordSignInCommand
from src.application.commands.submit_password_otp_command import SubmitPasswordOtpCommand
from src.application.dtos.browser_complete_request import BrowserCompleteRequest
from src.application.dtos.browser_start_response import BrowserStartResponse
from src.application.dtos.device_poll_request import DevicePollRequest
from src.application.dtos.device_poll_response import DevicePollResponse
from src.application.dtos.device_start_response import DeviceStartResponse
from src.application.dtos.password_method_request import PasswordMethodRequest
from src.application.dtos.password_otp_request import PasswordOtpRequest
from src.application.dtos.password_sign_in_response import PasswordSignInResponse
from src.application.dtos.password_start_request import PasswordStartRequest
from src.application.queries.get_password_sign_in_query import GetPasswordSignInQuery

router = APIRouter(prefix="/api/auth")


@controller(router)
class AuthController:
    mediator: Mediator = Depends(get_mediator)

    @router.post("/device/start", tags=["Auth"], response_model=DeviceStartResponse)
    async def device_start(self):
        return await self.mediator.send(StartDeviceLoginCommand())

    @router.post("/device/poll", tags=["Auth"], response_model=DevicePollResponse)
    async def device_poll(self, body: DevicePollRequest):
        return await self.mediator.send(PollDeviceLoginCommand(body.device_code))

    @router.post("/browser/start", tags=["Auth"], response_model=BrowserStartResponse)
    async def browser_start(self):
        return await self.mediator.send(StartBrowserLoginCommand())

    @router.post("/browser/complete", tags=["Auth"], response_model=DevicePollResponse)
    async def browser_complete(self, body: BrowserCompleteRequest):
        return await self.mediator.send(CompleteBrowserLoginCommand(body.code, body.code_verifier))

    @router.post("/password/start", tags=["Auth"], response_model=PasswordSignInResponse, response_model_exclude_none=True)
    async def password_start(self, body: PasswordStartRequest, user_id: str = Depends(get_password_caller)):
        """Sign in with the Microsoft password. The password is used once, held only in memory for this
        sign-in and never stored, cached, logged or returned. Completes straight away when Microsoft asks
        for no MFA; otherwise returns mfa_required with the methods Microsoft offers."""
        password = body.password
        body.password = None  # the request model no longer references the password
        return await self.mediator.send(StartPasswordSignInCommand(user_id, body.username, password))

    @router.post("/password/{sign_in_id}/method", tags=["Auth"], response_model=PasswordSignInResponse, response_model_exclude_none=True)
    async def password_method(self, sign_in_id: str, body: PasswordMethodRequest, user_id: str = Depends(get_password_caller)):
        """Choose (or switch to) push or otp. push -> push_pending with the number to tap; otp -> otp_required."""
        return await self.mediator.send(ChoosePasswordMethodCommand(user_id, sign_in_id, body.method))

    @router.post("/password/{sign_in_id}/otp", tags=["Auth"], response_model=PasswordSignInResponse, response_model_exclude_none=True)
    async def password_otp(self, sign_in_id: str, body: PasswordOtpRequest, user_id: str = Depends(get_password_caller)):
        """Submit the authenticator code. complete, or otp_invalid with attempts_left (3 tries per method choice)."""
        return await self.mediator.send(SubmitPasswordOtpCommand(user_id, sign_in_id, body.code))

    @router.get("/password/{sign_in_id}", tags=["Auth"], response_model=PasswordSignInResponse, response_model_exclude_none=True)
    async def password_status(self, sign_in_id: str, user_id: str = Depends(get_password_caller)):
        return await self.mediator.send(GetPasswordSignInQuery(user_id, sign_in_id))

    @router.delete("/password/{sign_in_id}", tags=["Auth"], status_code=204)
    async def password_cancel(self, sign_in_id: str, user_id: str = Depends(get_password_caller)):
        await self.mediator.send(CancelPasswordSignInCommand(user_id, sign_in_id))
        return Response(status_code=204)
