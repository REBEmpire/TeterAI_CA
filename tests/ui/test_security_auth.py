import os
import importlib
import pytest
import src.ui.api.auth as auth

def test_session_secret_desktop_mode_auto_generate(monkeypatch):
    """Verify that in desktop mode, a random secret is generated if not provided."""
    monkeypatch.setenv("DESKTOP_MODE", "true")
    monkeypatch.delenv("SESSION_SECRET", raising=False)

    importlib.reload(auth)

    assert auth.SESSION_SECRET is not None
    assert auth.SESSION_SECRET != "dev-secret-change-in-prod"
    assert auth.SESSION_SECRET != "MISSING_IN_PRODUCTION"
    assert len(auth.SESSION_SECRET) >= 32

def test_session_secret_production_missing_raises(monkeypatch):
    """Verify that in production (not desktop mode), missing secret causes RuntimeError on use."""
    monkeypatch.setenv("DESKTOP_MODE", "false")
    monkeypatch.delenv("SESSION_SECRET", raising=False)

    importlib.reload(auth)

    assert auth.SESSION_SECRET == "MISSING_IN_PRODUCTION"

    with pytest.raises(RuntimeError, match="SESSION_SECRET environment variable is required in production"):
        auth.create_jwt("uid", "email", "name", "role")

    with pytest.raises(RuntimeError, match="SESSION_SECRET environment variable is required in production"):
        auth.decode_jwt("some-token")

def test_session_secret_provided_works(monkeypatch):
    """Verify that if SESSION_SECRET is provided, it is used correctly."""
    my_secret = "my-very-secure-provided-secret"
    monkeypatch.setenv("SESSION_SECRET", my_secret)
    monkeypatch.setenv("DESKTOP_MODE", "false")

    importlib.reload(auth)

    assert auth.SESSION_SECRET == my_secret

    token = auth.create_jwt("uid", "email@teter.com", "Name", "CA_STAFF")
    assert token is not None

    payload = auth.decode_jwt(token)
    assert payload["sub"] == "uid"
    assert payload["email"] == "email@teter.com"
