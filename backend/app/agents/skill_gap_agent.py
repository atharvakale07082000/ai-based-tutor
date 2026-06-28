"""
Skill-gap agent for the Job Tracker.

Two responsibilities, kept separate so the scoring logic is pure and unit-testable:
  - `parse_jd`     : LLM extraction of {company, role, seniority, required_skills} from a JD.
  - `analyze_gap`  : pure function comparing required skills to the learner's proficiency map,
                     producing a readiness score, per-skill gaps, and quiz/course recommendations.

Both feed the streaming `/jobs/analyze/stream` endpoint, which surfaces progress via the shared
StepTimeline backbone.
"""

from __future__ import annotations

import structlog

from app.agents.json_utils import extract_json
from app.hf.client import hf_chat_completion_with_resilience
from app.hf.models import HF_MODELS, TOKEN_BUDGETS

log = structlog.get_logger()

# ELO thresholds (proficiency map is 0–1000; mastery ≥ 700, matching the rest of the platform).
_HAVE_ELO = 700.0
_PARTIAL_ELO = 500.0

# Score weights per gap status, averaged into the 0–100 readiness score.
_STATUS_WEIGHT = {"have": 1.0, "partial": 0.5, "missing": 0.0}


async def parse_jd(jd_text: str) -> dict:
    """Extract {company, role, seniority, required_skills} from a job description via the LLM."""
    model_cfg = HF_MODELS["DOUBT_SOLVER"]
    prompt = (
        "You are an expert technical recruiter. Extract structured data from this job description.\n\n"
        f'Job description:\n"""\n{jd_text[:6000]}\n"""\n\n'
        "Return ONLY a JSON object (no markdown, no prose) with this exact shape:\n"
        '{"company": "<name or empty>", "role": "<title>", '
        '"seniority": "<junior|mid|senior|staff|lead or empty>", '
        '"required_skills": ["skill1", "skill2"]}\n\n'
        "Rules:\n"
        "- required_skills: 5–15 concrete technical skills, tools, or topics "
        '(e.g. "Python", "System Design", "PyTorch", "SQL", "Kubernetes"). No soft skills.\n'
        "- Return ONLY the JSON."
    )
    raw = await hf_chat_completion_with_resilience(
        provider=model_cfg["provider"],
        model_id=model_cfg["model_id"],
        messages=[{"role": "user", "content": prompt}],
        max_tokens=TOKEN_BUDGETS.get("course_plan", 600),
        temperature=0.1,
        timeout_s=30.0,
    )
    data = extract_json(raw) or {}
    skills = data.get("required_skills") or []
    # Normalize: strings only, de-duped (case-insensitive), capped.
    seen: set[str] = set()
    clean_skills: list[str] = []
    for s in skills:
        if not isinstance(s, str):
            continue
        key = s.strip().lower()
        if key and key not in seen:
            seen.add(key)
            clean_skills.append(s.strip())
    return {
        "company": str(data.get("company", "") or "").strip()[:200],
        "role": str(data.get("role", "") or "").strip()[:200],
        "seniority": str(data.get("seniority", "") or "").strip()[:80],
        "required_skills": clean_skills[:20],
    }


def _match_elo(skill: str, proficiency_map: dict[str, float]) -> float | None:
    """Best-effort match a required skill to a proficiency-map topic; return its ELO or None.

    Matches case-insensitively in either direction (skill ⊆ topic or topic ⊆ skill), preferring
    the topic with the highest ELO so a strong related skill counts.
    """
    s = skill.strip().lower()
    if not s:
        return None
    best: float | None = None
    for topic, elo in proficiency_map.items():
        t = str(topic).strip().lower()
        if not t:
            continue
        if s == t or s in t or t in s:
            if best is None or elo > best:
                best = float(elo)
    return best


def analyze_gap(required_skills: list[str], proficiency_map: dict[str, float]) -> dict:
    """Compare required skills to proficiency, returning readiness %, gaps, and recommendations.

    Pure function (no I/O) — unit-tested directly.
    """
    gaps: list[dict] = []
    for skill in required_skills:
        elo = _match_elo(skill, proficiency_map or {})
        if elo is not None and elo >= _HAVE_ELO:
            status = "have"
        elif elo is not None and elo >= _PARTIAL_ELO:
            status = "partial"
        else:
            status = "missing"
        gaps.append({"skill": skill, "have_elo": elo, "status": status})

    if gaps:
        readiness = round(sum(_STATUS_WEIGHT[g["status"]] for g in gaps) / len(gaps) * 100, 1)
    else:
        readiness = 0.0

    # Recommend a quiz to firm up partial skills, a course to learn missing ones.
    recommendations: list[dict] = []
    for g in gaps:
        if g["status"] == "partial":
            recommendations.append(
                {"type": "quiz", "skill": g["skill"], "label": f"Quiz: sharpen {g['skill']}", "url": "/quiz"}
            )
        elif g["status"] == "missing":
            recommendations.append(
                {"type": "course", "skill": g["skill"], "label": f"Build a path for {g['skill']}", "url": "/courses"}
            )

    return {
        "readiness_score": readiness,
        "skill_gaps": gaps,
        "recommendations": recommendations[:8],
    }
