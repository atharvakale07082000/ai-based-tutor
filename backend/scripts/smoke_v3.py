#!/usr/bin/env python3
"""
smoke_v3.py — Throttled end-to-end smoke test for the v3 DeepAgent.

Tests the agent pipeline directly (no HTTP server needed) at ≤ 30 RPM
to stay well within the 40 RPM limit on NVIDIA NIM + HF Together.

Usage:
  uv run python scripts/smoke_v3.py                  # full suite
  uv run python scripts/smoke_v3.py --step doubt      # doubt only
  uv run python scripts/smoke_v3.py --step routing    # routing only
  uv run python scripts/smoke_v3.py --step guardrail  # guardrail only
  uv run python scripts/smoke_v3.py --step schema     # schema/import only (no LLM)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

INTER_CALL_DELAY = 2.0  # seconds between LLM calls (= 30 RPM max)

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m·\033[0m"

failures: list[str] = []


def ok(msg: str) -> None:
    print(f"  {PASS} {msg}")


def fail(msg: str) -> None:
    print(f"  {FAIL} {msg}")
    failures.append(msg)


def info(msg: str) -> None:
    print(f"  {INFO} {msg}")


# ---------------------------------------------------------------------------
# Schema-only test (no LLM calls)
# ---------------------------------------------------------------------------


def test_schema() -> None:
    print("\n[schema] Importing and validating Pydantic models...")
    from app.agents_v3.schemas import (
        AGENT_DISPLAY_NAMES,
        AgentReport,
        CoTStep,
        RoutingDecision,
    )

    assert set(AGENT_DISPLAY_NAMES.keys()) == {"doubt", "quiz", "curriculum", "progress"}, (
        "AGENT_DISPLAY_NAMES missing keys"
    )
    ok("AGENT_DISPLAY_NAMES keys correct")

    rd = RoutingDecision.from_agent_key("doubt", "test", 0.9)
    assert rd.display_name == "Learning Assistant", f"Wrong display_name: {rd.display_name}"
    assert rd.agent == "doubt"
    ok(f"RoutingDecision.from_agent_key → display_name={rd.display_name!r}")

    report = AgentReport(
        agent_name="doubt",
        display_name="Learning Assistant",
        task="test",
        cot_chain=[CoTStep(step=1, reasoning="r", decision="d")],
        result="test answer",
    )
    assert len(report.cot_chain) == 1
    ok("AgentReport with CoTStep created successfully")

    from app.agents_v3.middleware import CoTMiddleware, GuardrailMiddleware, MiddlewareChain, ObservabilityMiddleware

    chain = MiddlewareChain([CoTMiddleware(), GuardrailMiddleware(), ObservabilityMiddleware()])
    assert len(chain._middlewares) == 3
    ok("MiddlewareChain with 3 middlewares")

    from app.agents_v3.graph import build_graph

    g = build_graph().compile()
    node_names = set(g.get_graph().nodes.keys())
    expected = {
        "__start__",
        "orchestrator",
        "doubt",
        "quiz",
        "curriculum",
        "progress",
        "assistant",
        "synthesizer",
        "__end__",
    }
    assert node_names == expected, f"Graph nodes mismatch: {node_names}"
    ok(f"LangGraph compiled — nodes: {sorted(node_names - {'__start__', '__end__'})}")


# ---------------------------------------------------------------------------
# Keyword routing test (no LLM call)
# ---------------------------------------------------------------------------


def test_keyword_routing() -> None:
    print("\n[routing] Testing keyword-first routing (no LLM)...")
    from app.agents_v3.graph import _keyword_route

    cases = [
        ("explain recursion to me", "doubt"),
        ("generate a quiz on Python", "quiz"),
        ("build me a learning path", "curriculum"),
        ("update my progress score", "progress"),
    ]
    for query, expected_agent in cases:
        result = _keyword_route(query)
        if result is None:
            fail(f"Keyword routing returned None for: {query!r}")
            continue
        agent, reason = result
        if agent == expected_agent:
            ok(f"{query!r} → {agent!r} ({reason})")
        else:
            fail(f"{query!r} → expected {expected_agent!r}, got {agent!r}")


# ---------------------------------------------------------------------------
# CoT extraction test (no LLM call)
# ---------------------------------------------------------------------------


def test_cot_extraction() -> None:
    print("\n[cot] Testing CoT step extraction...")
    from app.agents_v3.middleware.cot import extract_cot_steps

    step_with_cot = {
        "cot_steps": [
            {"step": 1, "reasoning": "learner needs help with recursion", "decision": "call get_proficiency"},
        ],
        "thought": "Check proficiency first",
        "action": {"tool": "get_proficiency", "args": {"topic": "recursion"}},
    }
    steps = extract_cot_steps(step_with_cot, 1)
    assert len(steps) == 1 and steps[0].reasoning == "learner needs help with recursion"
    ok(f"Extracted {len(steps)} CoT step(s) with explicit cot_steps")

    step_fallback = {
        "thought": "I should explain recursion",
        "action": {"tool": "generate_explanation", "args": {}},
    }
    steps2 = extract_cot_steps(step_fallback, 2)
    assert len(steps2) == 1 and "explain" in steps2[0].reasoning.lower()
    ok(f"Fallback CoT extraction from 'thought' field: {steps2[0].reasoning!r}")


# ---------------------------------------------------------------------------
# Live LLM tests (throttled)
# ---------------------------------------------------------------------------


async def test_doubt_agent_live() -> None:
    print("\n[doubt] Live doubt subagent test (1 LLM call)...")
    from app.agents_v3.middleware import CoTMiddleware, MiddlewareChain, ObservabilityMiddleware
    from app.agents_v3.subagents.doubt import DoubtSubAgent

    chain = MiddlewareChain([CoTMiddleware(), ObservabilityMiddleware()])
    agent = DoubtSubAgent(chain)

    t0 = time.monotonic()
    report = await agent.run(
        "What is recursion in programming?",
        {
            "learner_id": "smoke-test-user",
            "current_topic": "Python",
            "proficiency": {},
            "history": [],
        },
    )
    elapsed = int((time.monotonic() - t0) * 1000)

    if report.result and len(report.result) > 20:
        ok(f"Got answer ({len(report.result)} chars) in {elapsed}ms")
    else:
        fail(f"Answer too short or empty: {report.result!r}")

    if report.display_name == "Learning Assistant":
        ok(f"display_name={report.display_name!r}")
    else:
        fail(f"display_name wrong: {report.display_name!r}")

    info(f"CoT steps: {len(report.cot_chain)}, tool calls: {len(report.tool_calls)}")
    for cot in report.cot_chain[:2]:
        info(f"  CoT step {cot.step}: {cot.reasoning[:60]}")


async def test_routing_live() -> None:
    print("\n[routing] Live LLM routing test (1 LLM call)...")
    from app.agents_v3.graph import _llm_route

    agent, reason = await _llm_route("I don't understand what a for loop is")
    valid = {"doubt", "quiz", "curriculum", "progress", "assistant"}
    if agent in valid:
        ok(f"LLM routed to {agent!r}: {reason}")
    else:
        fail(f"LLM returned invalid agent: {agent!r}")

    from app.agents_v3.schemas import AGENT_DISPLAY_NAMES, RoutingDecision

    rd = RoutingDecision.from_agent_key(agent, reason)
    expected_display = AGENT_DISPLAY_NAMES.get(agent, "AI Tutor")
    if rd.display_name == expected_display:
        ok(f"RoutingDecision display_name={rd.display_name!r}")
    else:
        fail(f"display_name mismatch: {rd.display_name!r} vs {expected_display!r}")


async def test_guardrail_live() -> None:
    print("\n[guardrail] Guardrail middleware test (no LLM call — CPU only)...")
    from app.agents_v3.middleware import CoTMiddleware, GuardrailMiddleware, MiddlewareChain, ObservabilityMiddleware
    from app.agents_v3.schemas import AgentContext

    chain = MiddlewareChain([CoTMiddleware(), GuardrailMiddleware(), ObservabilityMiddleware()])
    ctx = AgentContext(
        learner_id="smoke-test-user",
        query="Explain quantum entanglement",
        context={},
        system_prompt="You are a tutor.",
    )
    ctx = await chain.apply_pre(ctx)

    if "CHAIN OF THOUGHT" in ctx.system_prompt:
        ok("CoT instructions injected into system prompt")
    else:
        fail("CoT instructions NOT found in system prompt")

    info(f"Query blocked by guardrail: {ctx.blocked}")
    if not ctx.blocked:
        ok("Non-toxic query passed guardrail")


async def test_deep_agent_graph() -> None:
    print("\n[graph] Full DeepAgent graph test (1 LLM call, doubt path)...")
    from app.agents_v3.deep_agent import create_deep_agent

    agent = create_deep_agent()
    events: list[dict] = []

    t0 = time.monotonic()
    async for event in agent.astream(
        "What is a variable in Python?",
        {
            "learner_id": "smoke-test-user",
            "current_topic": "Python basics",
            "proficiency": {},
            "history": [],
        },
    ):
        events.append(event)
        info(
            f"  event: type={event.get('type')!r} "
            + (
                f"agent={event.get('agent')!r} display={event.get('display_name')!r}"
                if event.get("type") == "routing"
                else ""
            )
        )

    elapsed = int((time.monotonic() - t0) * 1000)
    event_types = [e.get("type") for e in events]

    if "routing" in event_types:
        routing_evt = next(e for e in events if e.get("type") == "routing")
        if routing_evt.get("display_name"):
            ok(f"routing event has display_name={routing_evt['display_name']!r}")
        else:
            fail("routing event missing display_name")
    else:
        fail("No routing event emitted")

    if "token" in event_types:
        token_events = [e for e in events if e.get("type") == "token"]
        full_text = "".join(e.get("content", "") for e in token_events)
        ok(f"token stream: {len(token_events)} chunks, {len(full_text)} chars total")
    else:
        fail("No token events emitted")

    if "done" in event_types:
        done_evt = next(e for e in events if e.get("type") == "done")
        ok(f"done event: steps={done_evt.get('steps')}, total_ms={done_evt.get('total_ms')}")
    else:
        fail("No done event emitted")

    cot_events = [e for e in events if e.get("type") == "cot_step"]
    info(f"CoT events emitted: {len(cot_events)}")

    info(f"Total elapsed: {elapsed}ms, events: {len(events)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def async_main(step: str) -> None:
    print(f"\n{'=' * 55}")
    print(f"  AI Tutor v3 DeepAgent Smoke Test  |  step={step!r}")
    print("  Rate limit: ≤30 RPM (2s between LLM calls)")
    print(f"{'=' * 55}")

    if step in ("schema", "all"):
        test_schema()

    if step in ("routing", "all"):
        test_keyword_routing()
        test_cot_extraction()

    if step in ("guardrail", "all"):
        await test_guardrail_live()

    if step in ("routing", "all"):
        await test_routing_live()
        await asyncio.sleep(INTER_CALL_DELAY)

    if step in ("doubt", "all"):
        await test_doubt_agent_live()
        await asyncio.sleep(INTER_CALL_DELAY)

    if step in ("graph", "all"):
        await test_deep_agent_graph()

    print(f"\n{'=' * 55}")
    if failures:
        print(f"  {FAIL} {len(failures)} failure(s):")
        for f in failures:
            print(f"    - {f}")
        print(f"{'=' * 55}\n")
        sys.exit(1)
    else:
        print(f"  {PASS} All checks passed!")
        print(f"{'=' * 55}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="v3 DeepAgent smoke test")
    parser.add_argument(
        "--step",
        choices=["all", "schema", "routing", "guardrail", "doubt", "graph"],
        default="all",
        help="Which test group to run (default: all)",
    )
    args = parser.parse_args()
    asyncio.run(async_main(args.step))


if __name__ == "__main__":
    main()
