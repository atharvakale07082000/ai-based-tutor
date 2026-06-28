"""
Core primitives for the plan-then-execute workflow framework: Task, Plan, WorkflowContext,
the TaskAgent protocol, and the sequential Executor.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

import structlog

from app.agents.steps import StepTimeline
from app.agents.workflow.registry import TASK_AGENTS

log = structlog.get_logger()

# An emitter forwards a step/event dict to the SSE stream (see app.agents.steps.sse_step_stream).
Emit = Callable[[dict], Awaitable[None]]


class WorkflowError(Exception):
    """Raised when a non-optional task fails or references an unknown agent."""


@dataclass
class WorkflowContext:
    """Shared state threaded through a workflow's sequential tasks.

    ``request`` is the original input; each task writes its output into ``results[task.id]`` so
    later tasks can read it — this is the hand-off that makes the chain sequential and stateful.
    ``params`` holds planner-resolved values (e.g. an LLM-chosen difficulty).
    """

    workflow: str
    request: dict = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)

    def result(self, task_id: str, default: Any = None) -> Any:
        return self.results.get(task_id, default)


@dataclass(frozen=True)
class Task:
    """One step in a workflow's TODO.

    - ``agent_key``  : which registered task agent runs this step.
    - ``optional``   : if True, a failure/skip doesn't abort the workflow.
    - ``when``       : optional predicate over the context; False → skip the task.
    - ``params``     : static params for this task (planner may override per-run via ctx.params).
    """

    id: str
    label: str
    agent_key: str
    optional: bool = False
    when: Optional[Callable[["WorkflowContext"], bool]] = None
    params: dict = field(default_factory=dict)


@dataclass
class Plan:
    """An ordered list of tasks for a workflow — the concrete TODO produced by the planner."""

    workflow: str
    tasks: list[Task]


class TaskAgent(Protocol):
    """One unit of work: read the context, return a result merged into ``ctx.results[task.id]``."""

    async def __call__(self, ctx: WorkflowContext, task: Task) -> Any:  # pragma: no cover - protocol
        ...


async def _noop_emit(_ev: dict) -> None:
    return None


class Executor:
    """Runs a Plan's tasks strictly one-after-another — never in parallel."""

    def __init__(self, registry: Optional[dict[str, TaskAgent]] = None) -> None:
        # Defaults to the global registry; injectable for tests.
        self._registry = registry if registry is not None else TASK_AGENTS

    async def run(self, plan: Plan, ctx: WorkflowContext, emit: Emit | None = None) -> WorkflowContext:
        """Execute ``plan`` sequentially, threading ``ctx`` and emitting timeline events.

        Each task: optionally skip via ``when`` → emit ``start`` → run the agent → store the result →
        emit ``done``. A non-optional failure raises WorkflowError (the caller surfaces a graceful
        message); an optional failure is logged and skipped.
        """
        emit = emit or _noop_emit
        tl = StepTimeline(plan.workflow)

        for task in plan.tasks:
            if task.when is not None and not task.when(ctx):
                log.info("workflow.task_skipped", workflow=plan.workflow, task=task.id)
                continue

            agent = self._registry.get(task.agent_key)
            if agent is None:
                log.error("workflow.unknown_agent", workflow=plan.workflow, agent_key=task.agent_key)
                await emit(tl.error(task.id, task.label))
                if task.optional:
                    continue
                raise WorkflowError(f"No task agent registered for '{task.agent_key}'")

            await emit(tl.start(task.id, task.label))
            t0 = time.perf_counter()
            try:
                result = await agent(ctx, task)
            except WorkflowError:
                raise
            except Exception as e:  # noqa: BLE001 - one task's failure shouldn't crash the loop opaquely
                log.error("workflow.task_failed", workflow=plan.workflow, task=task.id, error=str(e)[:200])
                await emit(tl.error(task.id, task.label))
                if task.optional:
                    continue
                raise WorkflowError(f"Task '{task.id}' failed: {e}") from e

            ctx.results[task.id] = result
            log.info(
                "workflow.task_done",
                workflow=plan.workflow,
                task=task.id,
                latency_ms=round((time.perf_counter() - t0) * 1000),
            )
            await emit(tl.done(task.id, task.label))

        return ctx


async def run_workflow(
    workflow: str,
    request: dict,
    *,
    emit: Emit | None = None,
    adapt: bool = False,
    registry: Optional[dict[str, TaskAgent]] = None,
) -> WorkflowContext:
    """Convenience entry point: build the plan for ``workflow`` then execute it sequentially.

    ``adapt=True`` lets the hybrid planner LLM-tune which optional tasks run (with a safe fallback
    to the static skeleton).
    """
    from app.agents.workflow.planner import build_plan

    ctx = WorkflowContext(workflow=workflow, request=dict(request or {}))
    plan = await build_plan(workflow, ctx, adapt=adapt)
    return await Executor(registry).run(plan, ctx, emit=emit)
