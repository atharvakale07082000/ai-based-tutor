"""
Agent v2 Stress Test — 125 queries across all 5 agents with retry logic.

Tests the full SSE event pipeline:
  AgentRouter → specialist agent → ReAct loop → SSE stream

All LLM and DB calls are mocked so the suite runs offline and fast.
Each query is retried up to MAX_RETRIES times before being recorded as failed.
Final summary is printed after each test class.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_RETRIES = 3
QUERIES_PER_AGENT = 25

# ── Query bank (25 per agent = 125 total) ─────────────────────────────────────

QUIZ_QUERIES: list[str] = [
    "quiz me on Python basics",
    "test my knowledge of machine learning",
    "give me questions about data structures",
    "create a quiz on neural networks",
    "I want to be assessed on algorithms",
    "examine my understanding of recursion",
    "quiz me on SQL queries",
    "test me on object-oriented programming",
    "assess my knowledge of REST APIs",
    "quiz me about binary trees",
    "I want a test on sorting algorithms",
    "give me questions about Python decorators",
    "quiz me on database normalization",
    "test my knowledge of Docker",
    "I want to be quizzed on React hooks",
    "examine my understanding of async/await",
    "quiz me on pandas and numpy",
    "test me on git commands",
    "assess my knowledge of Big O notation",
    "quiz me on linear regression",
    "give me questions about hash tables",
    "test my understanding of closures",
    "quiz me on microservices architecture",
    "I want questions on Kubernetes",
    "test me on Python list comprehensions",
]

CURRICULUM_QUERIES: list[str] = [
    "create a learning path for AI",
    "I need a roadmap for web development",
    "plan my study for data science",
    "build me a curriculum for machine learning",
    "what should I learn for backend engineering",
    "give me a study plan for Python mastery",
    "I want a learning goal roadmap for DevOps",
    "plan my path to becoming a full stack developer",
    "create a curriculum for NLP",
    "what is the roadmap for cloud architecture",
    "I need a learning path for mobile development",
    "plan my study for computer vision",
    "give me a roadmap for system design",
    "create a learning plan for cybersecurity",
    "what should I learn for data engineering",
    "plan my path to learn TypeScript",
    "build a curriculum for graph algorithms",
    "create a learning roadmap for Rust",
    "plan my study for distributed systems",
    "what is the learning path for blockchain",
    "I need a curriculum for deep learning",
    "plan my learning goal for reinforcement learning",
    "give me a study plan for algorithms and data structures",
    "create a roadmap for software architecture",
    "plan my path to learning Kubernetes and Docker",
]

PROGRESS_QUERIES: list[str] = [
    "how am I doing on Python",
    "update my progress on machine learning",
    "what is my ELO score for algorithms",
    "show me my progress in data science",
    "how well am I performing in SQL",
    "update my score on neural networks",
    "what is my current progress",
    "how am I doing overall",
    "update my elo for React development",
    "show me my scores",
    "how well do I know Python",
    "update my progress tracker",
    "what topics have I mastered",
    "show my progress in web development",
    "how am I progressing with machine learning",
    "update my performance metrics",
    "what is my progress on algorithms",
    "show me how I am doing in this course",
    "update my elo score please",
    "how much progress have I made",
    "show my mastery levels",
    "update my scores for data structures",
    "what is my current elo",
    "how am I doing in the curriculum",
    "show my overall progress summary",
]

DOUBT_QUERIES: list[str] = [
    "explain what is recursion",
    "how does gradient descent work",
    "why is Python slower than C++",
    "what is the difference between list and tuple",
    "explain how neural networks learn",
    "how does backpropagation work",
    "what is a closure in Python",
    "explain the CAP theorem",
    "how does TCP/IP work",
    "what is the difference between SQL and NoSQL",
    "explain what is a decorator",
    "how does garbage collection work",
    "what is the difference between threads and processes",
    "explain what is a transformer model",
    "how does attention mechanism work",
    "what is the difference between supervised and unsupervised learning",
    "explain what is a hash table",
    "how does quicksort work",
    "what is the difference between stack and heap",
    "explain what is an API",
    "how does Docker containerization work",
    "what is the difference between REST and GraphQL",
    "explain what is Big O notation",
    "how does a binary search tree work",
    "what is the difference between mutable and immutable",
]

ASSISTANT_QUERIES: list[str] = [
    "help me get started with learning",
    "what should I focus on today",
    "I'm confused about where to begin",
    "can you give me some advice on studying",
    "I need help with my learning journey",
    "suggest something interesting to learn",
    "what are good resources for programming",
    "help me organize my study schedule",
    "I want to improve my coding skills",
    "give me some motivation to keep studying",
    "what is the best way to learn a new language",
    "I need guidance on my career path",
    "help me understand how to study effectively",
    "what topics should a beginner programmer learn",
    "I want to become a better developer",
    "can you help me with my learning plan",
    "give me tips for coding interviews",
    "I need help choosing between Python and JavaScript",
    "what is the most important skill for a software engineer",
    "help me understand the job market for developers",
    "I want to contribute to open source projects",
    "how do I stay updated with technology trends",
    "give me advice on building a portfolio",
    "I need help finding good programming projects",
    "how do I balance learning and working",
]

ALL_QUERIES: dict[str, list[str]] = {
    "quiz": QUIZ_QUERIES,
    "curriculum": CURRICULUM_QUERIES,
    "progress": PROGRESS_QUERIES,
    "doubt": DOUBT_QUERIES,
    "assistant": ASSISTANT_QUERIES,
}


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class QueryResult:
    query: str
    expected_agent: str
    passed: bool = False
    routed_to: str = ""
    event_counts: dict[str, int] = field(default_factory=dict)
    attempts: int = 0
    error: str = ""
    latency_ms: int = 0


# ── Mock ToolResult ───────────────────────────────────────────────────────────

class MockToolResult:
    def __init__(self, name: str, args: dict):
        self.name = name
        self.args = args
        self.result = {"ok": True, "data": f"mock result for {name}"}
        self.error = None
        self.latency_ms = 42


# ── Mock decide_step: 1 action step, then final_answer ───────────────────────

_step_counters: dict[str, int] = {}

async def _mock_decide_step(self, messages: list[dict]) -> dict:
    key = id(self)
    _step_counters[key] = _step_counters.get(key, 0) + 1
    count = _step_counters[key]

    if count == 1 and self.tool_names:
        tool = self.tool_names[0]
        # Provide minimal valid args per tool
        tool_arg_map: dict[str, dict] = {
            "classify_topic": {"text": "sample query"},
            "analyze_sentiment": {"text": "feeling good"},
            "score_difficulty": {"text": "explain recursion", "topic": "Python"},
            "generate_quiz": {"topic": "Python", "bloom_level": "apply", "count": 5},
            "get_embeddings": {"text": "learning Python"},
            "generate_explanation": {"question": "what is recursion?", "correct_answer": "A function calls itself"},
            "get_proficiency": {"user_id": "test-user", "topic": "Python"},
            "get_topic_graph": {"user_id": "test-user"},
            "save_quiz": {"user_id": "test-user", "topic": "Python", "bloom_level": "apply", "questions": []},
            "save_progress": {"user_id": "test-user", "topic": "Python", "old_elo": 500.0, "new_elo": 520.0},
            "get_due_topics": {"user_id": "test-user"},
            "calculate_elo": {"current_elo": 500.0, "score": 0.8},
            "check_guardrail": {"text": "sample query"},
        }
        args = tool_arg_map.get(tool, {"text": "query"})
        return {
            "thought": f"I should use {tool} to answer this query.",
            "action": {"tool": tool, "args": args},
        }

    return {
        "thought": "I have enough information to answer.",
        "final_answer": f"Here is the answer from {self.name}.",
        "side_effects": [],
    }


async def _mock_stream_final_answer(self, final_answer: str, messages: list[dict]):
    tokens = ["Here", " is", " a", " helpful", " response", " from", f" {self.name}", "."]
    for token in tokens:
        yield token


# ── SSE stream parser ─────────────────────────────────────────────────────────

async def _parse_sse_stream(response) -> list[dict]:
    """Parse all SSE events from an httpx streaming response."""
    events: list[dict] = []
    async for line in response.aiter_lines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if payload == "[DONE]":
            break
        try:
            event = json.loads(payload)
            events.append(event)
        except json.JSONDecodeError:
            pass
    return events


def _validate_events(events: list[dict]) -> tuple[bool, str]:
    """
    Validate the event sequence for correctness.
    Returns (passed, error_message).
    """
    if not events:
        return False, "No events received"

    types = [e.get("type") for e in events]

    # Must start with routing
    if types[0] != "routing":
        return False, f"First event must be 'routing', got {types[0]!r}"

    # Must end with done or error
    if types[-1] not in ("done", "error"):
        return False, f"Last event must be 'done' or 'error', got {types[-1]!r}"

    if types[-1] == "error":
        err_msg = events[-1].get("message", "unknown error")
        return False, f"Agent returned error event: {err_msg}"

    # Must have at least some token events
    token_count = types.count("token")
    if token_count == 0:
        return False, "No token events received — final answer was not streamed"

    # Routing event must have agent field
    routing_event = events[0]
    if not routing_event.get("agent"):
        return False, "Routing event missing 'agent' field"

    return True, ""


# ── Core streaming function ───────────────────────────────────────────────────

async def stream_v2_query(
    client: AsyncClient,
    query: str,
) -> tuple[list[dict], int]:
    """Hit POST /api/v2/chat and return (events, latency_ms)."""
    start = time.monotonic()
    events: list[dict] = []

    async with client.stream(
        "POST",
        "/api/v2/chat",
        json={"message": query, "history": [], "context": {}},
        timeout=60.0,
    ) as response:
        if response.status_code != 200:
            body = await response.aread()
            raise AssertionError(f"HTTP {response.status_code}: {body[:200]}")
        events = await _parse_sse_stream(response)

    latency_ms = int((time.monotonic() - start) * 1000)
    return events, latency_ms


async def run_with_retry(
    client: AsyncClient,
    query: str,
    expected_agent: str,
    max_retries: int = MAX_RETRIES,
) -> QueryResult:
    """Run a query with retry logic. Returns a QueryResult."""
    result = QueryResult(query=query, expected_agent=expected_agent)

    for attempt in range(1, max_retries + 1):
        result.attempts = attempt
        # Reset step counter for this attempt
        _step_counters.clear()
        try:
            events, latency_ms = await stream_v2_query(client, query)
            result.latency_ms = latency_ms

            # Count event types
            result.event_counts = {}
            for e in events:
                t = e.get("type", "unknown")
                result.event_counts[t] = result.event_counts.get(t, 0) + 1

            # Extract routing
            if events and events[0].get("type") == "routing":
                result.routed_to = events[0].get("agent", "")

            # Validate
            passed, error = _validate_events(events)
            if passed:
                result.passed = True
                result.error = ""
                return result
            else:
                result.error = error
                if attempt < max_retries:
                    await asyncio.sleep(0.05 * attempt)

        except Exception as exc:
            result.error = str(exc)[:200]
            if attempt < max_retries:
                await asyncio.sleep(0.1 * attempt)

    return result


# ── Summary printer ───────────────────────────────────────────────────────────

def _print_summary(results: list[QueryResult], agent_name: str) -> None:
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]
    avg_latency = sum(r.latency_ms for r in results) / max(len(results), 1)
    avg_attempts = sum(r.attempts for r in results) / max(len(results), 1)

    print(f"\n{'='*60}")
    print(f"Agent: {agent_name.upper()} | Total: {len(results)} | Passed: {len(passed)} | Failed: {len(failed)}")
    print(f"Avg latency: {avg_latency:.0f}ms | Avg attempts: {avg_attempts:.2f}")

    if failed:
        print("\nFailed queries:")
        for r in failed:
            print(f"  [{r.attempts} attempts] {r.query[:60]!r}")
            print(f"    Error: {r.error}")
            print(f"    Routed to: {r.routed_to!r}")
    print(f"{'='*60}\n")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def v2_client():
    """
    Async httpx client wired to the FastAPI ASGI app with:
    - auth dependency overridden (always returns "test-user-id")
    - tool_registry.call mocked to return MockToolResult
    - BaseAgent.decide_step mocked to cycle thought→final_answer
    - BaseAgent.stream_final_answer mocked to yield tokens
    - col_learners mocked to return an empty learner doc
    """
    from app.main import app
    from app.auth.jwt import get_current_user_id
    from app.agents_v2.base import BaseAgent
    from app.tools import tool_registry

    # Override auth
    app.dependency_overrides[get_current_user_id] = lambda: "test-user-id"

    mock_col = MagicMock()
    mock_col.find_one.return_value = {
        "id": "test-user-id",
        "user_id": "test-user-id",
        "topic_proficiency_map": {"Python": 500.0, "Machine Learning": 350.0},
    }

    async def _mock_tool_call(name: str, args: dict) -> MockToolResult:
        return MockToolResult(name=name, args=args)

    with (
        patch("app.routers.v2.chat.col_learners", return_value=mock_col),
        patch.object(tool_registry, "call", side_effect=_mock_tool_call),
        patch.object(BaseAgent, "decide_step", _mock_decide_step),
        patch.object(BaseAgent, "stream_final_answer", _mock_stream_final_answer),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client

    app.dependency_overrides.clear()


# ── Test classes ──────────────────────────────────────────────────────────────

class TestQuizAgentStress:
    @pytest.mark.asyncio
    async def test_quiz_agent_25_queries(self, v2_client):
        results: list[QueryResult] = []
        for query in QUIZ_QUERIES:
            r = await run_with_retry(v2_client, query, "quiz")
            results.append(r)

        _print_summary(results, "quiz")

        failed = [r for r in results if not r.passed]
        assert not failed, (
            f"{len(failed)}/{len(results)} quiz queries failed:\n"
            + "\n".join(f"  {r.query!r}: {r.error}" for r in failed)
        )


class TestCurriculumAgentStress:
    @pytest.mark.asyncio
    async def test_curriculum_agent_25_queries(self, v2_client):
        results: list[QueryResult] = []
        for query in CURRICULUM_QUERIES:
            r = await run_with_retry(v2_client, query, "curriculum")
            results.append(r)

        _print_summary(results, "curriculum")

        failed = [r for r in results if not r.passed]
        assert not failed, (
            f"{len(failed)}/{len(results)} curriculum queries failed:\n"
            + "\n".join(f"  {r.query!r}: {r.error}" for r in failed)
        )


class TestProgressAgentStress:
    @pytest.mark.asyncio
    async def test_progress_agent_25_queries(self, v2_client):
        results: list[QueryResult] = []
        for query in PROGRESS_QUERIES:
            r = await run_with_retry(v2_client, query, "progress")
            results.append(r)

        _print_summary(results, "progress")

        failed = [r for r in results if not r.passed]
        assert not failed, (
            f"{len(failed)}/{len(results)} progress queries failed:\n"
            + "\n".join(f"  {r.query!r}: {r.error}" for r in failed)
        )


class TestDoubtAgentStress:
    @pytest.mark.asyncio
    async def test_doubt_agent_25_queries(self, v2_client):
        results: list[QueryResult] = []

        # DoubtAgent overrides stream_final_answer to call stream_doubt_response.
        # Patch that too so it yields tokens without a real LLM.
        async def _mock_doubt_stream(*args, **kwargs):
            async def _gen():
                tokens = ["Great", " question", ".", " Recursion", " means", " a", " function", " calls", " itself", "."]
                for t in tokens:
                    yield t
            return _gen()

        with patch("app.agents_v2.doubt_agent.stream_doubt_response", side_effect=_mock_doubt_stream):
            for query in DOUBT_QUERIES:
                r = await run_with_retry(v2_client, query, "doubt")
                results.append(r)

        _print_summary(results, "doubt")

        failed = [r for r in results if not r.passed]
        assert not failed, (
            f"{len(failed)}/{len(results)} doubt queries failed:\n"
            + "\n".join(f"  {r.query!r}: {r.error}" for r in failed)
        )


class TestAssistantAgentStress:
    @pytest.mark.asyncio
    async def test_assistant_agent_25_queries(self, v2_client):
        results: list[QueryResult] = []
        for query in ASSISTANT_QUERIES:
            r = await run_with_retry(v2_client, query, "assistant")
            results.append(r)

        _print_summary(results, "assistant")

        failed = [r for r in results if not r.passed]
        assert not failed, (
            f"{len(failed)}/{len(results)} assistant queries failed:\n"
            + "\n".join(f"  {r.query!r}: {r.error}" for r in failed)
        )


class TestFullSuite125Queries:
    """
    Runs all 125 queries in one combined test to produce an aggregate report.
    Individual agent tests must all pass before this is meaningful.
    """

    @pytest.mark.asyncio
    async def test_all_125_queries_no_failures(self, v2_client):
        all_results: list[QueryResult] = []

        async def _mock_doubt_stream(*args, **kwargs):
            async def _gen():
                for t in ["Full", " suite", " doubt", " answer", "."]:
                    yield t
            return _gen()

        with patch("app.agents_v2.doubt_agent.stream_doubt_response", side_effect=_mock_doubt_stream):
            for agent_name, queries in ALL_QUERIES.items():
                for query in queries:
                    r = await run_with_retry(v2_client, query, agent_name)
                    all_results.append(r)

        # ── Aggregate summary ──────────────────────────────────────────────────
        total = len(all_results)
        passed = [r for r in all_results if r.passed]
        failed = [r for r in all_results if not r.passed]
        avg_latency = sum(r.latency_ms for r in all_results) / max(total, 1)
        retried = [r for r in all_results if r.attempts > 1]

        # Per-agent breakdown
        by_agent: dict[str, dict] = {}
        for r in all_results:
            ag = r.expected_agent
            if ag not in by_agent:
                by_agent[ag] = {"pass": 0, "fail": 0}
            if r.passed:
                by_agent[ag]["pass"] += 1
            else:
                by_agent[ag]["fail"] += 1

        print(f"\n{'#'*60}")
        print(f"FULL SUITE: {total} queries | Passed: {len(passed)} | Failed: {len(failed)}")
        print(f"Avg latency: {avg_latency:.0f}ms | Queries retried: {len(retried)}")
        print("\nPer-agent breakdown:")
        for ag, counts in sorted(by_agent.items()):
            status = "✓" if counts["fail"] == 0 else "✗"
            print(f"  {status} {ag:12s}: {counts['pass']:2d} passed, {counts['fail']:2d} failed")

        if failed:
            print("\nFailed queries:")
            for r in failed:
                print(f"  [{r.expected_agent}] [{r.attempts} attempts] {r.query[:55]!r}")
                print(f"    Error: {r.error}")
        print(f"{'#'*60}\n")

        assert not failed, (
            f"{len(failed)}/{total} queries failed across all agents.\n"
            + "\n".join(
                f"  [{r.expected_agent}] {r.query!r}: {r.error}"
                for r in failed
            )
        )


# ── Routing accuracy analysis (bonus, non-blocking) ───────────────────────────

class TestRoutingAccuracy:
    """
    Checks that keyword-dominant queries route to the expected agent.
    Not all queries have a guaranteed route (some are intentionally ambiguous),
    so this test uses a lenient threshold.
    """

    @pytest.mark.asyncio
    async def test_routing_accuracy_above_threshold(self, v2_client):
        # Only test queries with strong keyword signals
        confident_map: list[tuple[str, str]] = [
            ("quiz me on Python basics", "quiz"),
            ("test my knowledge of machine learning", "quiz"),
            ("create a learning path for AI", "curriculum"),
            ("I need a roadmap for web development", "curriculum"),
            ("how am I doing on Python", "progress"),
            ("what is my ELO score for algorithms", "progress"),
            ("explain what is recursion", "doubt"),
            ("how does gradient descent work", "doubt"),
        ]

        correct = 0
        total = len(confident_map)

        async def _mock_doubt_stream(*args, **kwargs):
            async def _gen():
                yield "answer"
            return _gen()

        with patch("app.agents_v2.doubt_agent.stream_doubt_response", side_effect=_mock_doubt_stream):
            for query, expected in confident_map:
                _step_counters.clear()
                events, _ = await stream_v2_query(v2_client, query)
                if events and events[0].get("type") == "routing":
                    routed_to = events[0].get("agent", "")
                    if routed_to == expected:
                        correct += 1
                    else:
                        print(f"  Routing mismatch: {query!r}")
                        print(f"    expected={expected!r}, got={routed_to!r}")

        accuracy = correct / total
        print(f"\nRouting accuracy: {correct}/{total} = {accuracy:.0%}")
        assert accuracy >= 0.75, f"Routing accuracy {accuracy:.0%} below 75% threshold"


class TestSSEEventStructure:
    """
    Deep structural validation of SSE events for one representative query per agent.
    """

    @pytest.mark.asyncio
    async def test_quiz_sse_structure(self, v2_client):
        _step_counters.clear()
        events, _ = await stream_v2_query(v2_client, "quiz me on Python")
        _assert_full_event_structure(events, expected_tool_step=True)

    @pytest.mark.asyncio
    async def test_curriculum_sse_structure(self, v2_client):
        _step_counters.clear()
        events, _ = await stream_v2_query(v2_client, "create a learning path for me")
        _assert_full_event_structure(events, expected_tool_step=True)

    @pytest.mark.asyncio
    async def test_progress_sse_structure(self, v2_client):
        _step_counters.clear()
        events, _ = await stream_v2_query(v2_client, "how am I doing on my progress")
        _assert_full_event_structure(events, expected_tool_step=True)

    @pytest.mark.asyncio
    async def test_doubt_sse_structure(self, v2_client):
        _step_counters.clear()

        async def _mock_doubt_stream(*args, **kwargs):
            async def _gen():
                yield "Explanation here."
            return _gen()

        with patch("app.agents_v2.doubt_agent.stream_doubt_response", side_effect=_mock_doubt_stream):
            events, _ = await stream_v2_query(v2_client, "explain what is a neural network")

        _assert_full_event_structure(events, expected_tool_step=True)

    @pytest.mark.asyncio
    async def test_assistant_sse_structure(self, v2_client):
        _step_counters.clear()
        events, _ = await stream_v2_query(v2_client, "help me get started with learning")
        _assert_full_event_structure(events, expected_tool_step=True)


def _assert_full_event_structure(events: list[dict], expected_tool_step: bool) -> None:
    """Deep-validate SSE event sequence structure."""
    assert events, "No events received"

    types = [e.get("type") for e in events]

    # routing first
    assert types[0] == "routing", f"First event must be 'routing', got {types[0]!r}"
    routing = events[0]
    assert routing.get("agent"), "routing event missing 'agent'"
    assert routing.get("reason"), "routing event missing 'reason'"

    # done last
    assert types[-1] == "done", f"Last event must be 'done', got {types[-1]!r}"
    done = events[-1]
    assert "steps" in done, "done event missing 'steps'"
    assert "total_ms" in done, "done event missing 'total_ms'"

    # thought event present
    assert "thought" in types, f"No thought event in stream: {types}"
    thought = next(e for e in events if e.get("type") == "thought")
    assert thought.get("content"), "thought event missing 'content'"
    assert "step" in thought, "thought event missing 'step'"

    if expected_tool_step:
        # tool_call event present
        assert "tool_call" in types, f"No tool_call event in stream: {types}"
        tc = next(e for e in events if e.get("type") == "tool_call")
        assert tc.get("name"), "tool_call event missing 'name'"
        assert "args" in tc, "tool_call event missing 'args'"

        # tool_result event present
        assert "tool_result" in types, f"No tool_result event in stream: {types}"
        tr = next(e for e in events if e.get("type") == "tool_result")
        assert tr.get("name"), "tool_result event missing 'name'"
        assert "latency_ms" in tr, "tool_result event missing 'latency_ms'"

    # token events present
    assert "token" in types, f"No token events in stream: {types}"
    tokens = [e.get("content", "") for e in events if e.get("type") == "token"]
    full_response = "".join(tokens)
    assert len(full_response) > 0, "Token stream produced empty response"
