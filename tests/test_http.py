"""Shared HTTP client for sign-in calls and the startup warm-up."""

import entrance
import httpx
import pytest

from tests.services import http_clients


@pytest.mark.asyncio
async def test_post_reuses_one_shared_client_with_bounded_connect():
    first = http_clients.shared_async_client()
    assert http_clients.shared_async_client() is first
    assert first.timeout.connect == 5.0 and first.timeout.read == 30.0
    await http_clients.close_shared_client()
    assert http_clients.shared_async_client() is not first
    await http_clients.close_shared_client()


@pytest.mark.asyncio
async def test_warm_up_opens_login_and_graph_hosts_and_never_raises(monkeypatch):
    seen = []
    monkeypatch.setattr(entrance, "warm_up", lambda urls: seen.extend(urls))
    await http_clients.warm_up()
    assert any("login.microsoftonline.com" in u for u in seen) and any("graph.microsoft.com" in u for u in seen)
