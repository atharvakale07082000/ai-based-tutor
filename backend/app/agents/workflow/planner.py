"""
Hybrid planner.

A workflow registers a static, ordered skeleton of Tasks. ``build_plan`` returns that skeleton as
a concrete Plan; with ``adapt=True`` it may additionally run a *bounded* LLM call that only decides
which ``optional`` tasks to include and fills per-task params — it can never invent new tasks or
agents. Any LLM failure falls back to the deterministic skeleton.
"""

from __future__ import annotations

import json

import structlog

from app.agents.json_utils import extract_json
from app.agents.workflow.base import Plan, Task, WorkflowError

log = structlog.get_logger()

# workflow key -> ordered skeleton
WORKFLOW_SKELETONS: dict[str, list[Task]] = {}


def register_workflow(workflow: str, tasks: list[Task]) -> None:
    """Register a workflow's ordered task skeleton."""
    WORKFLOW_SKELETONS[workflow] = list(tasks)


async def build_plan(workflow: str, ctx, *, adapt: bool = False) -> Plan:
    """Build a concrete Plan for ``workflow`` (the TODO).

    Non-optional tasks are always included, in order. Optional tasks are included by default; when
    ``adapt`` is set and the skeleton has optional tasks, a bounded LLM pass may drop some and supply
    params (merged into ``ctx.params``). Falls back to the full skeleton on any error.
    """
    skeleton = WORKFLOW_SKELETONS.get(workflow)
    if skeleton is None:
        raise WorkflowError(f"Unknown workflow '{workflow}'")

    included_optional = {t.id for t in skeleton if t.optional}

    if adapt and any(t.optional for t in skeleton):
        try:
            included_optional, param_overrides = await _llm_adapt(workflow, ctx, skeleton)
            ctx.params.update(param_overrides)
        except Exception as e:  # noqa: BLE001 - planning must never hard-fail; skeleton is the floor
            log.warning("workflow.adapt_failed", workflow=workflow, error=str(e)[:200])

    tasks = [t for t in skeleton if (not t.optional) or (t.id in included_optional)]
    return Plan(workflow=workflow, tasks=tasks)


async def _llm_adapt(workflow: str, ctx, skeleton: list[Task]) -> tuple[set[str], dict]:
    """Bounded LLM adaptation: choose which optional task ids to include + per-task params.

    Returns ``(included_optional_ids, param_overrides)``, both constrained to the skeleton.
    """
    from app.hf.client import hf_chat_completion_with_resilience
    from app.hf.models import HF_MODELS, TOKEN_BUDGETS

    optional_ids = [t.id for t in skeleton if t.optional]
    skeleton_desc = "\n".join(f"- {t.id}: {t.label}{' (optional)' if t.optional else ''}" for t in skeleton)
    prompt = (
        f"You are planning the '{workflow}' workflow. Here is the fixed task list:\n{skeleton_desc}\n\n"
        f"Request: {json.dumps(ctx.request, default=str)[:1500]}\n\n"
        f"Decide which OPTIONAL tasks (ids: {optional_ids}) to include for THIS request. "
        "You may not add, remove, or reorder non-optional tasks.\n"
        'Reply ONLY with JSON: {"include": ["<optional id>", ...], "params": {"<task id>": {...}}}'
    )
    model_cfg = HF_MODELS["DOUBT_SOLVER"]
    raw = await hf_chat_completion_with_resilience(
        provider=model_cfg["provider"],
        model_id=model_cfg["model_id"],
        messages=[{"role": "user", "content": prompt}],
        max_tokens=TOKEN_BUDGETS.get("cot_step", 120),
        temperature=0.0,
        timeout_s=15.0,
    )
    data = extract_json(raw) or {}

    valid_optional = {t.id for t in skeleton if t.optional}
    valid_all = {t.id for t in skeleton}
    include = {i for i in data.get("include", []) if i in valid_optional}
    params = {k: v for k, v in (data.get("params") or {}).items() if k in valid_all and isinstance(v, dict)}
    return include, params
