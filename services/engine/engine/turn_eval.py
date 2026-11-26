"""Score Smart Turn models offline on labelled pauses, before one goes onto real calls.

    uv run python -m engine.turn_eval pauses.csv [--model other.onnx ...]

`pauses.csv` has a header and one row per clip: `file,language,label`, where `file` is a WAV
(mono 16-bit; 8 kHz phone audio is resampled to 16 kHz), `language` is te, hi or en, and `label`
is `complete` (the speaker had finished) or `incomplete` (they paused and went on). Relative
paths are read from the CSV's folder. With no --model, Pipecat's bundled v3.2 is scored; give
`--model bundled` to score it beside other files.

Per model and language it prints the share judged right, how often an unfinished turn was cut
off (judged complete), and how often a finished one was held for the silence fallback.
"""

import argparse
import csv
import sys
import wave
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

MODEL_RATE = 16000
BUNDLED = "bundled"
Audio = NDArray[np.float32]
Predict = Callable[[Audio], bool]  # True = the turn is complete


@dataclass(frozen=True)
class Clip:
    path: Path
    language: str
    complete: bool


@dataclass
class Score:
    right: int = 0
    cut_off: int = 0  # unfinished, judged complete: the caller is talked over
    held: int = 0  # finished, judged unfinished: the caller waits for the fallback
    complete: int = 0
    incomplete: int = 0

    @property
    def total(self) -> int:
        return self.complete + self.incomplete


@dataclass
class Report:
    scores: dict[str, Score] = field(default_factory=dict)  # language -> score

    def add(self, clip: Clip, judged_complete: bool) -> None:
        score = self.scores.setdefault(clip.language, Score())
        if clip.complete:
            score.complete += 1
            score.held += not judged_complete
        else:
            score.incomplete += 1
            score.cut_off += judged_complete
        score.right += judged_complete == clip.complete


def read_manifest(path: Path) -> list[Clip]:
    clips = []
    with path.open(newline="", encoding="utf-8") as handle:
        for line, row in enumerate(csv.DictReader(handle), start=2):
            label = (row.get("label") or "").strip().lower()
            if label not in ("complete", "incomplete") or not row.get("file"):
                raise ValueError(f"{path}:{line}: needs a file and label complete|incomplete")
            clips.append(
                Clip(
                    path=path.parent / row["file"].strip(),
                    language=(row.get("language") or "").strip() or "unknown",
                    complete=label == "complete",
                )
            )
    return clips


def read_wav(path: Path) -> Audio:
    """Mono 16-bit WAV as floats in [-1, 1] at 16 kHz."""
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError(f"{path}: needs mono 16-bit audio")
        rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    audio = samples.astype(np.float32) / 32768.0
    if rate != MODEL_RATE and len(audio):
        # ponytail: linear resampling; enough for an 8 kHz phone clip that has nothing above 4 kHz.
        times = np.arange(round(len(audio) * MODEL_RATE / rate)) * (rate / MODEL_RATE)
        audio = np.interp(times, np.arange(len(audio)), audio).astype(np.float32)
    return audio


def evaluate(clips: Iterable[Clip], predict: Predict) -> Report:
    report = Report()
    for clip in clips:
        report.add(clip, predict(read_wav(clip.path)))
    return report


def smart_turn(model: str) -> Predict:
    """The model's own verdict on a clip, as Pipecat's analyzer reaches it at a VAD stop."""
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

    analyzer = LocalSmartTurnAnalyzerV3(smart_turn_model_path=None if model == BUNDLED else model)

    def predict(audio: Audio) -> bool:
        return bool(analyzer._predict_endpoint(audio)["prediction"] == 1)

    return predict


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:5.1f}%" if whole else "    -"


def render(model: str, report: Report) -> str:
    lines = [f"model: {model}", "language  clips  right   cut off  held"]
    for language, s in sorted(report.scores.items()):
        lines.append(
            f"{language:<8}  {s.total:>5}  {_pct(s.right, s.total)}  "
            f"{_pct(s.cut_off, s.incomplete)}   {_pct(s.held, s.complete)}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("manifest", type=Path, help="CSV of file,language,label")
    parser.add_argument("--model", action="append", help="Smart Turn ONNX file, or 'bundled'")
    args = parser.parse_args(argv)
    clips = read_manifest(args.manifest)
    for model in args.model or [BUNDLED]:
        print(render(model, evaluate(clips, smart_turn(model))))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
