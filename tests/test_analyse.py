from datetime import date

from voicenotes.analyse import analyse, extract_topics
from voicenotes.transcript import parse_text, sample_transcript

MON = date(2026, 10, 5)


def _by_owner(notes):
    out = {}
    for a in notes.action_items:
        out.setdefault(a.owner, []).append(a)
    return out


def test_sample_meeting_action_items():
    notes = analyse(sample_transcript(), MON)
    owners = _by_owner(notes)
    assert set(owners) == {"Daniel", "Tom", "Priya", "Team", "Amira"}
    assert len(owners["Daniel"]) == 3
    cert = next(a for a in owners["Daniel"] if "certificate" in a.task)
    assert cert.priority == "high" and cert.due == "2026-10-05"
    tom = owners["Tom"]
    assert len(tom) == 1 and tom[0].due == "2026-10-09"  # request + acknowledgement merged
    release = next(a for a in owners["Daniel"] if "release notes" in a.task)
    assert release.due == "2026-10-09" and release.task == "Send the release notes to the beta testers"


def test_sample_meeting_decisions_questions_summary():
    notes = analyse(sample_transcript(), MON)
    assert len(notes.decisions) == 3
    assert any("magic link" in d.text for d in notes.decisions)
    assert any(q.answer.startswith("Daniel: It is") for q in notes.questions)
    assert 1 <= len(notes.summary) <= 3
    assert notes.duration == "03:47" and notes.title.startswith("Weekly product sync")
    assert "magic link" in notes.topics


def test_non_tasks_and_suggestions_are_ignored():
    t = parse_text("A: Let's get started.\nB: We could maybe try a new logo.\nA: I think that is fine.")
    assert analyse(t, MON).action_items == []


def test_request_goes_to_addressee_or_next_speaker():
    t = parse_text("Ana: Ben, can you book the venue by Thursday?\nCal: Could you send the slides?\nAna: Sure.")
    items = analyse(t, MON).action_items
    assert [(a.owner, a.task) for a in items] == [("Ben", "Book the venue"), ("Ana", "Send the slides")]
    assert items[0].due == "2026-10-08"


def test_topics_prefer_repeated_phrases():
    t = parse_text("A: The magic link works.\nB: The magic link is fast.\nA: Fast magic link indeed.")
    assert extract_topics(t)[0] == "magic link"
