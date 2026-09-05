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

# ── Elo → cognitive level ─────────────────────────────────────────────────────
# The other half of the proficiency model, hoisted here for the same reason as
# MASTERY_ELO: this ladder existed twice, byte-identical, in `hf/quiz_questions.py`
# (BLOOM_BY_ELO / bloom_for_elo) and `agents/session.py` (BLOOM_LEVEL_BY_ELO /
# get_bloom_level). Both now re-export from here, so quiz generation, the session
# engine and the chat specialists agree on what level a learner is at.

BLOOM_LEVELS: list[str] = [
    "remember",
    "understand",
    "apply",
    "analyze",
    "evaluate",
    "create",
]

BLOOM_BY_ELO: list[tuple[tuple[int, int], str]] = [
    ((0, 300), "remember"),
    ((300, 450), "understand"),
    ((450, 600), "apply"),
    ((600, 720), "analyze"),
    ((720, 870), "evaluate"),
    ((870, 1001), "create"),
]


def bloom_for_elo(elo: float) -> str:
    """Map an Elo score to the appropriate Bloom taxonomy level."""
    for (low, high), level in BLOOM_BY_ELO:
        if low <= elo < high:
            return level
    return "understand"


def calculate_elo_update(
    current_elo: float, score: float, expected_score: float = 0.5
) -> float:
    """Standard Elo update, clamped to [0, 1000].

    score: actual performance 0.0-1.0
    expected_score: prior probability of success (default 0.5)
    """
    new_elo = current_elo + K_FACTOR * (score - expected_score)
    return max(0.0, min(1000.0, new_elo))


def job_readiness(
    topic_proficiency: dict[str, float] | None,
    interviews: list[dict] | None,
) -> float | None:
    """How ready this learner is for their target role, 0-100, or None if unknowable.

    Pure like the rest of this module: the caller supplies the evidence, so this stays
    testable and free of Mongo. It reads only things the platform has actually *graded* —
    topic mastery and finished interviews — never activity (topics added, sessions opened),
    because activity is not achievement. The dashboard tile hid behind an invented
    ``topics_tracked / 10`` figure before this existed; returning ``None`` is what lets the
    UI show nothing rather than a 0% that reads as a verdict on a brand-new account.

    Two components, blended when both exist:
      * mastery  — share of tracked topics at/above ``MASTERY_ELO``
      * interviews — mean of ``final_score / bar``, each round judged against the bar it was
        actually set (a staff round and an intern round do not clear at the same number)

    Interviews carry the larger weight: answering live under questioning is stronger evidence
    than a proficiency score accumulated from quizzes.
    """
    from app.agents.bar import DEFAULT_BAR

    prof = topic_proficiency or {}
    mastery: float | None = None
    if prof:
        mastered = sum(1 for elo in prof.values() if (elo or 0) >= MASTERY_ELO)
        mastery = mastered / len(prof)

    graded = [
        iv
        for iv in (interviews or [])
        if isinstance(iv, dict) and iv.get("final_score") is not None
    ]
    interview: float | None = None
    if graded:
        ratios = []
        for iv in graded:
            bar = iv.get("bar")
            # A missing or nonsense bar means "the platform default", never a divide-by-zero.
            bar = (
                float(bar) if isinstance(bar, (int, float)) and bar > 0 else DEFAULT_BAR
            )
            ratios.append(min(1.0, max(0.0, float(iv["final_score"]) / bar)))
        interview = sum(ratios) / len(ratios)

    if mastery is None and interview is None:
        return None
    if mastery is None:
        score = interview
    elif interview is None:
        score = mastery
    else:
        score = 0.4 * mastery + 0.6 * interview

    return round(max(0.0, min(1.0, float(score))) * 100.0, 1)
