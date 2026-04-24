"""Per-call LLM input-token budgets (§12.3).

Each value caps the INPUT side of an LLM call. Inputs longer than the cap
are truncated in `utils/llm.py` (Phase 10) before the network call.
"""

from __future__ import annotations

TOKEN_BUDGETS: dict[str, int] = {
    "intent_parse": 1000,
    "predeploy": 2000,
    "explain": 800,
}
