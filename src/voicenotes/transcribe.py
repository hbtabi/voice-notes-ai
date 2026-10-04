"""Speech-to-text engines with graceful fallback.

``auto`` tries, in order: faster-whisper, openai-whisper, an OpenAI-compatible ``/audio/transcriptions``
endpoint, and finally the bundled sample transcript (so the pipeline always runs offline).
"""

from __future__ import annotations

import importlib.util
import os
import wave
from dataclasses import dataclass
from pathlib import Path

from .llm import OpenAICompatible
from .transcript import Segment, Transcript, sample_transcript

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm", ".mp4", ".aac", ".opus"}
ENGINES = ("auto", "faster-whisper", "whisper", "api", "sample")


class TranscriptionError(RuntimeError):
    pass


@dataclass
class EngineStatus:
    name: str
    available: bool
    detail: str


def is_audio(path: str | Path) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXTS


def wav_duration(path: str | Path) -> float | None:
    """Duration in seconds for PCM WAV files (None for other formats)."""
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError, OSError):
        return None


def engine_status() -> list[EngineStatus]:
    client = OpenAICompatible()
    return [
        EngineStatus("faster-whisper", importlib.util.find_spec("faster_whisper") is not None,
                     "pip install 'voice-notes-ai[whisper]'"),
        EngineStatus("whisper", importlib.util.find_spec("whisper") is not None,
                     "pip install 'voice-notes-ai[openai-whisper]'"),
        EngineStatus("api", client.available, f"OPENAI_API_KEY set -> {client.base_url} ({client.stt_model})"
                     if client.available else "set OPENAI_API_KEY (any OpenAI-compatible server)"),
        EngineStatus("sample", True, "bundled demo transcript (offline fallback)"),
    ]


def _faster_whisper(path: Path, model: str) -> Transcript:
    from faster_whisper import WhisperModel  # type: ignore[import-not-found]

    segs, _info = WhisperModel(model, device="auto", compute_type="int8").transcribe(str(path), vad_filter=True)
    return Transcript([Segment(s.text.strip(), "Speaker", s.start, s.end) for s in segs], source=str(path))


def _openai_whisper(path: Path, model: str) -> Transcript:
    import whisper  # type: ignore[import-not-found]

    result = whisper.load_model(model).transcribe(str(path))
    return Transcript([Segment(s["text"].strip(), "Speaker", s["start"], s["end"]) for s in result["segments"]],
                      source=str(path))


def _api(path: Path) -> Transcript:
    data = OpenAICompatible().transcribe(path)
    segs = data.get("segments") or []
    if segs:
        return Transcript([Segment(s["text"].strip(), "Speaker", s.get("start"), s.get("end")) for s in segs],
                          source=str(path))
    return Transcript([Segment(data.get("text", "").strip(), "Speaker")], source=str(path))


def transcribe(path: str | Path, engine: str = "auto", model: str | None = None) -> tuple[Transcript, str]:
    """Return ``(transcript, engine_used)``."""
    path = Path(path)
    model = model or os.getenv("VOICENOTES_WHISPER_MODEL", "base")
    if engine not in ENGINES:
        raise TranscriptionError(f"unknown engine {engine!r}; choose from {', '.join(ENGINES)}")
    if engine == "sample":
        return sample_transcript(), "sample"
    if not path.exists():
        raise TranscriptionError(f"audio file not found: {path}")

    status = {s.name: s.available for s in engine_status()}
    order = ["faster-whisper", "whisper", "api"] if engine == "auto" else [engine]
    runners = {"faster-whisper": lambda: _faster_whisper(path, model), "whisper": lambda: _openai_whisper(path, model),
               "api": lambda: _api(path)}
    errors = []
    for name in order:
        if not status[name]:
            errors.append(f"{name}: not available")
            continue
        try:
            return runners[name](), name
        except Exception as exc:  # noqa: BLE001 - surface any backend failure and try the next one
            errors.append(f"{name}: {exc}")
    if engine == "auto":
        return sample_transcript(), "sample"
    raise TranscriptionError("; ".join(errors))
