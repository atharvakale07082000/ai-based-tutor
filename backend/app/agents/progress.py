"""Elo proficiency math — pure, dependency-free.

Ported verbatim from the old ``progress_agent`` so the quiz-submit router and the
``calculate_elo`` tool keep identical behavior (K=32, clamped to [0, 1000]).
"""

from __future__ import annotations

K_FACTOR = 32.0

# Single source of truth: the Elo (proficiency map is 0-1000) at/above which a topic
# counts as mastered. Used by quiz grading, the session engine, the curriculum view,
# the leaderboard, the skill-gap agent, the weekly digest and the evals suite — every
# one of those hardcoded its own `700` before this constant was hoisted here.
MASTERY_ELO: float = 700.0


def calculate_elo_update(
    current_elo: float, score: float, expected_score: float = 0.5
) -> float:
    """Standard Elo update, clamped to [0, 1000].

    score: actual performance 0.0-1.0
    expected_score: prior probability of success (default 0.5)
    """
    new_elo = current_elo + K_FACTOR * (score - expected_score)
    return max(0.0, min(1000.0, new_elo))
