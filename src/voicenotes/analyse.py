"""Rule-based meeting analysis: summary, topics, decisions, questions and action items.

The rules are intentionally transparent so every extracted item can be traced to a transcript line.
An LLM can replace them (see :mod:`voicenotes.llm_analyse`), but this path always works offline.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date

from .dates import find_due
from .transcript import Transcript, fmt_time

STOP = frozenset(
    """a about after again all also am an and any are as at be because been before being but by can could did
    do does doing don't down for from get got had has have having he her here him his how i i'll i'm if in into
    is it it's its just know let let's like me more most my no not now of off ok okay on one only or other our
    out over please really right same say see she should so some still sure than thanks that that's the their
    them then there these they thing things think this those three to today tomorrow too two up us very want
    was we we'll we're we've well were what when where which while who why will with would yeah yes you your
    morning everyone great quick update all good first next week time least around new""".split()
)
PRIORITY_WORDS = re.compile(r"\b(urgent|asap|critical|blocker|top priority|immediately|right away)\b", re.I)
DECISION_RE = re.compile(
    r"\b(?:we(?:'ve| have)? (?:decided|agreed)|decision\s*:|let's go with|we're going with|we will go with|"
    r"it's decided|approved)\b", re.I)
EXPLICIT_RE = re.compile(r"^(?:action(?: item)?|todo|to-do|follow[- ]up)\s*[:\-]\s*(?P<task>.+)$", re.I)
SELF_RE = re.compile(r"\b(?:I'll|I will|I can|I'm going to|I am going to|I'm gonna|let me)\s+(?P<task>.+)$", re.I)
REQUEST_RE = re.compile(r"\b(?:can|could|would) you(?: please)?\s+(?P<task>.+?)\??$", re.I)
PLEASE_RE = re.compile(r"\bplease\s+(?P<task>.+)$", re.I)
TEAM_RE = re.compile(r"\b(?:we need to|we should|we must|we have to|let's|we'll|we will)\s+(?P<task>.+)$", re.I)
NON_TASKS = ("be ", "say ", "admit", "guess", "think", "bet ", "get started", "go ", "begin", "start", "move on",
             "wrap up", "see ", "keep it", "talk about")
NOT_NAMES = frozenset("Okay Ok So Sure Yes Yeah Right Well Also Great Thanks Then Now Hey Hi And But Please".split())
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class ActionItem:
    task: str
    owner: str
    due: str | None = None
    due_phrase: str | None = None
    priority: str = "normal"
    source: str = ""  # "[01:40] Amira"
    quote: str = ""


@dataclass
class Decision:
    text: str
    speaker: str
    at: str = ""


@dataclass
class Question:
    text: str
    speaker: str
    at: str = ""
    answer: str = ""


@dataclass
class MeetingNotes:
    title: str
    meeting_date: str
    duration: str | None
    participants: dict[str, float]
    summary: list[str]
    topics: list[str]
    decisions: list[Decision] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    engine: str = "text"
    analyser: str = "rules"
    source: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text.strip()) if s.strip()]


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9'-]+", text.lower()) if w not in STOP and len(w) > 2]


def _clean_task(task: str, names: list[str]) -> str:
    task = task.strip().rstrip(".!?").strip()
    if names:
        cut = re.search(rf",\s*(?:{'|'.join(map(re.escape, names))})\b", task)
        if cut:
            task = task[: cut.start()]
    task = re.split(r"\s*(?:;|, but |, because | - )", task)[0]
    task = re.sub(r"^(?:please|also|then|just)\s+", "", task, flags=re.I).strip(" ,")
    return task[:1].upper() + task[1:] if task else task


def _overlap(a: str, b: str) -> float:
    ta, tb = set(_tokens(a)), set(_tokens(b))
    return len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0.0


def extract_topics(transcript: Transcript, n: int = 6) -> list[str]:
    uni: Counter[str] = Counter()
    bi: Counter[str] = Counter()
    for seg in transcript.segments:
        for sent in _sentences(seg.text):
            words = re.findall(r"[a-z][a-z0-9'-]+", sent.lower())
            toks = [w for w in words if w not in STOP and len(w) > 2]
            uni.update(toks)
            for a, b in zip(words, words[1:], strict=False):
                if a not in STOP and b not in STOP and len(a) > 2 and len(b) > 2:
                    bi[f"{a} {b}"] += 1
    scored = {k: v * 1.6 for k, v in bi.items() if v >= 2}
    scored.update({k: float(v) for k, v in uni.items() if v >= 2})
    topics: list[str] = []
    for term, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0])):
        if any(term in t.split() or term in t for t in topics) or any(t in term.split() for t in topics):
            continue
        topics.append(term)
        if len(topics) == n:
            break
    return topics


def summarise(transcript: Transcript, n: int = 3) -> list[str]:
    freq = Counter(t for s in transcript.segments for t in _tokens(s.text))
    candidates = []
    for order, seg in enumerate(transcript.segments):
        for sent in _sentences(seg.text):
            toks = _tokens(sent)
            if sent.endswith("?") or len(toks) < 4:
                continue
            score = sum(math.log1p(freq[t]) for t in set(toks)) / math.sqrt(len(toks))
            candidates.append((score, order, f"{seg.speaker}: {sent}"))
    best = sorted(candidates, key=lambda c: -c[0])[:n]
    return [c[2] for c in sorted(best, key=lambda c: c[1])]


def _priority(sentence: str, context: str, due: date | None, today: date) -> str:
    if PRIORITY_WORDS.search(sentence) or PRIORITY_WORDS.search(context):
        return "high"
    if due is not None and (due - today).days <= 1:
        return "high"
    return "normal"


def extract(transcript: Transcript, today: date) -> tuple[list[ActionItem], list[Decision], list[Question]]:
    names = transcript.speakers
    actions: list[ActionItem] = []
    decisions: list[Decision] = []
    questions: list[Question] = []
    segs = transcript.segments
    for idx, seg in enumerate(segs):
        at = fmt_time(seg.start) if seg.start is not None else ""
        source = f"[{at}] {seg.speaker}" if at else seg.speaker
        next_speaker = next((s.speaker for s in segs[idx + 1 :] if s.speaker != seg.speaker), "Unassigned")
        prev_sents: list[str] = []
        for sent in _sentences(seg.text):
            context = " ".join(prev_sents[-1:])
            prev_sents.append(sent)
            if DECISION_RE.search(sent):
                decisions.append(Decision(sent.rstrip("."), seg.speaker, at))
                continue
            owner = task = None
            if m := EXPLICIT_RE.search(sent):
                body = m.group("task")
                who = re.match(r"^([A-Z][a-z]+)\s+(?:to|will|should|must)\s+(.+)$", body)
                owner, task = (who.group(1), who.group(2)) if who else ("Unassigned", body)
            elif m := REQUEST_RE.search(sent):
                addressed = re.match(r"^([A-Z][a-z]+),\s", sent)
                name = addressed.group(1) if addressed and addressed.group(1) not in NOT_NAMES else None
                owner, task = name or next_speaker, m.group("task")
            elif m := PLEASE_RE.search(sent):
                mentioned = [n for n in names if n != seg.speaker and re.search(rf"\b{re.escape(n)}\b", sent)]
                owner, task = (mentioned[0] if mentioned else next_speaker), m.group("task")
            elif m := SELF_RE.search(sent):
                owner, task = seg.speaker, m.group("task")
            elif (m := re.search(rf"\b({'|'.join(map(re.escape, names))})\s+(?:will|is going to|needs to|to)\s+"
                                 r"(?P<task>.+)$", sent)) and names:
                owner, task = m.group(1), m.group("task")
            elif m := TEAM_RE.search(sent):
                owner, task = "Team", m.group("task")
            if task and owner not in (seg.speaker, "Team"):
                # "Can you review my PR?" -> "Review Sana's PR" once the owner is someone else
                task = re.sub(r"\bmy\b", f"{seg.speaker}'s", task)
                task = re.sub(r"\bme\b", seg.speaker, task)
            if task and not task.lower().startswith(NON_TASKS):
                phrase, due, rest = find_due(task, today)
                cleaned = _clean_task(rest, names)
                if len(cleaned.split()) >= 2:
                    actions.append(ActionItem(cleaned, owner, due.isoformat() if due else None, phrase,
                                              _priority(sent, context, due, today), source, sent))
                    continue
            if sent.endswith("?") and len(sent.split()) >= 4:
                answer = ""
                if idx + 1 < len(segs) and segs[idx + 1].speaker != seg.speaker:
                    first = _sentences(segs[idx + 1].text)
                    answer = f"{segs[idx + 1].speaker}: {first[0]}" if first else ""
                questions.append(Question(sent, seg.speaker, at, answer))
    return _dedupe(actions), decisions, questions


def _dedupe(items: list[ActionItem]) -> list[ActionItem]:
    """Merge a request and its acknowledgement ("Tom, can you X?" / "I'll X") into one item."""
    merged: list[ActionItem] = []
    rank = {"normal": 0, "high": 1}
    for item in items:
        twin = next((m for m in merged if m.owner == item.owner and _overlap(m.task, item.task) >= 0.5), None)
        if twin is None:
            merged.append(item)
            continue
        if len(item.task) > len(twin.task):
            twin.task, twin.quote = item.task, item.quote
        if rank[item.priority] > rank[twin.priority]:
            twin.priority = item.priority
        if item.due and (not twin.due or item.due < twin.due):
            twin.due, twin.due_phrase = item.due, item.due_phrase
    return merged


def analyse(transcript: Transcript, meeting_date: date | None = None, engine: str = "text") -> MeetingNotes:
    today = meeting_date or date.today()
    actions, decisions, questions = extract(transcript, today)
    duration = transcript.duration
    return MeetingNotes(
        title=transcript.title or "Meeting notes",
        meeting_date=today.isoformat(),
        duration=fmt_time(duration) if duration else None,
        participants={k: round(v, 3) for k, v in transcript.talk_share().items()},
        summary=summarise(transcript),
        topics=extract_topics(transcript),
        decisions=decisions,
        action_items=actions,
        questions=questions,
        engine=engine,
        analyser="rules",
        source=transcript.source,
    )
