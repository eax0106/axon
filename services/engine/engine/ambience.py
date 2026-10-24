"""Background sound under the bot's voice (an employee setting).

The sound files are not part of the repository: drop mono 16 kHz WAVs named after the setting
(office.wav, call_center.wav, restaurant.wav, quiet_room.wav, retail_store.wav) into
AXON_AMBIENCE_DIR (default: engine/assets/ambience). A setting with no file plays no background
sound; the call is not affected.
"""

import os
from pathlib import Path

from loguru import logger
from pipecat.audio.mixers.soundfile_mixer import SoundfileMixer

DEFAULT_DIR = Path(__file__).parent / "assets" / "ambience"


def mixer_for(name: str, volume: float) -> SoundfileMixer | None:
    if name == "none":
        return None
    path = Path(os.environ.get("AXON_AMBIENCE_DIR") or DEFAULT_DIR) / f"{name}.wav"
    if not path.is_file():
        logger.warning(f"ambience {name!r}: {path} not found, playing no background sound")
        return None
    return SoundfileMixer(sound_files={name: str(path)}, default_sound=name, volume=volume)
