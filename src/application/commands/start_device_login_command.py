from dataclasses import dataclass

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_device_login import IDeviceLogin
from src.application.dtos.device_start_response import DeviceStartResponse


@dataclass
class StartDeviceLoginCommand(ICommand[DeviceStartResponse]):
    pass


class StartDeviceLoginHandler(ICommandHandler[StartDeviceLoginCommand, DeviceStartResponse]):
    def __init__(self, device: IDeviceLogin):
        self._device = device

    async def handle(self, command: StartDeviceLoginCommand) -> DeviceStartResponse:
        data = await self._device.start_device_login()
        return DeviceStartResponse(
            user_code=data["user_code"],
            verification_uri=data.get("verification_uri") or data.get("verification_url"),
            device_code=data["device_code"],
            interval=data.get("interval", 5),
            expires_in=data.get("expires_in", 900),
            message=data.get("message"),
        )
