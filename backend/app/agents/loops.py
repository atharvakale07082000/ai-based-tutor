"""Interview loops — the domain logic behind a company-specific interview gauntlet.

A *loop* is an ordered set of rounds mirroring the process a real employer runs
(recruiter screen → coding → system design → behavioural). Each round is conducted by
the existing interrupt-driven interview agent and graded against a bar calibrated to
the job's seniority, rather than the flat platform default every module interview uses.

This module holds the pure parts — round-plan validation, the default ladder, and the
status transitions — so they are unit-testable without a database or an LLM. The I/O
lives in ``pipelines/loop_setup.py`` and ``routers/interview_loops.py``.

Round documents deliberately mirror what ``course_planner.start_interview`` needs, so
starting a round is a straight hand-off with no translation layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.agents.bar import ROUND_KINDS, round_bar

# Loop-level and round-level statuses.
ROUND_LOCKED = "locked"
ROUND_AVAILABLE = "available"
ROUND_IN_PROGRESS = "in_progress"
ROUND_PASSED = "passed"
ROUND_FAILED = "failed"

_RESOLVED = {ROUND_PASSED, ROUND_FAILED}

LOOP_IN_PROGRESS = "in_progress"
LOOP_PASSED = "passed"
LOOP_FAILED = "failed"

# A loop shorter than this is not a loop; longer than this is a slog nobody finishes.
MIN_ROUNDS = 2
MAX_ROUNDS = 5

# Per-kind question budgets. A system-design round is one problem taken deep; a screen
# is several short questions. Without this every round would inherit the platform-wide
# ceiling and feel identical.
_ROUND_BUDGETS: dict[str, tuple[int, int]] = {
    "screen": (3, 4),
    "coding": (2, 3),
    "system_design": (1, 2),
    "behavioral": (3, 5),
}

_ROUND_TITLES: dict[str, str] = {
    "screen": "Recruiter screen",
    "coding": "Coding round",
    "system_design": "System design",
    "behavioral": "Behavioural round",
}

# Used when the LLM's proposed ladder is unusable. Deliberately generic and safe.
_DEFAULT_KINDS: tuple[str, ...] = ("screen", "coding", "behavioral")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_round(
    kind: str, order: int, focus_skills: list[str], seniority: str | None
) -> dict:
    """Build one round document, with its budget and seniority-calibrated bar."""
    min_q, max_q = _ROUND_BUDGETS.get(kind, (2, 4))
    return {
        "key": f"{order}-{kind}",
        "title": _ROUND_TITLES.get(kind, kind.replace("_", " ").title()),
        "kind": kind,
        "order": order,
        "focus_skills": focus_skills,
        "min_questions": min_q,
        "max_questions": max_q,
        "bar": round_bar(seniority, kind),
        "interview_id": None,
        "status": ROUND_LOCKED,
        "score": None,
        "attempt": 0,
    }


def normalize_rounds(
    raw: object, target_skills: list[str], seniority: str | None
) -> list[dict]:
    """Turn an LLM's proposed ladder into valid round documents.

    The model is asked for ``[{kind, focus_skills}]``. Anything unusable — unknown
    kinds, a bad shape, too few or too many rounds — falls back to the default ladder
    rather than propagating a malformed loop the learner cannot complete.

    Focus skills are constrained to ``target_skills`` (the JD's own extracted skills) so
    a hallucinated skill can never become the subject of a round.
    """
    allowed = {
        s.strip(): s.strip() for s in target_skills if isinstance(s, str) and s.strip()
    }
    allowed_lower = {k.lower(): v for k, v in allowed.items()}

    proposed: list[tuple[str, list[str]]] = []
    if isinstance(raw, list):
        seen_kinds: set[str] = set()
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            kind = str(entry.get("kind", "")).strip().lower().replace(" ", "_")
            if kind not in ROUND_KINDS or kind in seen_kinds:
                continue
            seen_kinds.add(kind)
            skills: list[str] = []
            for s in entry.get("focus_skills") or []:
                if not isinstance(s, str):
                    continue
                match = allowed_lower.get(s.strip().lower())
                if match and match not in skills:
                    skills.append(match)
            proposed.append((kind, skills))

    if not (MIN_ROUNDS <= len(proposed) <= MAX_ROUNDS):
        proposed = [(kind, []) for kind in _DEFAULT_KINDS]

    # Every round needs something to be about. A round the model left empty falls back
    # to the whole skill list rather than interviewing on nothing.
    fallback = list(allowed.values())[:6]
    rounds = []
    for i, (kind, skills) in enumerate(proposed, start=1):
        rounds.append(build_round(kind, i, skills or fallback, seniority))
    if rounds:
        rounds[0]["status"] = ROUND_AVAILABLE
    return rounds


def build_loop(
    *,
    learner_id: str,
    job: dict,
    rounds: list[dict],
    company_signals: dict,
) -> dict:
    """Assemble a complete loop document from a saved job application."""
    now = _now()
    return {
        "loop_id": str(uuid.uuid4()),
        "learner_id": learner_id,
        "job_id": job.get("id"),
        "company": job.get("company", ""),
        "role": job.get("role", ""),
        "seniority": job.get("seniority", ""),
        "target_skills": list(job.get("required_skills") or [])[:20],
        "company_signals": company_signals,
        "rounds": rounds,
        "status": LOOP_IN_PROGRESS,
        "debrief": None,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    }


def find_round(loop: dict, round_key: str) -> dict | None:
    return next(
        (r for r in loop.get("rounds") or [] if r.get("key") == round_key), None
    )


def apply_round_result(loop: dict, round_key: str, score: float) -> dict:
    """Record a graded round, unlock the next one, and recompute the loop status.

    Mutates and returns ``loop`` (the caller persists it). A **failed round still
    unlocks the next one** — this is practice, not a gatekeeper, and a learner who
    stumbles on the screen should still get to try the coding round. The loop's own
    status is what reflects whether every round cleared its bar.
    """
    rounds = loop.get("rounds") or []
    for i, rnd in enumerate(rounds):
        if rnd.get("key") != round_key:
            continue
        rnd["score"] = score
        rnd["status"] = ROUND_PASSED if score >= rnd.get("bar", 0) else ROUND_FAILED
        if i + 1 < len(rounds) and rounds[i + 1]["status"] == ROUND_LOCKED:
            rounds[i + 1]["status"] = ROUND_AVAILABLE
        break

    loop["status"] = loop_status(rounds)
    loop["updated_at"] = _now()
    if loop["status"] != LOOP_IN_PROGRESS:
        loop["completed_at"] = loop["updated_at"]
    return loop


def loop_status(rounds: list[dict]) -> str:
    """A loop is resolved once every round is; it passed only if all rounds did."""
    if not rounds or any(r.get("status") not in _RESOLVED for r in rounds):
        return LOOP_IN_PROGRESS
    return (
        LOOP_PASSED
        if all(r.get("status") == ROUND_PASSED for r in rounds)
        else LOOP_FAILED
    )


def is_resolved(loop: dict) -> bool:
    """True when every round has been graded, so a debrief can be written."""
    return loop_status(loop.get("rounds") or []) != LOOP_IN_PROGRESS


def loop_view(loop: dict) -> dict:
    """Project a loop for the client.

    Whitelisted like ``course_planner.interview_state``: the learner sees the ladder,
    their scores and the bars they are graded against, but never the raw scraped
    company text (untrusted third-party content that has no business being rendered).
    """
    return {
        "loop_id": loop.get("loop_id"),
        "job_id": loop.get("job_id"),
        "company": loop.get("company", ""),
        "role": loop.get("role", ""),
        "seniority": loop.get("seniority", ""),
        "target_skills": loop.get("target_skills") or [],
        "process_summary": (loop.get("company_signals") or {}).get(
            "process_summary", ""
        ),
        "status": loop.get("status", LOOP_IN_PROGRESS),
        "rounds": [
            {
                "key": r.get("key"),
                "title": r.get("title", ""),
                "kind": r.get("kind", ""),
                "order": r.get("order"),
                "focus_skills": r.get("focus_skills") or [],
                "bar": r.get("bar"),
                "status": r.get("status"),
                "score": r.get("score"),
                "attempt": r.get("attempt", 0),
                "interview_id": r.get("interview_id"),
                "max_questions": r.get("max_questions"),
            }
            for r in loop.get("rounds") or []
        ],
        "debrief": loop.get("debrief"),
        "created_at": loop.get("created_at"),
        "completed_at": loop.get("completed_at"),
    }
