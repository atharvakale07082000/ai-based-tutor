"""CoTMiddleware — injects Chain-of-Thought instructions and extracts thought steps."""

from __future__ import annotations

from app.agents_v3.middleware.base import AgentMiddleware
from app.agents_v3.schemas import AgentContext, AgentReport, CoTStep

_COT_INSTRUCTION = """
=== CHAIN OF THOUGHT (REQUIRED) ===
Before every action, reason explicitly through these questions:
1. What does the learner need?
2. What context or proficiency data do I already have?
3. What tools are required and in which order?
4. What would the ideal response look like?

Include a "cot_steps" array in EVERY JSON output:
{"cot_steps":[{"step":1,"reasoning":"<why>","decision":"<what you will do>"},...],
 "thought":"<conclusion>","action":{"tool":"<name>","args":{...}}}

For the final answer use:
{"cot_steps":[...],"thought":"<conclusion>","final_answer":"<answer>","side_effects":[...]}

NEVER omit cot_steps. Minimum one entry per step.
===========================================
"""


class CoTMiddleware(AgentMiddleware):
    async def pre_process(self, ctx: AgentContext) -> AgentContext:
        ctx.system_prompt = ctx.system_prompt + _COT_INSTRUCTION
        return ctx

    async def post_process(self, ctx: AgentContext, report: AgentReport) -> AgentReport:
        # cot_chain is already populated by BaseSubAgent during the ReAct loop
        return report


def extract_cot_steps(step_result: dict, step_num: int) -> list[CoTStep]:
    """Pull cot_steps out of a raw LLM JSON response dict."""
    raw = step_result.get("cot_steps", [])
    steps: list[CoTStep] = []
    for i, entry in enumerate(raw if isinstance(raw, list) else []):
        if isinstance(entry, dict):
            steps.append(
                CoTStep(
                    step=entry.get("step", step_num * 10 + i),
                    reasoning=str(entry.get("reasoning", "")),
                    decision=str(entry.get("decision", "")),
                )
            )
    # Fallback: synthesise one CoT step from the thought field
    if not steps:
        thought = step_result.get("thought", "")
        if thought:
            action = step_result.get("action", {})
            decision = f"call {action.get('tool', 'unknown')}" if action else "provide final answer"
            steps.append(CoTStep(step=step_num, reasoning=thought, decision=decision))
    return steps
