"""Process settings, read from environment variables (`.env` locally, a secret store when hosted).

Provider keys are not listed here: the provider registry reads them by name, so a key added
at runtime is picked up without code changes. `.env.example` lists every variable.
"""

import os
from dataclasses import dataclass
from functools import cache


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str


@cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql+asyncpg://axon:axon@localhost:5432/axon"
        ),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    )
