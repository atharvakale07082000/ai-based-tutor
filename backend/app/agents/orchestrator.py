"""
Multi-agent orchestrator — supervisor pattern.

Architecture:
                    ┌─────────────┐
              ┌────▶│ curriculum  │────┐
              │     └─────────────┘    │
              │     ┌─────────────┐    │
              │────▶│  progress   │────┤
              │     └─────────────┘    ▼
           ┌──────┐              ┌──────────┐
  start ──▶│      │              │          │──▶ END
           │ SUP  │◀─────────────│ (reports)│
           │      │              │          │
  task ───▶│      │──▶ quiz  ───▶│  END     │
           └──────┘──▶ doubt ──▶ END
                    (human-in-the-loop, re-invoked by API layer)

The LLM supervisor reads structured reports from each agent and decides
what to call next — replacing the old hardcoded rule-based planner.
"""
import structlog
from langgraph.graph import StateGraph, END

from app.agents.state import AgentState
from app.agents.supervisor import supervisor_node
from app.agents.curriculum_agent import curriculum_agent_node
from app.agents.quiz_agent import quiz_agent_node
from app.agents.progress_agent import progress_agent_node
from app.agents.doubt_agent import doubt_agent_node

log = structlog.get_logger()


def _route_supervisor(state: AgentState) -> str:
    """Read supervisor's decision and map to graph node."""
    decision = state.get("supervisor_decision", "FINISH")
    if state.get("session_complete"):
        return "FINISH"
    if decision in {"curriculum", "quiz", "progress", "doubt"}:
        return decision
    return "FINISH"


def build_orchestrator() -> StateGraph:
    workflow = StateGraph(AgentState)

    # ── Nodes ─────────────────────────────────────────────────────────────────
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("curriculum", curriculum_agent_node)
    workflow.add_node("quiz", quiz_agent_node)
    workflow.add_node("progress", progress_agent_node)
    workflow.add_node("doubt", doubt_agent_node)

    # ── Entry ─────────────────────────────────────────────────────────────────
    workflow.set_entry_point("supervisor")

    # ── Supervisor hub: LLM decides which agent runs next ────────────────────
    workflow.add_conditional_edges(
        "supervisor",
        _route_supervisor,
        {
            "curriculum": "curriculum",
            "quiz": "quiz",
            "progress": "progress",
            "doubt": "doubt",
            "FINISH": END,
        },
    )

    # ── Agents that loop back: curriculum and progress report to supervisor ───
    # Supervisor reads their report and decides whether to loop or finish.
    workflow.add_edge("curriculum", "supervisor")
    workflow.add_edge("progress", "supervisor")

    # ── Agents that pause for human input: quiz and doubt exit the graph ─────
    # The API layer re-invokes the graph for the next cycle after human responds.
    workflow.add_edge("quiz", END)
    workflow.add_edge("doubt", END)

    return workflow.compile()


# Singleton — imported by all routers
orchestrator = build_orchestrator()
