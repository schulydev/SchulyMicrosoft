from dataclasses import dataclass, field

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_account_runner import IAccountRunner
from src.application.abstractions.i_gif_search import IGifSearch
from src.application.options.microsoft_options import MicrosoftOptions
from src.domain.errors.gif_search_unavailable import GifSearchUnavailable
from src.domain.errors.service_error import ServiceError
from src.domain.validation.refresh_token_format import RefreshTokenFormat


@dataclass
class SearchGifsQuery(IQuery[list[dict]]):
    refresh_token: str = field(repr=False)
    q: str | None
    limit: int


class SearchGifsHandler(IQueryHandler[SearchGifsQuery, list[dict]]):
    def __init__(self, accounts: IAccountRunner, gifs: IGifSearch, options: MicrosoftOptions):
        self._accounts = accounts
        self._gifs = gifs
        self._options = options

    async def handle(self, query: SearchGifsQuery) -> list[dict]:
        RefreshTokenFormat.check(query.refresh_token)

        def run(note, broker):
            # Only a live Microsoft sign-in may spend the GIF key: the token must mint a Graph token (cached after the first call), and each account is rate limited.
            broker(self._options.device_client_id)
            if not self._gifs.allow(broker):
                raise ServiceError(429, "Too many GIF searches; wait a minute.", headers={"Retry-After": "60"})
            try:
                return self._gifs.search(query.q, query.limit)
            except GifSearchUnavailable as ex:
                raise ServiceError(503, str(ex))
            except Exception as ex:
                raise ServiceError(502, f"GIF search failed: {type(ex).__name__}")

        return await self._accounts.run(query.refresh_token, run)
