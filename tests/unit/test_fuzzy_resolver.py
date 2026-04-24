"""Tests for fuzzy_resolve + fuzzy_extract."""

from __future__ import annotations

from utils.fuzzy_resolver import fuzzy_extract, fuzzy_resolve


def test_resolve_exact_match() -> None:
    result = fuzzy_resolve("trading-dashboard", ["trading-dashboard", "portfolio-site"])
    assert result is not None
    match, score = result
    assert match == "trading-dashboard"
    assert score == 100.0


def test_resolve_typo() -> None:
    result = fuzzy_resolve("trding-dashbord", ["trading-dashboard", "portfolio-site"])
    assert result is not None
    match, score = result
    assert match == "trading-dashboard"
    assert score >= 60


def test_resolve_below_cutoff_returns_none() -> None:
    assert fuzzy_resolve("zzzzz", ["trading-dashboard"], score_cutoff=90) is None


def test_resolve_empty_query_returns_none() -> None:
    assert fuzzy_resolve("", ["a", "b"]) is None


def test_resolve_empty_choices_returns_none() -> None:
    assert fuzzy_resolve("trading", []) is None


def test_extract_top_n() -> None:
    choices = ["trading", "trading-bot", "trading-dashboard", "trade-analytics"]
    results = fuzzy_extract("trading", choices, limit=3)
    assert len(results) <= 3
    assert all(isinstance(s, float) and 0 <= s <= 100 for _, s in results)
    # top result should contain "trading"
    assert "trading" in results[0][0].lower()


def test_extract_empty_query_returns_first_n() -> None:
    choices = ["a", "b", "c", "d", "e"]
    results = fuzzy_extract("", choices, limit=3)
    assert len(results) == 3
    assert [c for c, _ in results] == ["a", "b", "c"]


def test_extract_empty_if_all_below_cutoff() -> None:
    assert fuzzy_extract("xyzz", ["foo", "bar"], score_cutoff=99) == []
