"""ElevenLabs Scribe speech-to-text. REST base https://api.elevenlabs.io/v1, header `xi-api-key`.

Calls stream through the engine's realtime WebSocket service; the API's own transcriptions use
the batch endpoint.
"""

import os

from app.providers.base import SpeechToTextProvider
from app.providers.speech.common import VendorHealth, check_language

BASE = "https://api.elevenlabs.io/v1"
BATCH_MODEL = "scribe_v2"
RT_MODELS = ("scribe_v2_realtime", "scribe_v3_live")


class ElevenLabsSTT(VendorHealth, SpeechToTextProvider):
    name = "elevenlabs"
    health_url = f"{BASE}/user"

    def headers(self) -> dict[str, str]:
        return {"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}

    async def transcribe(self, wav: bytes, language: str) -> str:
        data = {"model_id": BATCH_MODEL, "language_code": check_language(language)}
        async with self.client() as client:
            response = await client.post(
                f"{BASE}/speech-to-text",
                headers=self.headers(),
                data=data,
                files={"file": ("audio.wav", wav, "audio/wav")},
            )
            response.raise_for_status()
            return str(response.json()["text"])
