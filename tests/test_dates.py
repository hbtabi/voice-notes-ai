from datetime import date

import pytest

from voicenotes.dates import find_due, resolve

MON = date(2026, 10, 5)  # a Monday


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("today", date(2026, 10, 5)),
        ("tomorrow", date(2026, 10, 6)),
        ("Wednesday", date(2026, 10, 7)),
        ("Monday", date(2026, 10, 12)),
        ("next Friday", date(2026, 10, 16)),
        ("end of the week", date(2026, 10, 9)),
        ("next week", date(2026, 10, 12)),
        ("end of month", date(2026, 10, 31)),
        ("12 November", date(2026, 11, 12)),
        ("March 3rd", date(2027, 3, 3)),
    ],
)
def test_resolve(phrase, expected):
    assert resolve(phrase, MON) == expected


def test_find_due_strips_phrase():
    phrase, due, rest = find_due("send the deck by Friday to the board", MON)
    assert phrase == "Friday" and due == date(2026, 10, 9) and rest == "send the deck to the board"
    assert find_due("no dates here", MON) == (None, None, "no dates here")
