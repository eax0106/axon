"""Shared by the speech and LLM adapters: the vendor HTTP client and the health request."""

from abc import abstractmethod
from typing import Any, ClassVar

import httpx

from app.providers.base import Provider

TIMEOUT_S = 10.0
LONG_TIMEOUT_S = 60.0  # synthesis, transcription and completions take longer than a health call
LANGUAGES = ("te", "hi", "en")


def check_language(language: str) -> str:
    if language not in LANGUAGES:
        raise ValueError(f"unsupported language {language!r}; V1 speaks {', '.join(LANGUAGES)}")
    return language


class VendorHealth(Provider):
    """One cheap authenticated call to the vendor. Subclasses set the request."""

    health_method = "GET"
    health_url: str
    health_json: ClassVar[dict[str, Any] | None] = None
    health_params: ClassVar[dict[str, str] | None] = None

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    @abstractmethod
    def headers(self) -> dict[str, str]:
        """Auth headers for every request to this vendor."""

    def client(self, timeout: float = LONG_TIMEOUT_S) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    async def health(self) -> None:
        async with self.client(TIMEOUT_S) as client:
            response = await client.request(
                self.health_method,
                self.health_url,
                headers=self.headers(),
                params=self.health_params,
                json=self.health_json,
            )
            response.raise_for_status()
