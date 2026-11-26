"""The turn model and its silence fallback are configurable; the offline scorer reports per
language how often a model cuts a caller off or holds them for the fallback."""

import wave
from pathlib import Path

import numpy as np
import pytest
from pipecat.audio.turn.smart_turn import data as bundled_models

from engine import turn_eval, turns


def test_by_default_the_bundled_model_and_a_2_s_fallback_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(turns.MODEL_ENV, raising=False)
    monkeypatch.delenv(turns.SILENCE_ENV, raising=False)

    assert turns.model_path() is None
    assert turns.analyzer("te").params.stop_secs == 2.0


def test_another_model_file_is_loaded_and_a_missing_one_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model = Path(bundled_models.__file__).parent / "smart-turn-v3.2-cpu.onnx"
    monkeypatch.setenv(turns.MODEL_ENV, str(model))
    assert turns.model_path() == str(model)
    turns.analyzer("en")  # loads the named file

    monkeypatch.setenv(turns.MODEL_ENV, str(tmp_path / "indic.onnx"))
    with pytest.raises(ValueError, match=turns.MODEL_ENV):
        turns.check()


def test_the_fallback_can_differ_by_language_and_others_keep_2_s(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(turns.SILENCE_ENV, "en=1.5, hi=1.2")

    assert turns.silence_s("en") == 1.5
    assert turns.analyzer("hi").params.stop_secs == 1.2
    assert turns.silence_s("te") == 2.0


@pytest.mark.parametrize("value", ["en", "en=fast", "en=0.1", "en=9", "te=2,en"])
def test_a_wrong_fallback_setting_fails_at_start_up(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(turns.SILENCE_ENV, value)
    with pytest.raises(ValueError, match=turns.SILENCE_ENV):
        turns.check()


def _wav(path: Path, seconds: float, rate: int = 16000) -> None:
    samples = (np.sin(np.arange(int(seconds * rate)) / 5) * 8000).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())


def _manifest(folder: Path) -> Path:
    rows = [
        ("te-done.wav", "te", "complete"),
        ("te-pause.wav", "te", "incomplete"),
        ("te-done-2.wav", "te", "complete"),
        ("en-done.wav", "en", "complete"),
    ]
    for name, _, _ in rows:
        _wav(folder / name, 1.0)
    manifest = folder / "pauses.csv"
    manifest.write_text(
        "file,language,label\n" + "".join(f"{f},{lang},{label}\n" for f, lang, label in rows),
        encoding="utf-8",
    )
    return manifest


def test_the_report_counts_right_answers_cut_offs_and_held_turns(tmp_path: Path) -> None:
    clips = turn_eval.read_manifest(_manifest(tmp_path))
    always_complete = turn_eval.evaluate(clips, lambda _: True)
    never_complete = turn_eval.evaluate(clips, lambda _: False)

    te = always_complete.scores["te"]
    assert (te.total, te.right, te.cut_off, te.held) == (3, 2, 1, 0)
    te = never_complete.scores["te"]
    assert (te.right, te.cut_off, te.held) == (1, 0, 2)
    assert "te            3   66.7%  100.0%" in turn_eval.render("x", always_complete)


def test_phone_audio_is_resampled_to_the_models_16_khz(tmp_path: Path) -> None:
    _wav(tmp_path / "phone.wav", 1.0, rate=8000)
    assert len(turn_eval.read_wav(tmp_path / "phone.wav")) == 16000


def test_a_row_without_a_label_is_refused(tmp_path: Path) -> None:
    manifest = tmp_path / "bad.csv"
    manifest.write_text("file,language,label\na.wav,te,maybe\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.csv:2"):
        turn_eval.read_manifest(manifest)


def test_the_script_scores_the_bundled_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert turn_eval.main([str(_manifest(tmp_path)), "--model", "bundled"]) == 0
    out = capsys.readouterr().out
    assert "model: bundled" in out and "\nte " in out and "\nen " in out
