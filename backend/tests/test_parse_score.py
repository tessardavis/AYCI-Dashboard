"""Regression tests for `interview_eve_dm.parse_score()`.

Pins the Unicode-digit normalisation behaviour. Without NFKC normalisation,
students who reply with a Circle-rendered superscript "⁹" or keycap emoji
"9️⃣" instead of an ASCII "9" silently fail score-capture. Live incident
2026-05-15: Henry Walton replied with U+2079 ('⁹') and his score was lost.
"""
from __future__ import annotations

import os
import sys

# Ensure backend/ is on the path before importing the module under test.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interview_eve_dm import parse_score  # noqa: E402


def test_parse_score_ascii_digits():
    assert parse_score("9") == 9
    assert parse_score("10") == 10
    assert parse_score("1") == 1
    assert parse_score("i'd say 4") == 4
    assert parse_score("maybe 8 today") == 8


def test_parse_score_unicode_digits():
    """Superscripts, keycaps, full-width — all should normalise to ASCII."""
    assert parse_score("⁹") == 9          # U+2079 superscript nine
    assert parse_score("⁸") == 8          # U+2078 superscript eight
    assert parse_score("¹⁰") == 10        # superscript ten
    assert parse_score("9️⃣") == 9          # keycap emoji
    assert parse_score("９") == 9          # U+FF19 full-width nine


def test_parse_score_no_digit_returns_none():
    assert parse_score("Thanks") is None
    assert parse_score("") is None
    assert parse_score(None) is None
    assert parse_score("very supported!") is None


def test_parse_score_long_message_requires_rating_hint():
    """Long replies only count if they contain a rating-like keyword."""
    # No hint → None
    assert parse_score(
        "Hi Coralie, my interview is at 11am tomorrow and I'm prepping",
    ) is None
    # With hint "supported" → matches the standalone digit
    assert parse_score(
        "I feel very supported, I'd say 8 out of how I felt last week",
    ) == 8


def test_parse_score_multidigit_doesnt_match():
    """11am must NOT be parsed as 1 (word-boundary requirement)."""
    assert parse_score("see you at 11am") is None
    assert parse_score("call at 12pm") is None
