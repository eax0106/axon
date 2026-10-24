"""Background sound under the bot's voice (an employee setting). Files: see app.employees.ambience.
A setting with no file plays no background sound; the call is not affected."""

from loguru import logger
from pipecat.audio.mixers.soundfile_mixer import SoundfileMixer

from app.employees.ambience import is_missing, sound_path


def mixer_for(name: str, volume: float) -> SoundfileMixer | None:
    if name == "none":
        return None
    if is_missing(name):
        logger.warning(
            f"ambience {name!r}: {sound_path(name)} not found, playing no background sound"
        )
        return None
    return SoundfileMixer(
        sound_files={name: str(sound_path(name))}, default_sound=name, volume=volume
    )
