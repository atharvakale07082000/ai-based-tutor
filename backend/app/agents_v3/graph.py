"""
LangGraph StateGraph for the v3 DeepAgent.

Topology:
  START → orchestrator → [doubt | quiz | curriculum | progress | assistant] → synthesizer → END

The orchestrator replicates v2's keyword-first routing (O(1), no LLM)
with an LLM fallback, and emits a RoutingDecision into state.

Each sub-agent node runs BaseSubAgent.run() → appends AgentReport to state.

The synthesizer merges reports and streams the final answer token by token.
"""

from __future__ import annotations

import asyncio
import json
import re

import structlog
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.agents_v3.schemas import (
    AGENT_DISPLAY_NAMES,
    AgentReport,
    DeepAgentState,
    RoutingDecision,
)
from app.agents_v3.subagents.assistant import AssistantSubAgent
from app.agents_v3.subagents.curriculum import CurriculumSubAgent
from app.agents_v3.subagents.doubt import DoubtSubAgent
from app.agents_v3.subagents.progress import ProgressSubAgent
from app.agents_v3.subagents.quiz import QuizSubAgent
from app.hf.client import get_hf_client, record_auth_failure, record_auth_success
from app.hf.models import HF_MODELS, TOKEN_BUDGETS

log = structlog.get_logger()

# Hoisted as a module-level constant so the provider KV cache hits on every
# routing call — the prefix is byte-identical across all requests.
_ROUTING_SYSTEM_PROMPT = (
    "Route the learner query to the correct agent. "
    "Agents: quiz, curriculum, progress, doubt, assistant. "
    'Reply ONLY with JSON: {"agent": "<name>", "reason": "<one sentence>"}'
)

# ---------------------------------------------------------------------------
# Keyword routing — same logic as v2 AgentRouter (no LLM call)
# ---------------------------------------------------------------------------
_KEYWORD_MAP: dict[str, set[str]] = {
    "quiz": {"quiz", "test me", "question", "assess", "examine"},
    "curriculum": {"learn", "path", "roadmap", "curriculum", "plan my", "study plan", "learning goal"},
    "progress": {"score", "elo", "my progress", "how am i doing", "update my", "progress"},
    "doubt": {"explain", "what is", "how does", "why", "confused", "understand", "clarify", "difference between"},
}


def _keyword_route(query: str) -> tuple[str, str] | None:
    """Return (agent, reason) via O(1) keyword matching, or None on a tie/miss."""
    lower = query.lower()
    hit_counts: dict[str, list[str]] = {}
    for agent_name, keywords in _KEYWORD_MAP.items():
        matched = [kw for kw in keywords if kw in lower]
        if matched:
            hit_counts[agent_name] = matched

    if not hit_counts:
        return None
    if len(hit_counts) == 1:
        agent = next(iter(hit_counts))
        return agent, f"keyword match: {hit_counts[agent][0]}"
    best = max(hit_counts, key=lambda a: len(hit_counts[a]))
    tied = [a for a, h in hit_counts.items() if len(h) == len(hit_counts[best])]
    if len(tied) == 1:
        return best, f"keyword match: {hit_counts[best][0]}"
    return None  # tie — fall through to LLM


async def _llm_route(query: str) -> tuple[str, str]:
    """Use the LLM to route a query when keyword matching is ambiguous or misses."""
    model_cfg = HF_MODELS["DOUBT_SOLVER"]
    provider = model_cfg["provider"]
    model_id = model_cfg["model_id"]
    try:
        client = get_hf_client(provider=provider)
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat_completion,
                model=model_id,
                messages=[
                    {"role": "system", "content": _ROUTING_SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                max_tokens=TOKEN_BUDGETS["routing"],
                temperature=0.0,
            ),
            timeout=5.0,
        )
        record_auth_success(provider)
        raw = response.choices[0].message.content.strip()
        cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        data = json.loads(cleaned)
        agent = str(data.get("agent", "assistant")).strip().lower()
        reason = str(data.get("reason", "llm routing"))
        valid = {"quiz", "curriculum", "progress", "doubt", "assistant"}
        if agent not in valid:
            agent, reason = "assistant", "routing parse error"
        return agent, reason
    except asyncio.TimeoutError:
        log.warning("v3.orchestrator_llm_timeout")
        return "assistant", "routing timeout — fallback to assistant"
    except Exception as e:
        err = str(e)
        if "401" in err or "403" in err:
            record_auth_failure(provider)
        log.error("v3.orchestrator_llm_error", error=err[:200])
        return "assistant", "routing error"


# ---------------------------------------------------------------------------
# LangGraph node functions
# ---------------------------------------------------------------------------


async def orchestrator_node(state: DeepAgentState) -> dict:
    """LangGraph node: resolve routing decision and update state with the chosen agent."""
    query = state["query"]
    result = _keyword_route(query) or await _llm_route(query)
    agent_key, reason = result

    decision = RoutingDecision.from_agent_key(agent_key, reason)
    log.info("v3.routing", agent=decision.agent, display_name=decision.display_name, reason=reason)

    return {
        "routing_decision": decision,
        "messages": [HumanMessage(content=query)],
        "iteration": state.get("iteration", 0) + 1,
    }


def _make_subagent_node(subagent_cls):
    """
    Factory: returns an async LangGraph node that runs the given subagent class.

    Resilience tiers:
      1. Domain subagent runs normally.
      2. If it raises or returns an empty/error result, AssistantSubAgent runs as fallback.
      3. If the fallback also fails, a warm failsafe message is returned instead of an error.
    """
    from app.agents_v3.middleware import (
        CoTMiddleware,
        GuardrailMiddleware,
        MiddlewareChain,
        ObservabilityMiddleware,
    )

    async def node(state: DeepAgentState) -> dict:
        """Run the domain subagent with 3-tier resilience: domain → assistant fallback → failsafe."""
        chain = MiddlewareChain([CoTMiddleware(), GuardrailMiddleware(), ObservabilityMiddleware()])

        # Tier 1: domain agent
        try:
            agent = subagent_cls(chain)
            report: AgentReport = await agent.run(state["query"], state["context"])
            if report.result and len(report.result.strip()) > 10 and "unavailable" not in report.result.lower():
                return {"agent_reports": [report]}
            log.warning("v3.subagent_empty_result", agent=subagent_cls.name)
        except Exception as e:
            log.error("v3.subagent_failed", agent=getattr(subagent_cls, "name", "?"), error=str(e)[:200])

        # Tier 2: assistant fallback
        try:
            fallback_chain = MiddlewareChain([CoTMiddleware(), ObservabilityMiddleware()])
            fallback = AssistantSubAgent(fallback_chain)
            fb_report: AgentReport = await fallback.run(state["query"], state["context"])
            if fb_report.result and len(fb_report.result.strip()) > 10:
                log.info("v3.subagent_fallback_used", primary=getattr(subagent_cls, "name", "?"))
                return {"agent_reports": [fb_report]}
        except Exception as e:
            log.error("v3.fallback_agent_failed", error=str(e)[:200])

        # Tier 3: warm failsafe message (never a cold "error")

        display = AGENT_DISPLAY_NAMES.get(getattr(subagent_cls, "name", "assistant"), "AI Tutor")
        failsafe = AgentReport(
            agent_name=getattr(subagent_cls, "name", "assistant"),
            display_name=display,
            task=state["query"],
            result=(
                "I'm working on your request but hit a temporary snag. "
                "Your question has been noted — please try again in a moment "
                "and I'll give you a complete answer."
            ),
            confidence=0.0,
        )
        return {"agent_reports": [failsafe]}

    node.__name__ = getattr(subagent_cls, "name", "subagent")
    return node


_FAILSAFE_MESSAGES = [
    "I'm still working through this — give it another go and I'll have a proper answer ready for you.",
    "Something got in the way of my response. Send it again and I'll be right with you.",
    "I ran into a brief snag. Try once more — I'm fully ready to help.",
    "My answer got lost in transit. Ask again and I'll come back with something solid.",
    "I needed a moment to regroup. Go ahead and resend — I'm all yours.",
]

_failsafe_index = 0


async def synthesizer_node(state: DeepAgentState) -> dict:
    """Merge all agent reports into a single final_response string."""
    global _failsafe_index
    reports: list[AgentReport] = state.get("agent_reports", [])

    if not reports:
        msg = _FAILSAFE_MESSAGES[_failsafe_index % len(_FAILSAFE_MESSAGES)]
        _failsafe_index += 1
        return {"final_response": msg}

    # Primary result from the last report
    primary = reports[-1]
    final = primary.result

    # Failsafe: if the primary result is empty or an error stub, rotate message
    if not final or len(final.strip()) < 10:
        msg = _FAILSAFE_MESSAGES[_failsafe_index % len(_FAILSAFE_MESSAGES)]
        _failsafe_index += 1
        return {"final_response": msg}

    # If multiple reports exist (future multi-agent), join with dividers
    if len(reports) > 1:
        parts = [r.result for r in reports if r.result and len(r.result.strip()) > 10]
        if parts:
            final = "\n\n---\n\n".join(parts)

    return {"final_response": final}


def _route_by_decision(state: DeepAgentState) -> str:
    """Return the agent key to branch to based on the current RoutingDecision in state."""
    decision = state.get("routing_decision")
    if decision is None:
        return "assistant"
    return decision.agent if decision.agent in {"doubt", "quiz", "curriculum", "progress"} else "assistant"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph() -> StateGraph:
    """Construct and return the compiled LangGraph StateGraph for the DeepAgent."""
    graph = StateGraph(DeepAgentState)

    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("doubt", _make_subagent_node(DoubtSubAgent))
    graph.add_node("quiz", _make_subagent_node(QuizSubAgent))
    graph.add_node("curriculum", _make_subagent_node(CurriculumSubAgent))
    graph.add_node("progress", _make_subagent_node(ProgressSubAgent))
    graph.add_node("assistant", _make_subagent_node(AssistantSubAgent))
    graph.add_node("synthesizer", synthesizer_node)

    graph.set_entry_point("orchestrator")

    graph.add_conditional_edges(
        "orchestrator",
        _route_by_decision,
        {
            "doubt": "doubt",
            "quiz": "quiz",
            "curriculum": "curriculum",
            "progress": "progress",
            "assistant": "assistant",
        },
    )

    for agent_name in ["doubt", "quiz", "curriculum", "progress", "assistant"]:
        graph.add_edge(agent_name, "synthesizer")

    graph.add_edge("synthesizer", END)

    return graph
