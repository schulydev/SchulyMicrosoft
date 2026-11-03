from dataclasses import dataclass

from mediatorx import ICommand, ICommandHandler

from src.application.abstractions.i_sign_in_store import ISignInStore


@dataclass
class CancelPasswordSignInCommand(ICommand[None]):
    user_id: str
    sign_in_id: str


class CancelPasswordSignInHandler(ICommandHandler[CancelPasswordSignInCommand, None]):
    def __init__(self, store: ISignInStore):
        self._store = store

    async def handle(self, command: CancelPasswordSignInCommand) -> None:
        self._store.remove(command.sign_in_id, command.user_id)
