"""GIF search over Giphy's public API.

Teams shows Giphy GIFs as a plain `<img itemtype="http://schema.skype.com/Giphy" src="https://media*.giphy.com/...">`
in the message body, so a GIF picked here sends the same way. The Teams clients query Giphy with
Microsoft's own key; Schuly needs its own (`GIPHY_API_KEY`, free from developers.giphy.com).
Without one the search answers 503.
"""

import os
import time

from entrance import http_client

from src import chat_html
from src.account_cache import AccountCache, for_broker

API = "https://api.giphy.com/v1/gifs"
RATING = os.getenv("GIPHY_RATING", "g")
MAX_LIMIT = 50
RESULTS_TTL = 300  # identical searches within 5 minutes share one Giphy call
RATE_PER_MINUTE = 30
_results = AccountCache(max_items=500)


class GifSearchUnavailable(RuntimeError):
    pass


def api_key() -> str | None:
    return os.getenv("GIPHY_API_KEY") or None


def _image(images: dict, *names: str) -> dict:
    for name in names:
        img = images.get(name) or {}
        if img.get("url"):
            return img
    return {}


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _shape(item: dict) -> dict | None:
    images = item.get("images") or {}
    full = _image(images, "downsized_medium", "downsized", "original")
    preview = _image(images, "fixed_width_small", "fixed_width", "preview_gif") or full
    url = (full.get("url") or "").split("?")[0]
    if not chat_html.is_gif_host(url):
        return None
    return {"id": item.get("id"), "title": item.get("title") or "GIF", "url": url, "previewUrl": (preview.get("url") or url).split("?")[0], "width": _int(full.get("width")), "height": _int(full.get("height"))}


def allow(broker) -> bool:
    """A fixed one-minute window per account: at most RATE_PER_MINUTE searches."""
    cache = for_broker(broker)
    window = ("gif_rate", int(time.time() // 60))
    with cache.lock("gif_rate"):
        used = cache.get(window, 0)
        if used >= RATE_PER_MINUTE:
            return False
        cache.set(window, used + 1, 120)
    return True


def search(query: str | None, limit: int) -> list[dict]:
    key = api_key()
    if not key:
        raise GifSearchUnavailable("GIF search needs a Giphy API key (GIPHY_API_KEY).")
    cache_key = ((query or "").strip().lower() or None, limit)
    hit = _results.get(cache_key)
    if hit is not None:
        return hit
    found = _search(key, query, limit)
    _results.set(cache_key, found, RESULTS_TTL)
    return found


def _search(key: str, query: str | None, limit: int) -> list[dict]:
    params = {"api_key": key, "limit": max(1, min(limit, MAX_LIMIT)), "rating": RATING}
    if query:
        params["q"] = query
    r = http_client().get(f"{API}/{'search' if query else 'trending'}", params=params, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"Giphy answered {r.status_code}")
    return [g for g in (_shape(i) for i in r.json().get("data") or []) if g]
