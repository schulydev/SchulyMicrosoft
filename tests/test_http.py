"""Shared HTTP client for sign-in calls and the startup warm-up."""

import httpx
import pytest

from src import outnote_client


@pytest.mark.asyncio
async def test_post_reuses_one_shared_client_with_bounded_connect():
    first = outnote_client.shared_async_client()
    assert outnote_client.shared_async_client() is first
    assert first.timeout.connect == 5.0 and first.timeout.read == 30.0
    await outnote_client.close_shared_client()
    assert outnote_client.shared_async_client() is not first
    await outnote_client.close_shared_client()


@pytest.mark.asyncio
async def test_warm_up_opens_login_and_graph_hosts_and_never_raises(monkeypatch):
    seen = []
    monkeypatch.setattr(outnote_client.entrance, "warm_up", lambda urls: seen.extend(urls))
    await outnote_client.warm_up()
    assert any("login.microsoftonline.com" in u for u in seen) and any("graph.microsoft.com" in u for u in seen)
