"""
Deterministic sequential pipelines — the replacement for the retired plan-execute
workflow framework.

Each pipeline is a plain async function that runs its steps in order and (when an
``emit`` callback is supplied) streams the same ``step`` timeline events the old
Executor produced. Step ids/labels are unchanged, so the SSE output and the
frontend timeline are identical.

Every pipeline body runs inside ``steps.step_emitter``, which adds one thing to that
contract: if the NIM rate limiter makes a call stall, the learner gets a one-line
capacity note *while* it stalls instead of a frozen timeline. Headless runs (no
``emit``) are unaffected.
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
