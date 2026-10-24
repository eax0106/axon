"""Shared by the speech and LLM adapters: the V1 languages and the vendor health request."""

import os
from typing import Any, ClassVar

import httpx

from app.providers.base import Provider, ProviderNotConfiguredError

LANGUAGES = ("te", "hi", "en")
TIMEOUT_S = 10.0


def check_language(language: str) -> str:
    if language not in LANGUAGES:
        raise ValueError(f"unsupported language {language!r}; V1 speaks {', '.join(LANGUAGES)}")
    return language


def pipecat_language(language: str) -> Any:
    """The Pipecat `Language` for a V1 language code. Imported late: only the engine has Pipecat."""
    from pipecat.transcriptions.language import Language

    return Language(check_language(language))


class VendorHealth(Provider):
    """One cheap authenticated call to the vendor. Subclasses set the request."""

    health_method = "GET"
    health_url: str
    health_json: ClassVar[dict[str, Any] | None] = None
    health_params: ClassVar[dict[str, str] | None] = None

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def headers(self) -> dict[str, str]:
        raise NotImplementedError

    async def health(self) -> None:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=self._transport) as client:
            response = await client.request(
                self.health_method,
                self.health_url,
                headers=self.headers(),
                params=self.health_params,
                json=self.health_json,
            )
            response.raise_for_status()


def need_env(kind_adapter: Provider, name: str) -> str:
    """The value of a required env var, or ProviderNotConfiguredError (served as 503)."""
    value = os.environ.get(name)
    if not value:
        detail = f"{kind_adapter.kind} provider {kind_adapter.name!r} needs {name}"
        raise ProviderNotConfiguredError(kind_adapter.kind, kind_adapter.name, [name], detail)
    return value
