"""Workflow definitions — importing this package registers each workflow's skeleton + task agents."""

from app.agents.workflow.workflows import (  # noqa: F401 - registration side effects
    course_gen,
    interview_review,
    job_analysis,
    quiz_gen,
)

__all__ = ["course_gen", "interview_review", "job_analysis", "quiz_gen"]
