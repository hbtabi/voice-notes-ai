"""Optional LLM analysis. Produces the same :class:`MeetingNotes` shape as the rule engine."""

from __future__ import annotations

from datetime import date

from .analyse import ActionItem, Decision, MeetingNotes, Question, analyse
from .llm import LLMError, OpenAICompatible
from .transcript import Transcript, fmt_time

SYSTEM = """You are a meticulous meeting assistant. Read the transcript and return ONLY a JSON object:
{"summary": [2-4 short sentences], "topics": [up to 6 short noun phrases],
 "decisions": [{"text": str, "speaker": str}],
 "action_items": [{"task": imperative str, "owner": participant name or "Team" or "Unassigned",
                   "due": "YYYY-MM-DD" or null, "priority": "high" | "normal"}],
 "questions": [{"text": str, "speaker": str, "answer": str}]}
Resolve relative dates against the meeting date. Never invent tasks that were not discussed."""


def _transcript_block(t: Transcript) -> str:
    lines = []
    for s in t.segments:
        stamp = f"[{fmt_time(s.start)}] " if s.start is not None else ""
        lines.append(f"{stamp}{s.speaker}: {s.text}")
    return "\n".join(lines)


def llm_analyse(transcript: Transcript, meeting_date: date | None = None, engine: str = "text",
                client: OpenAICompatible | None = None) -> MeetingNotes:
    """Analyse with an LLM, falling back to the rule engine on any error."""
    base = analyse(transcript, meeting_date, engine)  # also supplies duration, participants, etc.
    client = client or OpenAICompatible()
    if not client.available:
        return base
    try:
        prompt = (f"Meeting date: {base.meeting_date}\nParticipants: {', '.join(transcript.speakers)}\n\n"
                  f"Transcript:\n{_transcript_block(transcript)}")
        data = client.chat_json(SYSTEM, prompt)
        base.summary = [str(s) for s in data.get("summary", [])][:4] or base.summary
        base.topics = [str(s) for s in data.get("topics", [])][:6] or base.topics
        base.decisions = [Decision(str(d.get("text", "")), str(d.get("speaker", ""))) for d in data.get("decisions", [])
                          if d.get("text")]
        base.action_items = [
            ActionItem(str(a["task"]), str(a.get("owner") or "Unassigned"), a.get("due"), None,
                       "high" if a.get("priority") == "high" else "normal", "llm")
            for a in data.get("action_items", []) if a.get("task")
        ]
        base.questions = [Question(str(q.get("text", "")), str(q.get("speaker", "")), "", str(q.get("answer", "")))
                          for q in data.get("questions", []) if q.get("text")]
        base.analyser = f"llm:{client.chat_model}"
    except (LLMError, KeyError, TypeError, AttributeError):
        pass
    return base
