from abc import ABC, abstractmethod


class IDeviceLogin(ABC):
    """The device-code sign-in: two documented OAuth calls."""

    @abstractmethod
    async def start_device_login(self, client=None) -> dict: ...

    @abstractmethod
    async def poll_device_login(self, device_code: str, client=None) -> dict: ...
