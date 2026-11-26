"""The caller's voice activity detector (Silero), tunable for noisy phone lines.

Each value has its own variable; unset keeps today's value (Pipecat's defaults). Raising
`AXON_VAD_START_SECS` or `AXON_VAD_CONFIDENCE` makes a horn or a shop's chatter less likely to
cut the bot off, at the price of a slower real barge-in. Tune it against the usage event's
`false_interruptions` (engine.events) on real calls.
"""

import os

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams

# name -> (VADParams field, lowest, highest)
SETTINGS = {
    "AXON_VAD_CONFIDENCE": ("confidence", 0.1, 1.0),
    "AXON_VAD_START_SECS": ("start_secs", 0.05, 2.0),
    "AXON_VAD_STOP_SECS": ("stop_secs", 0.05, 2.0),
    "AXON_VAD_MIN_VOLUME": ("min_volume", 0.0, 1.0),
}


def params() -> VADParams:
    values: dict[str, float] = {}
    for name, (field, low, high) in SETTINGS.items():
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            value = -1.0
        if not low <= value <= high:
            raise ValueError(f"{name} must be a number from {low} to {high}, not {raw!r}")
        values[field] = value
    return VADParams(**values)


def analyzer() -> SileroVADAnalyzer:
    return SileroVADAnalyzer(params=params())
