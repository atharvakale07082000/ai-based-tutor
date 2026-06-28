import structlog
from fastapi import APIRouter, Depends, Query

from app.auth.jwt import require_superuser
from app.evals.evaluator import run_eval
from app.evals.mongo import aggregate_summary, dashboard_stats, query_evals
from app.evals.schemas import EvalRecord, EvalType

router = APIRouter()
log = structlog.get_logger()


@router.get("/dashboard")
async def evals_dashboard(user_id: str = Depends(require_superuser)):
    """Superuser-only: one-shot rich stats for the evals dashboard.

    Returns overall pass-rate/avg-score, per-metric and per-agent breakdowns, recent records, and a
    14-day score trend. The frontend refetches this on an interval.
    """
    return await dashboard_stats()


@router.post("/run", response_model=EvalRecord)
async def trigger_eval(
    eval_type: EvalType,
    agent: str,
    input: dict,
    output: dict,
    learner_id: str = "",
    trace_id: str = "",
    user_id: str = Depends(require_superuser),
):
    """
    Manually trigger an evaluation for a specific agent invocation.
    Stores the result in MongoDB and returns the EvalRecord.
    """
    log.info("eval_trigger", eval_type=eval_type, agent=agent, user_id=user_id)
    record = await run_eval(
        eval_type,
        agent,
        input=input,
        output=output,
        learner_id=learner_id,
        trace_id=trace_id,
        store=True,
    )
    return record


@router.get("/results")
async def get_eval_results(
    eval_type: EvalType | None = Query(None),
    agent: str | None = Query(None),
    passed: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    user_id: str = Depends(require_superuser),
):
    """Query stored eval records with optional filters."""
    results = await query_evals(
        eval_type=eval_type,
        agent=agent,
        passed=passed,
        limit=limit,
    )
    return {"results": results, "count": len(results)}


@router.get("/summary")
async def get_eval_summary(
    eval_type: EvalType | None = Query(None),
    agent: str | None = Query(None),
    user_id: str = Depends(require_superuser),
):
    """Aggregate pass-rate and average score by (eval_type, agent)."""
    summaries = await aggregate_summary(eval_type=eval_type, agent=agent)
    return {"summaries": summaries}


@router.post("/batch/quiz")
async def run_quiz_batch_eval(
    quiz_sessions: list[dict],
    user_id: str = Depends(require_superuser),
):
    """
    Run quiz_format eval over a batch of quiz session outputs.
    Useful for offline quality checks after a session.
    """
    results = []
    for session in quiz_sessions:
        record = await run_eval(
            "quiz_format",
            "quiz_agent",
            input=session.get("input", {}),
            output=session.get("output", {}),
            learner_id=session.get("learner_id", ""),
            session_id=session.get("session_id", ""),
            store=True,
        )
        results.append({"session_id": session.get("session_id"), "score": record.score, "passed": record.passed})
    return {"results": results}
