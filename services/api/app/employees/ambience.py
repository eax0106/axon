"""Where the ambience sound files live, for the API (to warn) and the engine (to play).

The files are not part of the repository: drop mono 16 kHz WAVs named after the setting
(office.wav, call_center.wav, restaurant.wav, quiet_room.wav, retail_store.wav) into
AXON_AMBIENCE_DIR (default: app/assets/ambience). A setting with no file plays no background sound.
"""

import os
from pathlib import Path

DEFAULT_DIR = Path(__file__).parents[1] / "assets" / "ambience"


def sound_path(name: str) -> Path:
    return Path(os.environ.get("AXON_AMBIENCE_DIR") or DEFAULT_DIR) / f"{name}.wav"


def is_missing(name: str) -> bool:
    return name != "none" and not sound_path(name).is_file()
