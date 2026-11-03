from dataclasses import dataclass

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_sign_in_store import ISignInStore
from src.application.dtos.password_sign_in_response import PasswordSignInResponse
from src.application.services.password_sign_in_responder import PasswordSignInResponder
from src.domain.errors.sign_in_refused import SignInRefused


@dataclass
class GetPasswordSignInQuery(IQuery[PasswordSignInResponse]):
    user_id: str
    sign_in_id: str


class GetPasswordSignInHandler(IQueryHandler[GetPasswordSignInQuery, PasswordSignInResponse]):
    def __init__(self, store: ISignInStore, responder: PasswordSignInResponder):
        self._store = store
        self._responder = responder

    async def handle(self, query: GetPasswordSignInQuery) -> PasswordSignInResponse:
        job = self._store.get(query.sign_in_id, query.user_id)
        if job is None:
            raise SignInRefused(404, "not_found", "Unknown or expired sign-in.")
        return await self._responder.respond(job)
