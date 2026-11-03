import os
from dataclasses import dataclass


@dataclass
class GiphyOptions:
    """Giphy's rating filter, and its key (free from developers.giphy.com), read at each search: without one the search answers 503."""

    rating: str

    @classmethod
    def from_environment(cls) -> "GiphyOptions":
        return cls(rating=os.getenv("GIPHY_RATING", "g"))

    def api_key(self) -> str | None:
        return os.getenv("GIPHY_API_KEY") or None
