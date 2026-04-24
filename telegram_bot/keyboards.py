"""InlineKeyboardMarkup builders (§10.4).

Phase 3 deliberately minimal — most keyboards come online in Phases 5 (deploy
progress), 7 (HITL approvals), and 8 (logs/report navigation).
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_confirm_keyboard(action: str, target: str) -> InlineKeyboardMarkup:
    """Used by `/branches trding` → 'did you mean trading?' flow in later phases."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes", callback_data=f"{action}:{target}"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
            ]
        ]
    )
