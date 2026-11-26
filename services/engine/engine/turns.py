"""When the caller's turn is over: Smart Turn v3 and its silence fallback, both configurable.

`AXON_SMART_TURN_MODEL` points at another Smart Turn v3 ONNX file (for example a fine-tune for
Indian languages); empty runs the model bundled with Pipecat (smart-turn-v3.2-cpu).
`AXON_TURN_SILENCE_BY_LANGUAGE` shortens or lengthens the fallback per opening language, for
example `en=1.5,hi=1.5`; a language not listed keeps the 2 s default.
"""

import os

from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

MODEL_ENV = "AXON_SMART_TURN_MODEL"
SILENCE_ENV = "AXON_TURN_SILENCE_BY_LANGUAGE"
# When Smart Turn wrongly hears a finished question as unfinished, only this much silence ends
# the turn. Pipecat's 3 s held such callers 3.7 s in local tests; 2 s still allows a long pause.
TURN_SILENCE_S = 2.0
MIN_SILENCE_S, MAX_SILENCE_S = 0.5, 5.0


def model_path() -> str | None:
    """The Smart Turn model file to load, or None for Pipecat's bundled one."""
    path = os.environ.get(MODEL_ENV, "").strip()
    if not path:
        return None
    if not os.path.isfile(path):
        raise ValueError(f"{MODEL_ENV} is not a file: {path}")
    return path


def silence_s(language: str) -> float:
    """The silence that ends a turn Smart Turn judged unfinished, for a call in `language`."""
    for item in filter(None, (p.strip() for p in os.environ.get(SILENCE_ENV, "").split(","))):
        code, sep, value = item.partition("=")
        try:
            seconds = float(value)
        except ValueError:
            seconds = -1.0
        if not sep or not MIN_SILENCE_S <= seconds <= MAX_SILENCE_S:
            raise ValueError(
                f"{SILENCE_ENV}: {item!r} must be <language>=<seconds {MIN_SILENCE_S}-"
                f"{MAX_SILENCE_S}>"
            )
        if code.strip() == language:
            return seconds
    return TURN_SILENCE_S


def check() -> None:
    """Fail at start-up, not on a caller, when either setting is wrong."""
    model_path()
    silence_s("")


def analyzer(language: str) -> LocalSmartTurnAnalyzerV3:
    return LocalSmartTurnAnalyzerV3(
        smart_turn_model_path=model_path(),
        params=SmartTurnParams(stop_secs=silence_s(language)),
    )
