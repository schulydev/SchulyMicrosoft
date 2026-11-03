from contextvars import ContextVar

from src.application.abstractions.i_token_rotation import ITokenRotation


class RotationSlot:
    """The rotated refresh token of one request, if any."""

    def __init__(self):
        self.refresh_token: str | None = None


class ContextTokenRotation(ITokenRotation):
    """Per-request state, like HttpContext: the middleware opens a slot, the account runner fills it after reading the broker."""

    def __init__(self):
        self._slot: ContextVar[RotationSlot | None] = ContextVar("token_rotation_slot", default=None)

    def open_slot(self) -> RotationSlot:
        slot = RotationSlot()
        self._slot.set(slot)
        return slot

    def record(self, refresh_token: str) -> None:
        slot = self._slot.get()
        if slot is not None:
            slot.refresh_token = refresh_token
