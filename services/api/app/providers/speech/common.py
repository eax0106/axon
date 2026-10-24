"""Shared by the speech and LLM adapters: the one vendor health request."""

from abc import abstractmethod
from typing import Any, ClassVar

import httpx

from app.providers.base import Provider

TIMEOUT_S = 10.0


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
        """Auth headers for the health request."""

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
