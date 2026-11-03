from dataclasses import dataclass, field

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_device_login import IDeviceLogin
from src.application.dtos.device_poll_response import DevicePollResponse
from src.application.services.linked_identity_reader import LinkedIdentityReader


@dataclass
class PollDeviceLoginCommand(ICommand[DevicePollResponse]):
    device_code: str = field(repr=False)


class PollDeviceLoginHandler(ICommandHandler[PollDeviceLoginCommand, DevicePollResponse]):
    def __init__(self, device: IDeviceLogin, identities: LinkedIdentityReader):
        self._device = device
        self._identities = identities

    async def handle(self, command: PollDeviceLoginCommand) -> DevicePollResponse:
        result = await self._device.poll_device_login(command.device_code)

        if result.get("access_token"):
            refresh_token = result.get("refresh_token")
            if not refresh_token:
                return DevicePollResponse(status="error", message="No refresh token in the response.")
            account = await self._identities.read(refresh_token)
            return DevicePollResponse(status="complete", refresh_token=refresh_token, account=account)

        error = result.get("error")
        if error in ("authorization_pending", "slow_down"):
            return DevicePollResponse(status="pending", message=error)
        return DevicePollResponse(status="error", message=result.get("error_description") or error or "sign-in failed")
