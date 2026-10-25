"""Process settings, read from environment variables (`.env` locally, a secret store when hosted).

Provider keys are not listed here: the provider registry reads them by name, so a key added
at runtime is picked up without code changes. `.env.example` lists every variable.
"""

import os
from dataclasses import dataclass
from functools import cache

from app.providers.base import ProviderKind, ProviderNotConfiguredError

PUBLIC_URL_ENV = "AXON_ENGINE_PUBLIC_URL"
API_URL_ENV = "AXON_API_PUBLIC_URL"


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    jwt_secret: str  # empty = auth not configured; auth routes answer 503


@cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql+asyncpg://axon:axon@localhost:5432/axon"
        ),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        jwt_secret=os.environ.get("AXON_JWT_SECRET", ""),
    )


def engine_public_url() -> str:
    """The engine's public https URL (the carrier and browsers must reach it), or a 503."""
    url = os.environ.get(PUBLIC_URL_ENV, "").rstrip("/")
    if not url.startswith("https://"):
        raise ProviderNotConfiguredError(
            ProviderKind.TELEPHONY,
            "vobiz",
            [PUBLIC_URL_ENV],
            f"{PUBLIC_URL_ENV} must be the engine's public https URL (Vobiz must reach it)",
        )
    return url


def api_public_url() -> str:
    """The API's public https URL (the carrier calls it back when a call ends), or a 503."""
    url = os.environ.get(API_URL_ENV, "").rstrip("/")
    if not url.startswith("https://"):
        raise ProviderNotConfiguredError(
            ProviderKind.TELEPHONY,
            "vobiz",
            [API_URL_ENV],
            f"{API_URL_ENV} must be the API's public https URL (Vobiz calls it when a call ends)",
        )
    return url
