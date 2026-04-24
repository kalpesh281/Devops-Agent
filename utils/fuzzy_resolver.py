"""rapidfuzz wrappers for entity resolution (§10.5).

Used by:
- Telegram inline mode / keyboard fallbacks (Phase 3) — top-N fuzzy match
- "Did you mean?" resolution on typo'd command args (Phase 3)
- Identifier resolution on <name> args (Phase 4 — `utils/identifiers.py` delegates)
"""

from __future__ import annotations

from collections.abc import Sequence

from rapidfuzz import process


def fuzzy_resolve(
    query: str,
    choices: Sequence[str],
    score_cutoff: int = 60,
) -> tuple[str, float] | None:
    """Return the single best match above `score_cutoff`, or None.

    Score is 0..100 (rapidfuzz default scorer).
    """
    if not query or not choices:
        return None
    result = process.extractOne(query, list(choices), score_cutoff=score_cutoff)
    if result is None:
        return None
    match, score, _index = result
    return match, float(score)


def fuzzy_extract(
    query: str,
    choices: Sequence[str],
    limit: int = 10,
    score_cutoff: int = 40,
) -> list[tuple[str, float]]:
    """Return up to `limit` matches above `score_cutoff`, sorted by score DESC."""
    if not choices:
        return []
    if not query:
        # No query = return the first `limit` choices (for empty inline-query UX).
        return [(c, 100.0) for c in list(choices)[:limit]]
    results = process.extract(query, list(choices), limit=limit)
    return [(m, float(s)) for m, s, _ in results if s >= score_cutoff]
