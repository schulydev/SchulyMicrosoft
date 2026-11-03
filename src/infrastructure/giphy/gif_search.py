"""GIF search over Giphy's public API.

Teams shows Giphy GIFs as a plain `<img itemtype="http://schema.skype.com/Giphy" src="https://media*.giphy.com/...">`
in the message body, so a GIF picked here sends the same way. The Teams clients query Giphy with
Microsoft's own key; Schuly needs its own (`GIPHY_API_KEY`, free from developers.giphy.com).
Without one the search answers 503.
"""

import time
from urllib.parse import urlencode
from entrance import http_client

from src.application.abstractions.i_gif_search import IGifSearch
from src.application.options.giphy_options import GiphyOptions
from src.application.services.chat_html_sanitizer import ChatHtmlSanitizer
from src.domain.errors.gif_search_unavailable import GifSearchUnavailable
from src.infrastructure.microsoft.account_cache import AccountCache


class GifSearch(IGifSearch):
    """GIF search over Giphy's public API, with a per-account rate limit."""

    API = "https://api.giphy.com/v1/gifs"
    MAX_LIMIT = 50
    RESULTS_TTL = 300  # identical searches within 5 minutes share one Giphy call
    RATE_PER_MINUTE = 30
    http_client = staticmethod(http_client)

    def __init__(self, html: ChatHtmlSanitizer, options: GiphyOptions):
        self._html = html
        self._options = options
        self._results = AccountCache(max_items=500)

    def _image(self, images: dict, *names: str) -> dict:
        for name in names:
            img = images.get(name) or {}
            if img.get("url"):
                return img
        return {}

    def _int(self, value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _shape(self, item: dict) -> dict | None:
        images = item.get("images") or {}
        full = self._image(images, "downsized_medium", "downsized", "original")
        preview = self._image(images, "fixed_width_small", "fixed_width", "preview_gif") or full
        url = (full.get("url") or "").split("?")[0]
        if not self._html.is_gif_host(url):
            return None
        return {"id": item.get("id"), "title": item.get("title") or "GIF", "url": url, "previewUrl": (preview.get("url") or url).split("?")[0], "width": self._int(full.get("width")), "height": self._int(full.get("height"))}

    def allow(self, broker) -> bool:
        """A fixed one-minute window per account: at most RATE_PER_MINUTE searches."""
        cache = AccountCache.for_broker(broker)
        window = ("gif_rate", int(time.time() // 60))
        with cache.lock("gif_rate"):
            used = cache.get(window, 0)
            if used >= self.RATE_PER_MINUTE:
                return False
            cache.set(window, used + 1, 120)
        return True

    def search(self, query: str | None, limit: int) -> list[dict]:
        key = self._options.api_key()
        if not key:
            raise GifSearchUnavailable("GIF search needs a Giphy API key (GIPHY_API_KEY).")
        cache_key = ((query or "").strip().lower() or None, limit)
        hit = self._results.get(cache_key)
        if hit is not None:
            return hit
        found = self._search(key, query, limit)
        self._results.set(cache_key, found, self.RESULTS_TTL)
        return found

    def _search(self, key: str, query: str | None, limit: int) -> list[dict]:
        params = {"api_key": key, "limit": max(1, min(limit, self.MAX_LIMIT)), "rating": self._options.rating}
        if query:
            params["q"] = query
        r = self.http_client().request("GET", f"{self.API}/{'search' if query else 'trending'}?{urlencode(params)}", timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"Giphy answered {r.status_code}")
        return [g for g in (self._shape(i) for i in r.json().get("data") or []) if g]
