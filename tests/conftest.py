import pytest

from tests.services import profile

REAL_FETCH = profile._fetch


@pytest.fixture(autouse=True)
def profile_from_note(monkeypatch):
    """Tests use fake notes: the profile comes from `note.me()` instead of a live Graph call. `test_profile.py` restores the real fetch."""
    monkeypatch.setattr(profile, "_fetch", lambda note, broker: (note.me(), profile.TTL))
