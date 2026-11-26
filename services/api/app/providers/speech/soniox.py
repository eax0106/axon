"""Soniox speech-to-text. REST base https://api.soniox.com/v1, header `Authorization: Bearer <key>`.

Calls stream through the engine's WebSocket service on `stt-rt-v6`. The API's own transcriptions
(a spoken brief, a voice lesson) use the file API: upload, create, poll, read, then delete both.
"""

import asyncio
import os

import httpx

from app.providers.base import SpeechToTextProvider
from app.providers.speech.common import LONG_TIMEOUT_S, VendorHealth, check_language

BASE = "https://api.soniox.com/v1"
RT_MODEL = "stt-rt-v6"
ASYNC_MODEL = "stt-async-v6"
POLL_S = 0.5


def hints(language: str) -> list[str]:
    """Callers mix English words into Telugu and Hindi, so English is always a hint too."""
    code = check_language(language)
    return [code] if code == "en" else [code, "en"]


class SonioxSTT(VendorHealth, SpeechToTextProvider):
    name = "soniox"
    health_url = f"{BASE}/models"

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {os.environ['SONIOX_API_KEY']}"}

    async def transcribe(self, wav: bytes, language: str) -> str:
        headers = self.headers()
        body = {"model": ASYNC_MODEL, "language_hints": hints(language)}
        async with self.client() as client:
            upload = await client.post(
                f"{BASE}/files", headers=headers, files={"file": ("audio.wav", wav, "audio/wav")}
            )
            upload.raise_for_status()
            file_id = upload.json()["id"]
            try:
                job = await client.post(
                    f"{BASE}/transcriptions", headers=headers, json={**body, "file_id": file_id}
                )
                job.raise_for_status()
                job_url = f"{BASE}/transcriptions/{job.json()['id']}"
                try:
                    await self._wait(client, job_url, headers)
                    transcript = await client.get(f"{job_url}/transcript", headers=headers)
                    transcript.raise_for_status()
                    return str(transcript.json()["text"])
                finally:
                    await client.delete(job_url, headers=headers)  # best effort; 409 if running
            finally:
                await client.delete(f"{BASE}/files/{file_id}", headers=headers)

    async def _wait(self, client: httpx.AsyncClient, job_url: str, headers: dict[str, str]) -> None:
        for _ in range(int(LONG_TIMEOUT_S / POLL_S)):
            status = await client.get(job_url, headers=headers)
            status.raise_for_status()
            job = status.json()
            if job["status"] == "completed":
                return
            if job["status"] == "error":
                raise httpx.HTTPError(f"soniox transcription failed: {job.get('error_message')}")
            await asyncio.sleep(POLL_S)
        raise httpx.TimeoutException(f"soniox transcription not done after {LONG_TIMEOUT_S:.0f} s")
