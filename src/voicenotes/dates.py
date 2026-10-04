"""Find and resolve relative due-date phrases ("by Friday", "end of the week", "12 Oct")."""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
_DAY = r"(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?"
_CORE = (
    rf"today|tonight|tomorrow|this (?:morning|afternoon|evening)|eod|eow|end of (?:the )?(?:day|week|month)"
    rf"|next week|(?:next |this )?{_DAY}\b|\d{{1,2}}(?:st|nd|rd|th)?(?: of)? {_MON}|{_MON} \d{{1,2}}(?:st|nd|rd|th)?"
)
DUE_RE = re.compile(rf"\s*\b(?:(?:by|before|on|until|due|for)\s+)?(?:the\s+)?(?P<core>{_CORE})\b", re.I)


def _month_index(token: str) -> int:
    token = token.lower()[:3]
    return [m[:3] for m in MONTHS].index(token) + 1


def resolve(phrase: str, today: date) -> date | None:
    p = phrase.lower().strip()
    if p in ("today", "tonight", "eod", "end of day", "end of the day") or p.startswith("this "):
        if not any(p.endswith(d) for d in WEEKDAYS):
            return today
    if p == "tomorrow":
        return today + timedelta(days=1)
    if p in ("eow", "end of week", "end of the week"):
        return today + timedelta(days=max(0, 4 - today.weekday()))
    if p in ("end of month", "end of the month"):
        return today.replace(day=calendar.monthrange(today.year, today.month)[1])
    if p == "next week":
        return today + timedelta(days=7 - today.weekday())
    m = re.fullmatch(rf"(next |this )?({_DAY})", p)
    if m:
        wd = next(i for i, d in enumerate(WEEKDAYS) if d.startswith(m.group(2)[:3]))
        ahead = (wd - today.weekday()) % 7 or 7
        if m.group(1) == "next " and wd > today.weekday():
            ahead += 7
        return today + timedelta(days=ahead)
    m = re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)?(?: of)? ({_MON})|({_MON}) (\d{{1,2}})(?:st|nd|rd|th)?", p)
    if m:
        day = int(m.group(1) or m.group(4))
        month = _month_index(m.group(2) or m.group(3))
        try:
            candidate = date(today.year, month, day)
        except ValueError:
            return None
        return candidate if candidate >= today else candidate.replace(year=today.year + 1)
    return None


def find_due(text: str, today: date) -> tuple[str | None, date | None, str]:
    """Return ``(phrase, resolved_date, text_without_phrase)`` for the first due phrase found."""
    m = DUE_RE.search(text)
    if not m:
        return None, None, text
    phrase = m.group("core")
    cleaned = (text[: m.start()] + text[m.end() :]).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;!?])", r"\1", cleaned)
    return phrase, resolve(phrase, today), cleaned
