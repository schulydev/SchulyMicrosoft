import os
import sys


def _force_http1():
    """Hides `h2` so Entrance's and our shared httpx clients use HTTP/1.1.

    httpcore's sync HTTP/2 connection reads the next stream id without a lock, so two threads that
    start a request at the same instant (a cold start: every queued request waits on the first token
    redeem, then all fire together) get the same id. One fails at once and its cleanup drops the
    other's response slot, which then hangs until the read timeout. HTTP/1.1 pools are thread-safe;
    a burst only opens more keep-alive connections. Set MS_HTTP2=1 to keep HTTP/2.
    """
    if os.getenv("MS_HTTP2") != "1":
        sys.modules["h2"] = None


_force_http1()
