"""Interview pass thresholds — pure, dependency-free.

Single source of truth for "what score clears the bar", in the same spirit as
``agents/progress.py::MASTERY_ELO``. Every interview score is 0-10, so every bar is
too. Never write a bare ``6.0`` anywhere else — import from here.

A module interview keeps the platform default. A job-loop round is graded against the
seniority named in the job description (``skill_gap.parse_jd`` already extracts it),
because "good enough" for an intern posting and for a staff posting are not the same
answer to the same question.
"""

from __future__ import annotations

# The platform default: what a module interview has always passed at.
DEFAULT_BAR: float = 6.0

# Seniority → bar. Keys are matched as substrings of the JD's free-text seniority
# string (lower-cased). When several match, the highest bar wins, so a compound title
# like "senior staff engineer" resolves to staff (8.0) rather than senior (7.5).
_SENIORITY_BARS: dict[str, float] = {
    "intern": 5.0,
    "junior": 5.5,
    "entry": 5.5,
    "associate": 5.5,
    "graduate": 5.5,
    "mid": 6.5,
    "intermediate": 6.5,
    "senior": 7.5,
    "lead": 7.5,
    "staff": 8.0,
    "principal": 8.0,
    "director": 8.0,
}

# Per-round adjustment applied on top of the seniority bar. A recruiter screen is
# easier to clear than a system-design round at the same seniority; the bar should say
# so rather than pretending every round is equally hard.
ROUND_ADJUSTMENTS: dict[str, float] = {
    "screen": -0.5,
    "coding": 0.0,
    "system_design": +0.5,
    "behavioral": 0.0,
}

ROUND_KINDS: tuple[str, ...] = tuple(ROUND_ADJUSTMENTS)

# Bars are clamped so no adjustment can push a round outside a sane range.
_MIN_BAR: float = 4.0
_MAX_BAR: float = 9.0


def seniority_bar(seniority: str | None) -> float:
    """Map a JD's free-text seniority to a 0-10 pass threshold.

    Unrecognised or empty input falls back to ``DEFAULT_BAR`` — an unknown seniority
    should grade like a normal interview, never like a staff one.
    """
    text = (seniority or "").strip().lower()
    if not text:
        return DEFAULT_BAR
    matches = [bar for key, bar in _SENIORITY_BARS.items() if key in text]
    return max(matches) if matches else DEFAULT_BAR


def round_bar(seniority: str | None, round_kind: str) -> float:
    """The pass threshold for one round of a job loop, clamped to a sane range."""
    base = seniority_bar(seniority)
    adjusted = base + ROUND_ADJUSTMENTS.get(round_kind, 0.0)
    return round(max(_MIN_BAR, min(_MAX_BAR, adjusted)), 1)
