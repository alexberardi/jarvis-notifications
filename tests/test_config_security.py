"""Guard against booting on insecure / placeholder auth secrets.

Regression cover for the .env.example placeholder drifting away from the
``validate_security`` reject-list (see ``app/config.py``).
"""

import pytest

from app.config import Settings

STRONG = "s3cret-" + "x" * 32  # >= 16 chars, not a placeholder


def _settings(monkeypatch: pytest.MonkeyPatch, auth: str, admin: str) -> Settings:
    # Env vars take precedence over any .env file; construct from a clean env.
    monkeypatch.setenv("AUTH_SECRET_KEY", auth)
    monkeypatch.setenv("ADMIN_API_KEY", admin)
    return Settings()


@pytest.mark.parametrize("bad", ["", "change-me", "__SET_ME__", "__set_me__", "short"])
def test_rejects_insecure_auth_secret(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    with pytest.raises(RuntimeError, match="insecure auth config"):
        _settings(monkeypatch, bad, STRONG).validate_security()


@pytest.mark.parametrize("bad", ["", "change-me", "__SET_ME__", "tooshort"])
def test_rejects_insecure_admin_key(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    with pytest.raises(RuntimeError, match="insecure auth config"):
        _settings(monkeypatch, STRONG, bad).validate_security()


def test_accepts_strong_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    # Should not raise.
    _settings(monkeypatch, STRONG, STRONG + "-admin").validate_security()
