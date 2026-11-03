import asyncio
from dataclasses import dataclass

from mediatorx import IQuery, IQueryHandler

from src.application.abstractions.i_emoji_catalogue import IEmojiCatalogue
from src.domain.errors.service_error import ServiceError


@dataclass
class GetEmojiCatalogueQuery(IQuery[dict]):
    locale: str


class GetEmojiCatalogueHandler(IQueryHandler[GetEmojiCatalogueQuery, dict]):
    def __init__(self, emojis: IEmojiCatalogue):
        self._emojis = emojis

    async def handle(self, query: GetEmojiCatalogueQuery) -> dict:
        name = self._emojis.normalize_locale(query.locale)
        if name is None:
            raise ServiceError(400, "Invalid locale.")
        cat = await asyncio.to_thread(self._emojis.catalogue, name)
        return cat.payload()
