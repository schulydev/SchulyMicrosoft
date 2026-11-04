"""GIF search through Teams, with the account's own Microsoft sign-in and no key of our own.

The Teams clients ask their middle tier for Giphy results (see `TeamsChatClient.gif_command`). The answer is a list of
`{composeType, composeValue, fieldValues: [{fieldName, fieldValue}]}`. The route is undocumented and the names in it were
read from Teams' client code, not from a live answer, so the GIF is found by its Giphy URL rather than by a field name.
A GIF sends as a plain `<img itemtype="http://schema.skype.com/Giphy" src="https://media*.giphy.com/...">` in the message body.
"""

import html
import logging
import re
import time

from src.application.abstractions.i_gif_search import IGifSearch
from src.application.abstractions.i_teams_chat import ITeamsChat
from src.application.options.giphy_options import GiphyOptions
from src.application.services.chat_html_sanitizer import ChatHtmlSanitizer
from src.domain.errors.chat_service_error import ChatServiceError
from src.domain.errors.gif_search_unavailable import GifSearchUnavailable
from src.infrastructure.microsoft.account_cache import AccountCache


class GifSearch(IGifSearch):
    """GIF search over the Teams middle tier, cached and rate limited per account because each tenant has its own GIF policy."""

    log = logging.getLogger("schuly.microsoft")
    MAX_LIMIT = 50
    RESULTS_TTL = 300  # identical searches within 5 minutes share one call
    RATE_PER_MINUTE = 30
    REFUSED = (401, 403, 404)  # this account or tenant has no GIFs: the picker hides them
    _URL = re.compile(r"""https://[^\s"'<>\\]+""")
    _PREVIEW_FIELD = re.compile("thumb|preview|small|still", re.IGNORECASE)

    def __init__(self, html_sanitizer: ChatHtmlSanitizer, options: GiphyOptions, teams: ITeamsChat):
        self._html = html_sanitizer
        self._options = options
        self._teams = teams

    def _gif_urls(self, text: str) -> list[str]:
        urls = (url.split("?")[0] for url in self._URL.findall(html.unescape(text)))
        return [url for url in urls if self._html.is_gif_host(url)]

    def _field(self, fields: dict[str, str], compose: str, *names: str) -> str | None:
        """A field whose name holds one of `names`, else that attribute of the compose value when it is markup."""
        for name in names:
            for key, value in fields.items():
                if name in key and value:
                    return value
            m = re.search(rf'\b{name}="([^"]+)"', compose)
            if m:
                return html.unescape(m.group(1))
        return None

    def _int(self, value) -> int | None:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _shape(self, item) -> dict | None:
        if not isinstance(item, dict):
            return None
        fields = {str(f.get("fieldName") or "").lower(): str(f.get("fieldValue") or "") for f in item.get("fieldValues") or [] if isinstance(f, dict)}
        compose = str(item.get("composeValue") or "")
        previews = [u for name, value in fields.items() if self._PREVIEW_FIELD.search(name) for u in self._gif_urls(value)]
        full = self._gif_urls(compose) + [u for name, value in fields.items() if not self._PREVIEW_FIELD.search(name) for u in self._gif_urls(value)]
        url = next(iter(full or previews), None)
        if not url:
            return None
        return {"id": url, "title": self._field(fields, compose, "title", "alt") or "GIF", "url": url, "previewUrl": next(iter(previews), url), "width": self._int(self._field(fields, compose, "width")), "height": self._int(self._field(fields, compose, "height"))}

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

    def search(self, broker, query: str | None, limit: int) -> list[dict]:
        cache = AccountCache.for_broker(broker)
        cache_key = ("gif_results", (query or "").strip().lower(), limit)
        hit = cache.get(cache_key)
        if hit is not None:
            return hit
        found = self._search(broker, (query or "").strip(), limit)
        cache.set(cache_key, found, self.RESULTS_TTL)
        return found

    def _search(self, broker, query: str, limit: int) -> list[dict]:
        limit = max(1, min(limit, self.MAX_LIMIT))
        try:
            items = self._teams.gif_command(broker, query, limit, self._options.rating)
        except ChatServiceError as ex:
            if ex.status in self.REFUSED:
                self.log.warning("Teams refused the GIF search (%s)", ex.status)
                raise GifSearchUnavailable("Teams has no GIF search for this account.") from None
            raise
        found = [g for g in map(self._shape, items) if g]
        if items and not found:
            # Names only: this is how an unexpected answer gets noticed, since the route has no documentation.
            first = items[0] if isinstance(items[0], dict) else {}
            self.log.warning("Teams GIF answer had no Giphy URL; keys %s, fields %s", sorted(first), sorted(str(f.get("fieldName")) for f in first.get("fieldValues") or [] if isinstance(f, dict)))
        return found[:limit]
