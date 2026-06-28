"""
Plan-then-execute agent workflow framework.

A workflow declares an ordered skeleton of Tasks (the TODO). The Planner turns that into a
concrete Plan (optionally LLM-adapted within bounds), and the Executor runs the tasks STRICTLY
sequentially — one agent at a time, each feeding the next via a shared WorkflowContext — while
emitting StepTimeline events so the TODO streams live to the UI.

Public surface:
    from app.agents.workflow import Task, Plan, WorkflowContext, Executor, build_plan, run_workflow
"""

# Import workflow definitions for their registration side effects (skeletons + task agents).
from app.agents.workflow import workflows  # noqa: E402,F401
from app.agents.workflow.base import (
    Executor,
    Plan,
    Task,
    TaskAgent,
    WorkflowContext,
    WorkflowError,
    run_workflow,
)
from app.agents.workflow.planner import WORKFLOW_SKELETONS, build_plan, register_workflow
from app.agents.workflow.registry import TASK_AGENTS, register

__all__ = [
    "Task",
    "Plan",
    "WorkflowContext",
    "TaskAgent",
    "Executor",
    "WorkflowError",
    "run_workflow",
    "build_plan",
    "register_workflow",
    "WORKFLOW_SKELETONS",
    "TASK_AGENTS",
    "register",
]
