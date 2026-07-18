"""Shared session constants.

The v1 LangGraph ``AgentState`` TypedDict was retired with the graph engine; only
this mastery threshold survives — it's the Elo (0-1000) at/above which a topic is
considered mastered, used by the session engine and the evals suite.
"""

from __future__ import annotations

# Single source of truth — the Elo at/above which a topic counts as mastered
# (session advance + evals scoring).
MASTERY_THRESHOLD_DEFAULT: float = 700.0
