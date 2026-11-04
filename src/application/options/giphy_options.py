import os
from dataclasses import dataclass


@dataclass
class GiphyOptions:
    """Giphy's rating filter for GIF search."""

    rating: str

    @classmethod
    def from_environment(cls) -> "GiphyOptions":
        return cls(rating=os.getenv("GIPHY_RATING", "g"))
