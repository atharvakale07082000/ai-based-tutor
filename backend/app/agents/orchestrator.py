from langgraph.graph import StateGraph, END
import structlog

from app.agents.state import AgentState
from app.agents.curriculum_agent import curriculum_agent_node
from app.agents.quiz_agent import quiz_agent_node
from app.agents.progress_agent import progress_agent_node
from app.agents.doubt_agent import doubt_agent_node
from app.agents.planner_agent import planner_agent_node

log = structlog.get_logger()


def route_initial_task(state: AgentState) -> str:
    """Route the very first node based on what the caller requested."""
    task = state.get("task_type", "doubt")
    log.info("orchestrator_route", task=task, learner_id=state.get("learner_id"))
    return task


def route_after_planner(state: AgentState) -> str:
    """After the planner runs, follow its decision."""
    return state.get("next_action", "end")


def router_node(state: AgentState) -> dict:
    return {}


def build_orchestrator() -> StateGraph:
    workflow = StateGraph(AgentState)

    workflow.add_node("router", router_node)
    workflow.add_node("curriculum", curriculum_agent_node)
    workflow.add_node("quiz", quiz_agent_node)
    workflow.add_node("progress", progress_agent_node)
    workflow.add_node("doubt", doubt_agent_node)
    workflow.add_node("planner", planner_agent_node)

    workflow.set_entry_point("router")

    # Initial dispatch — caller sets task_type
    # "start" skips directly to planner for fully autonomous sessions
    workflow.add_conditional_edges(
        "router",
        route_initial_task,
        {
            "curriculum": "curriculum",
            "quiz": "quiz",
            "progress": "progress",
            "doubt": "doubt",
            "start": "planner",
        },
    )

    # After curriculum and progress, always hand control to the planner
    workflow.add_edge("curriculum", "planner")
    workflow.add_edge("progress", "planner")

    # Planner decides what comes next
    workflow.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "curriculum": "curriculum",
            "quiz": "quiz",
            "end": END,
        },
    )

    # Quiz and doubt always pause here — they await human input before the next cycle
    workflow.add_edge("quiz", END)
    workflow.add_edge("doubt", END)

    return workflow.compile()


# Singleton — imported by routers
orchestrator = build_orchestrator()
