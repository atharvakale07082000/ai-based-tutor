"""Tests for the plan-then-execute workflow framework (base + planner)."""

import pytest
from app.agents.workflow.base import Executor, Plan, Task, WorkflowContext, WorkflowError
from app.agents.workflow.planner import build_plan, register_workflow


def _collect_emitter():
    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    return events, emit


@pytest.mark.asyncio
async def test_executor_runs_sequentially_and_threads_context():
    order: list[str] = []

    async def first(ctx, task):
        order.append(task.id)
        return {"value": 1}

    async def second(ctx, task):
        order.append(task.id)
        # reads the prior task's result — proves sequential hand-off
        return {"value": ctx.result("a")["value"] + 1}

    registry = {"first": first, "second": second}
    plan = Plan(
        workflow="t",
        tasks=[Task("a", "First", "first"), Task("b", "Second", "second")],
    )
    ctx = WorkflowContext(workflow="t")
    events, emit = _collect_emitter()

    out = await Executor(registry).run(plan, ctx, emit=emit)

    assert order == ["a", "b"]  # strictly in order
    assert out.results["b"]["value"] == 2  # b read a's result
    # one start + one done per task, in order
    assert [(e["id"], e["status"]) for e in events] == [
        ("a", "active"),
        ("a", "done"),
        ("b", "active"),
        ("b", "done"),
    ]


@pytest.mark.asyncio
async def test_executor_skips_task_when_predicate_false():
    ran: list[str] = []

    async def agent(ctx, task):
        ran.append(task.id)
        return {}

    registry = {"x": agent}
    plan = Plan(
        workflow="t",
        tasks=[
            Task("skip", "Skip", "x", when=lambda ctx: False),
            Task("run", "Run", "x"),
        ],
    )
    events, emit = _collect_emitter()
    await Executor(registry).run(plan, WorkflowContext(workflow="t"), emit=emit)

    assert ran == ["run"]  # skipped task never ran
    assert all(e["id"] != "skip" for e in events)  # and emitted nothing


@pytest.mark.asyncio
async def test_executor_optional_failure_continues_required_failure_raises():
    async def boom(ctx, task):
        raise RuntimeError("kaboom")

    async def ok(ctx, task):
        return {"ok": True}

    registry = {"boom": boom, "ok": ok}

    # optional failure → continue
    plan = Plan("t", [Task("opt", "Opt", "boom", optional=True), Task("ok", "Ok", "ok")])
    ctx = await Executor(registry).run(plan, WorkflowContext(workflow="t"))
    assert ctx.results.get("ok") == {"ok": True}
    assert "opt" not in ctx.results

    # required failure → WorkflowError
    plan2 = Plan("t", [Task("req", "Req", "boom")])
    with pytest.raises(WorkflowError):
        await Executor(registry).run(plan2, WorkflowContext(workflow="t"))


@pytest.mark.asyncio
async def test_executor_unknown_agent_raises():
    plan = Plan("t", [Task("a", "A", "does-not-exist")])
    with pytest.raises(WorkflowError):
        await Executor({}).run(plan, WorkflowContext(workflow="t"))


@pytest.mark.asyncio
async def test_build_plan_returns_skeleton_in_order():
    register_workflow(
        "wf_order",
        [Task("a", "A", "x"), Task("b", "B", "y", optional=True), Task("c", "C", "z")],
    )
    ctx = WorkflowContext(workflow="wf_order")
    plan = await build_plan("wf_order", ctx, adapt=False)
    assert [t.id for t in plan.tasks] == ["a", "b", "c"]  # optional included by default


@pytest.mark.asyncio
async def test_build_plan_unknown_workflow_raises():
    with pytest.raises(WorkflowError):
        await build_plan("nope", WorkflowContext(workflow="nope"))


@pytest.mark.asyncio
async def test_build_plan_adapt_falls_back_to_skeleton_on_llm_failure(monkeypatch):
    register_workflow("wf_adapt", [Task("a", "A", "x"), Task("opt", "Opt", "y", optional=True)])

    async def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr("app.agents.workflow.planner._llm_adapt", boom)
    plan = await build_plan("wf_adapt", WorkflowContext(workflow="wf_adapt"), adapt=True)
    # fallback keeps the full skeleton (optional included)
    assert [t.id for t in plan.tasks] == ["a", "opt"]


@pytest.mark.asyncio
async def test_build_plan_adapt_drops_optional_and_sets_params(monkeypatch):
    register_workflow("wf_adapt2", [Task("a", "A", "x"), Task("opt", "Opt", "y", optional=True)])

    async def adapt(workflow, ctx, skeleton):
        return set(), {"a": {"depth": "deep"}}  # include no optional, set a param

    monkeypatch.setattr("app.agents.workflow.planner._llm_adapt", adapt)
    ctx = WorkflowContext(workflow="wf_adapt2")
    plan = await build_plan("wf_adapt2", ctx, adapt=True)
    assert [t.id for t in plan.tasks] == ["a"]  # optional dropped
    assert ctx.params == {"a": {"depth": "deep"}}
