from pydantic import BaseModel


class DevicePollRequest(BaseModel):
    device_code: str
