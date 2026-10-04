"""``voice-notes`` command-line interface."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .analyse import analyse
from .llm_analyse import llm_analyse
from .render import to_json, to_markdown, to_terminal
from .transcribe import ENGINES, TranscriptionError, engine_status, is_audio, transcribe, wav_duration
from .transcript import load_transcript, sample_transcript


def _process(args: argparse.Namespace, source: str | None) -> int:
    meeting_date = date.fromisoformat(args.date) if args.date else date.today()
    if source is None:
        transcript, engine = sample_transcript(), "sample"
    elif is_audio(source):
        secs = wav_duration(source)
        try:
            transcript, engine = transcribe(source, engine=args.engine, model=args.model)
        except TranscriptionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if engine == "sample":
            print("note: no transcription engine available - using the bundled sample transcript. "
                  "Install faster-whisper or set OPENAI_API_KEY (see `voice-notes engines`).", file=sys.stderr)
        elif secs:
            print(f"transcribed {secs:.1f}s of audio with {engine}", file=sys.stderr)
    else:
        if not Path(source).exists():
            print(f"error: file not found: {source}", file=sys.stderr)
            return 2
        transcript, engine = load_transcript(source), "text"
    if args.title:
        transcript.title = args.title

    if args.llm:
        notes = llm_analyse(transcript, meeting_date, engine)
        if notes.analyser == "rules":
            print("note: LLM unavailable or failed - used the offline rule engine", file=sys.stderr)
    else:
        notes = analyse(transcript, meeting_date, engine)

    rendered = {"md": to_markdown, "json": to_json, "text": to_terminal}[args.format](notes)
    if args.out:
        Path(args.out).write_text(rendered if rendered.endswith("\n") else rendered + "\n", encoding="utf-8")
        n_a, n_d = len(notes.action_items), len(notes.decisions)
        print(f"wrote {args.out} ({n_a} action item{'s' * (n_a != 1)}, {n_d} decision{'s' * (n_d != 1)})",
              file=sys.stderr)
    else:
        print(rendered)
    return 0


def cmd_engines(_: argparse.Namespace) -> int:
    for s in engine_status():
        mark = "✔" if s.available else "✘"
        print(f"{mark} {s.name:<15} {s.detail}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="voice-notes", description="Meeting audio/transcripts -> action items.")
    p.add_argument("--version", action="version", version=f"voice-notes-ai {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("-f", "--format", choices=["text", "md", "json"], default="text")
        sp.add_argument("-o", "--out", help="write output to a file")
        sp.add_argument("--date", help="meeting date (YYYY-MM-DD) used to resolve 'Friday', 'tomorrow'...")
        sp.add_argument("--title", help="override the meeting title")
        sp.add_argument("--llm", action="store_true", help="analyse with an OpenAI-compatible LLM if configured")

    sp = sub.add_parser("process", help="process an audio file or transcript (.txt/.srt/.vtt)")
    sp.add_argument("input")
    sp.add_argument("--engine", choices=ENGINES, default="auto", help="speech-to-text engine for audio input")
    sp.add_argument("--model", help="whisper model size/name (default: base)")
    common(sp)
    sp.set_defaults(func=lambda a: _process(a, a.input))

    sp = sub.add_parser("demo", help="run the pipeline on the bundled sample meeting")
    common(sp)
    sp.set_defaults(func=lambda a: _process(a, None), engine="sample", model=None)

    sp = sub.add_parser("engines", help="show which transcription engines are available")
    sp.set_defaults(func=cmd_engines)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
