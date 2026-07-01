import logging
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(
        "sqlite:///./jarvis_notifications.db", alias="DATABASE_URL"
    )
    notifications_port: int = Field(7712, alias="NOTIFICATIONS_PORT")

    # Auth
    auth_secret_key: str = Field("change-me", alias="AUTH_SECRET_KEY")
    auth_algorithm: str = Field("HS256", alias="AUTH_ALGORITHM")
    admin_api_key: str = Field("change-me", alias="ADMIN_API_KEY")

    # App credentials (for app-to-app auth + remote logging)
    jarvis_app_id: str | None = Field(None, alias="JARVIS_APP_ID")
    jarvis_app_key: str | None = Field(None, alias="JARVIS_APP_KEY")

    # Relay
    relay_url: str | None = Field(None, alias="RELAY_URL")
    relay_household_jwt: str | None = Field(None, alias="RELAY_HOUSEHOLD_JWT")

    # Cleanup
    notification_log_retention_days: int = Field(
        30, alias="NOTIFICATION_LOG_RETENTION_DAYS"
    )
    token_cleanup_interval_hours: int = Field(
        24, alias="TOKEN_CLEANUP_INTERVAL_HOURS"
    )

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    def validate_security(self) -> None:
        """Fail closed on insecure auth secrets.

        ``auth_secret_key`` verifies user JWTs and ``admin_api_key`` gates the
        admin API (see ``app/deps.py``). Running on a shipped placeholder
        (``change-me``, ``__SET_ME__``), an empty value, or any short/low-entropy
        value would silently accept tokens forged against a publicly-known key,
        so refuse to start instead. The placeholder set must include whatever
        ``.env.example`` currently ships, or a verbatim copy would boot insecure.
        """
        placeholders = {"", "change-me", "__set_me__"}

        def _insecure(value: str) -> bool:
            v = value.strip()
            return v.lower() in placeholders or len(v) < 16

        problems = []
        if _insecure(self.auth_secret_key):
            problems.append("AUTH_SECRET_KEY")
        if _insecure(self.admin_api_key):
            problems.append("ADMIN_API_KEY")
        if problems:
            raise RuntimeError(
                "Refusing to start with insecure auth config: "
                + ", ".join(problems)
                + " is empty, a known placeholder (change-me / __SET_ME__), or "
                "shorter than 16 chars. Set a strong random secret in the "
                "environment (.env), e.g. `openssl rand -hex 32`."
            )


logger = logging.getLogger(__name__)


@lru_cache
def get_settings() -> Settings:
    try:
        settings = Settings()
    except PermissionError:
        logger.warning(
            "Unable to read .env; continuing with environment variables only"
        )
        settings = Settings(_env_file=None)
    return settings
