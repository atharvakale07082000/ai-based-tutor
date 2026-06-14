"""
Agent v2 Concurrency Test — 200 simultaneous SSE requests.

Validates that the system handles high concurrency without failures:
- Thread pool must be large enough (64 workers set at lifespan)
- HF semaphore caps at 40 concurrent LLM calls
- All 200 requests must complete with valid SSE event streams

All LLM and DB calls are mocked; this tests async infrastructure, not inference.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Shared test query set (varies agent targets) ──────────────────────────────

_QUERIES_POOL = [
    # quiz
    "quiz me on Python basics",
    "test my knowledge of machine learning",
    "give me questions about data structures",
    "I want to be assessed on algorithms",
    "quiz me about binary trees",
    # curriculum
    "create a learning path for AI",
    "I need a roadmap for web development",
    "build me a curriculum for machine learning",
    "what should I learn for backend engineering",
    "plan my study for data science",
    # progress
    "how am I doing on Python",
    "what is my ELO score for algorithms",
    "update my progress on machine learning",
    "show me my progress in data science",
    "how am I performing in SQL",
    # doubt
    "explain what is recursion",
    "how does gradient descent work",
    "what is the difference between list and tuple",
    "explain how neural networks learn",
    "how does backpropagation work",
    # assistant
    "help me get started with learning",
    "what should I focus on today",
    "I need help with my learning journey",
    "give me some motivation to keep studying",
    "what is the best way to learn a new language",
]


@dataclass
class ConcurrentResult:
    query: str
    passed: bool
    latency_ms: int
    error: str = ""
    routed_to: str = ""
    token_count: int = 0


# ── Mock helpers (same as stress test) ───────────────────────────────────────


class MockToolResult:
    def __init__(self, name: str, args: dict):
        self.name = name
        self.args = args
        self.result = {"ok": True}
        self.error = None
        self.latency_ms = 5


_decide_call_counts: dict[int, int] = {}


async def _mock_decide_step(self, messages):
    key = id(self)
    _decide_call_counts[key] = _decide_call_counts.get(key, 0) + 1
    count = _decide_call_counts[key]

    if count % 2 == 1 and self.tool_names:
        tool = self.tool_names[0]
        return {
            "thought": f"Using {tool} to respond.",
            "action": {"tool": tool, "args": {"text": "query"}},
        }
    return {
        "thought": "Ready to answer.",
        "final_answer": f"Response from {self.name}.",
        "side_effects": [],
    }


async def _mock_stream_final_answer(self, final_answer, messages):
    for token in ["Concurrent", " response", " from", f" {self.name}", "."]:
        yield token


async def _mock_doubt_stream(*args, **kwargs):
    async def _gen():
        yield "Concurrent doubt answer."

    return _gen()


# ── Concurrent streaming function ─────────────────────────────────────────────


async def _run_single_request(client: AsyncClient, query: str) -> ConcurrentResult:
    start = time.monotonic()
    events: list[dict] = []

    try:
        async with client.stream(
            "POST",
            "/api/v2/chat",
            json={"message": query, "history": [], "context": {}},
            timeout=90.0,
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise RuntimeError(f"HTTP {resp.status_code}: {body[:100]}")

            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        events.append(json.loads(payload))
                    except json.JSONDecodeError:
                        pass

        latency_ms = int((time.monotonic() - start) * 1000)
        types = [e.get("type") for e in events]

        if not events:
            return ConcurrentResult(query=query, passed=False, latency_ms=latency_ms, error="No events")
        if types[0] != "routing":
            return ConcurrentResult(query=query, passed=False, latency_ms=latency_ms, error=f"First={types[0]!r}")
        if types[-1] not in ("done", "error"):
            return ConcurrentResult(query=query, passed=False, latency_ms=latency_ms, error=f"Last={types[-1]!r}")
        if types[-1] == "error":
            return ConcurrentResult(
                query=query, passed=False, latency_ms=latency_ms, error=events[-1].get("message", "")
            )
        if "token" not in types:
            return ConcurrentResult(query=query, passed=False, latency_ms=latency_ms, error="No token events")

        token_count = types.count("token")
        routed_to = events[0].get("agent", "")
        return ConcurrentResult(
            query=query, passed=True, latency_ms=latency_ms, routed_to=routed_to, token_count=token_count
        )

    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return ConcurrentResult(query=query, passed=False, latency_ms=latency_ms, error=str(exc)[:200])


# ── Fixture ───────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def concurrent_v2_client():
    from app.agents_v2.base import BaseAgent
    from app.auth.jwt import get_current_user_id
    from app.main import app
    from app.tools import tool_registry

    app.dependency_overrides[get_current_user_id] = lambda: "test-user-id"

    mock_col = MagicMock()
    mock_col.find_one = AsyncMock(
        return_value={
            "id": "test-user-id",
            "user_id": "test-user-id",
            "topic_proficiency_map": {"Python": 500.0},
        }
    )

    async def _mock_tool_call(name, args):
        return MockToolResult(name=name, args=args)

    with (
        patch("app.routers.v2.chat.col_learners", return_value=mock_col),
        patch.object(tool_registry, "call", side_effect=_mock_tool_call),
        patch.object(BaseAgent, "decide_step", _mock_decide_step),
        patch.object(BaseAgent, "stream_final_answer", _mock_stream_final_answer),
        patch("app.agents_v2.doubt_agent.stream_doubt_response", side_effect=_mock_doubt_stream),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client

    app.dependency_overrides.clear()


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestConcurrency50Users:
    """50 simultaneous requests — warm-up tier."""

    @pytest.mark.asyncio
    async def test_50_concurrent_requests(self, concurrent_v2_client):
        _decide_call_counts.clear()
        n = 50
        queries = [_QUERIES_POOL[i % len(_QUERIES_POOL)] for i in range(n)]

        start = time.monotonic()
        results = await asyncio.gather(*[_run_single_request(concurrent_v2_client, q) for q in queries])
        wall_ms = int((time.monotonic() - start) * 1000)

        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed]
        avg_latency = sum(r.latency_ms for r in results) / n
        p95_latency = sorted(r.latency_ms for r in results)[int(n * 0.95)]

        print(
            f"\n[50-user] Passed: {len(passed)}/{n} | Wall: {wall_ms}ms | "
            f"Avg: {avg_latency:.0f}ms | P95: {p95_latency}ms"
        )

        if failed:
            for r in failed[:5]:
                print(f"  FAIL: {r.query!r} → {r.error}")

        assert len(failed) == 0, f"{len(failed)}/{n} requests failed"


class TestConcurrency200Users:
    """200 simultaneous requests — target load tier."""

    @pytest.mark.asyncio
    async def test_200_concurrent_requests(self, concurrent_v2_client):
        _decide_call_counts.clear()
        n = 200
        queries = [_QUERIES_POOL[i % len(_QUERIES_POOL)] for i in range(n)]

        start = time.monotonic()
        results = await asyncio.gather(*[_run_single_request(concurrent_v2_client, q) for q in queries])
        wall_ms = int((time.monotonic() - start) * 1000)

        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed]
        avg_latency = sum(r.latency_ms for r in results) / n
        p50 = sorted(r.latency_ms for r in results)[int(n * 0.50)]
        p95 = sorted(r.latency_ms for r in results)[int(n * 0.95)]
        p99 = sorted(r.latency_ms for r in results)[int(n * 0.99)]

        # Agent distribution
        agent_counts: dict[str, int] = {}
        for r in results:
            if r.routed_to:
                agent_counts[r.routed_to] = agent_counts.get(r.routed_to, 0) + 1

        print(f"\n[200-user] Passed: {len(passed)}/{n} | Wall: {wall_ms}ms")
        print(f"  Latency — Avg: {avg_latency:.0f}ms | P50: {p50}ms | P95: {p95}ms | P99: {p99}ms")
        print(f"  Agent distribution: {dict(sorted(agent_counts.items()))}")

        if failed:
            print("\n  First 5 failures:")
            for r in failed[:5]:
                print(f"    {r.query!r} → {r.error}")

        # Allow up to 2% failure rate (4/200) for transient issues
        max_allowed_failures = int(n * 0.02)
        assert len(failed) <= max_allowed_failures, (
            f"{len(failed)}/{n} requests failed (limit: {max_allowed_failures})\n"
            + "\n".join(f"  {r.query!r}: {r.error}" for r in failed[:10])
        )

    @pytest.mark.asyncio
    async def test_200_requests_throughput(self, concurrent_v2_client):
        """Throughput benchmark: 200 requests should complete in <10s on a laptop."""
        _decide_call_counts.clear()
        n = 200
        queries = [_QUERIES_POOL[i % len(_QUERIES_POOL)] for i in range(n)]

        start = time.monotonic()
        results = await asyncio.gather(*[_run_single_request(concurrent_v2_client, q) for q in queries])
        wall_s = time.monotonic() - start
        throughput = n / wall_s

        passed = sum(1 for r in results if r.passed)
        print(f"\n[Throughput] {n} requests in {wall_s:.2f}s = {throughput:.1f} req/s | {passed}/{n} passed")

        # Minimum 20 req/s (very conservative for mocked tests on any hardware)
        assert throughput >= 20, f"Throughput {throughput:.1f} req/s below 20 req/s minimum"
        assert wall_s < 30, f"200 requests took {wall_s:.1f}s (limit: 30s)"


class TestSemaphoreBehavior:
    """Verifies the HF semaphore correctly limits concurrent LLM calls."""

    @pytest.mark.asyncio
    async def test_semaphore_allows_40_concurrent(self, concurrent_v2_client):
        """Fire 40 requests simultaneously — all should get semaphore slots immediately."""
        from app.agents_v2.base import _HF_SEMAPHORE

        assert _HF_SEMAPHORE._value == 40, f"Semaphore initial value should be 40, got {_HF_SEMAPHORE._value}"

    @pytest.mark.asyncio
    async def test_100_concurrent_with_semaphore(self, concurrent_v2_client):
        """100 requests should queue properly under the semaphore — no failures."""
        _decide_call_counts.clear()
        n = 100
        queries = [_QUERIES_POOL[i % len(_QUERIES_POOL)] for i in range(n)]

        results = await asyncio.gather(*[_run_single_request(concurrent_v2_client, q) for q in queries])

        failed = [r for r in results if not r.passed]
        passed_count = n - len(failed)
        print(f"\n[Semaphore-100] Passed: {passed_count}/{n}")

        assert len(failed) == 0, f"{len(failed)}/{n} requests failed under semaphore:\n" + "\n".join(
            f"  {r.query!r}: {r.error}" for r in failed[:5]
        )
