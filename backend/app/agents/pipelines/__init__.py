"""
Deterministic sequential pipelines — the replacement for the retired plan-execute
workflow framework.

Each pipeline is a plain async function that runs its steps in order and (when an
``emit`` callback is supplied) streams the same ``step`` timeline events the old
Executor produced. Step ids/labels are unchanged, so the SSE output and the
frontend timeline are identical.
"""

from app.agents.pipelines.course_gen import run_course_gen
from app.agents.pipelines.interview_review import run_interview_review
from app.agents.pipelines.jd_analyze import run_jd_analyze
from app.agents.pipelines.quiz_gen import run_quiz_gen

__all__ = [
    "run_course_gen",
    "run_interview_review",
    "run_jd_analyze",
    "run_quiz_gen",
]
