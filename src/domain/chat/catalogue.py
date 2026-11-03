from dataclasses import dataclass, field

from src.domain.chat.emoji_assets import EmojiAssets


@dataclass
class Catalogue:
    locale: str
    version: str
    categories: list[dict] = field(default_factory=list)
    by_id: dict[str, dict] = field(default_factory=dict)

    def payload(self) -> dict:
        return {"locale": self.locale, "version": self.version, "assetBase": EmojiAssets.ASSET_BASE, "sizes": list(EmojiAssets.SIZES), "fps": EmojiAssets.FPS, "categories": self.categories, "custom": []}
