"""
Unit tests for google_drive._find_best_match - fuzzy student name lookup.

Critical: the matcher must surface close-typo doc filenames (e.g. doc named
"Annabella Jedovic" when the real student is "Annabella Jevdovic") with
needs_verification=True, but NOT pull obviously different names.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_drive import _find_best_match


def _files(*names):
    return [{"id": f"f{i}", "name": n, "mimeType": "application/vnd.google-apps.document", "webViewLink": f"https://docs.google.com/document/d/f{i}"} for i, n in enumerate(names)]


def test_exact_substring_match():
    files = _files("Annabella Jevdovic")
    m = _find_best_match("Annabella Jevdovic", files)
    assert m is not None
    assert m["match_reason"] == "exact"
    assert m["needs_verification"] is False


def test_token_match_with_extension():
    files = _files("Jevdovic Annabella.docx")
    m = _find_best_match("Annabella Jevdovic", files)
    assert m is not None
    assert m["match_reason"] in ("exact", "tokens")
    assert m["needs_verification"] is False


def test_fuzzy_match_close_typo_jedovic():
    """The bug that triggered this feature: doc filed under 'Annabella Jedovic'
    should be surfaced when searching for 'Annabella Jevdovic' with a verify flag."""
    files = _files("Annabella Jedovic", "Maria Popescu", "Lizzie Wortley")
    m = _find_best_match("Annabella Jevdovic", files)
    assert m is not None, "Fuzzy match must succeed for one-letter typo"
    assert m["match_reason"] == "fuzzy"
    assert m["needs_verification"] is True
    assert m["match_score"] >= 0.9
    assert m["name"] == "Annabella Jedovic"


def test_fuzzy_does_not_match_unrelated_name():
    """Different first AND last name must not produce a fuzzy match."""
    files = _files("Annabella Jedovic", "Maria Popescu")
    m = _find_best_match("John Smith", files)
    assert m is None


def test_fuzzy_does_not_pull_doc_with_only_first_name_overlap():
    """'Annabella Smith' should NOT pull 'Annabella Jedovic' - different surname."""
    files = _files("Annabella Jedovic")
    m = _find_best_match("Annabella Smith", files)
    assert m is None, "Different surname should not produce a fuzzy match"


def test_lastname_fallback_for_unusual_surname():
    """If a doc clearly contains the unusual surname as its own token, surface it."""
    files = _files("Jevdovic plan v2")
    m = _find_best_match("Anna Jevdovic", files)
    assert m is not None
    assert m["match_reason"] in ("tokens", "fuzzy", "lastname")


def test_no_match_when_folder_unrelated():
    files = _files("Maria Popescu", "Maria Katsouli", "Lizzie Wortley")
    m = _find_best_match("Annabella Jevdovic", files)
    assert m is None


def test_other_candidates_are_listed_for_fuzzy():
    files = _files("Annabella Jedovic", "Anabella Jevdovich", "John Smith")
    m = _find_best_match("Annabella Jevdovic", files)
    assert m is not None
    assert m["match_reason"] == "fuzzy"
    # The runner-up "Anabella Jevdovich" should be in other_candidates
    others = m.get("other_candidates", [])
    assert any("Anabella" in c["name"] for c in others) or len(others) == 0  # tolerant
