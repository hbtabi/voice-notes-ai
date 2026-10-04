"""Transcript model and parsers for plain text, SRT and WebVTT."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

_TS = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"
_LINE = re.compile(rf"^\s*(?:\[?{_TS}\]?\s*[-–]?\s*)?(?:([A-Z][\w .'-]{{0,30}}?)\s*:\s+)?(.+?)\s*$")
_CUE = re.compile(rf"{_TS}\s*-->\s*{_TS}")
_VOICE = re.compile(r"^<v\s+([^>]+)>(.*?)(?:</v>)?$")


def _seconds(h: str | None, m: str, s: str, ms: str | None) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + (int(ms.ljust(3, "0")) / 1000 if ms else 0.0)


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


@dataclass
class Segment:
    text: str
    speaker: str = "Speaker"
    start: float | None = None
    end: float | None = None


@dataclass
class Transcript:
    segments: list[Segment] = field(default_factory=list)
    source: str = ""
    title: str = ""

    @property
    def speakers(self) -> list[str]:
        seen: dict[str, None] = {}
        for s in self.segments:
            seen.setdefault(s.speaker, None)
        return list(seen)

    @property
    def duration(self) -> float | None:
        times = [t for s in self.segments for t in (s.start, s.end) if t is not None]
        return max(times) if times else None

    @property
    def text(self) -> str:
        return "\n".join(f"{s.speaker}: {s.text}" for s in self.segments)

    def talk_share(self) -> dict[str, float]:
        counts: dict[str, int] = {}
        for s in self.segments:
            counts[s.speaker] = counts.get(s.speaker, 0) + len(s.text.split())
        total = sum(counts.values()) or 1
        return {k: v / total for k, v in sorted(counts.items(), key=lambda kv: -kv[1])}


def parse_text(text: str, source: str = "") -> Transcript:
    """Parse ``[00:01:02] Name: words`` style lines; timestamps and speakers are optional.

    A leading ``# Title`` line becomes the transcript title. Lines without a speaker continue the
    previous speaker's turn.
    """
    segments: list[Segment] = []
    title = ""
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if raw.startswith("#") and not segments and not title:
            title = raw.lstrip("#").strip()
            continue
        m = _LINE.match(raw)
        if not m:
            continue
        h, mi, s, ms, speaker, body = m.groups()
        start = _seconds(h, mi, s, ms) if mi is not None else None
        if speaker is None and segments and start is None:
            segments[-1].text += " " + body
            continue
        segments.append(Segment(text=body, speaker=(speaker or (segments[-1].speaker if segments else "Speaker")),
                                start=start))
    for cur, nxt in zip(segments, segments[1:], strict=False):
        if cur.end is None and nxt.start is not None:
            cur.end = nxt.start
    return Transcript(segments, source=source, title=title)


def parse_subtitles(text: str, source: str = "") -> Transcript:
    """Parse SRT or WebVTT cues (``<v Name>`` voice tags and ``Name:`` prefixes become speakers)."""
    segments: list[Segment] = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    for block in blocks:
        lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
        cue_idx = next((i for i, ln in enumerate(lines) if _CUE.search(ln)), None)
        if cue_idx is None:
            continue
        g = _CUE.search(lines[cue_idx]).groups()
        start, end = _seconds(*g[:4]), _seconds(*g[4:])
        body = " ".join(lines[cue_idx + 1 :])
        speaker = "Speaker"
        v = _VOICE.match(body)
        if v:
            speaker, body = v.group(1).strip(), v.group(2).strip()
        elif re.match(r"^[A-Z][\w .'-]{0,30}:\s", body):
            speaker, body = (p.strip() for p in body.split(":", 1))
        body = re.sub(r"<[^>]+>", "", body).strip()
        if body:
            segments.append(Segment(body, speaker, start, end))
    return Transcript(segments, source=source)


def load_transcript(path: str | Path) -> Transcript:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".srt", ".vtt") or "-->" in text[:500]:
        return parse_subtitles(text, source=str(path))
    return parse_text(text, source=str(path))


def sample_transcript() -> Transcript:
    """The bundled demo meeting, used when no transcription engine is available."""
    text = resources.files("voicenotes").joinpath("data/sample_meeting.txt").read_text(encoding="utf-8")
    return parse_text(text, source="sample:sample_meeting.txt")
