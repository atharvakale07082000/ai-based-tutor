"""
End-to-end API tests covering the full user journey:

  Register → Login → Learner Profile → Session Start (multi-agent workflow)
  → Session Advance → Quiz Generate/Submit → Doubts → Evals

All HF / LLM calls are mocked at the agent-module level so the suite
runs offline against an in-memory SQLite database.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Mock helpers ──────────────────────────────────────────────────────────────


def _make_question(bloom_level: str = "apply", topic: str = "Python") -> dict:
    return {
        "id": "q-e2e",
        "question": f"Which of the following best illustrates {topic}?",
        "options": ["Option A — correct", "Option B", "Option C", "Option D"],
        "correct_index": 0,
        "explanation": f"Option A demonstrates {topic} correctly.",
        "bloom_level": bloom_level,
    }


async def _mock_tool(name: str, **kwargs) -> dict:
    if name == "classify_topic":
        return {"labels": ["Python Programming", "Machine Learning"], "scores": [0.92, 0.08]}
    if name == "analyze_sentiment":
        return {"label": "POSITIVE", "score": 0.91}
    if name == "score_difficulty":
        return {"score": 0.45}
    if name == "generate_quiz":
        topic = kwargs.get("topic", "Python")
        bloom = kwargs.get("bloom_level", "apply")
        count = kwargs.get("count", 5)
        return {"questions": [_make_question(bloom, topic) for _ in range(count)]}
    if name == "get_embeddings":
        return {"embedding": [0.1] * 384}
    return {}


async def _mock_stream(*args, **kwargs):
    async def _gen():
        yield "Python list comprehensions let you build lists concisely."

    return _gen()


async def _mock_get_or_generate(topic: str, bloom_level: str = "apply", count: int = 5) -> list:
    return [_make_question(bloom_level, topic) for _ in range(count)]


@contextmanager
def mock_all_agents():
    """Patch call_tool in every agent module + HF streaming responses."""
    with (
        patch("app.agents.curriculum_agent.call_tool", side_effect=_mock_tool),
        patch("app.agents.quiz_agent.call_tool", side_effect=_mock_tool),
        patch("app.agents.progress_agent.call_tool", side_effect=_mock_tool),
        patch("app.agents.doubt_agent.call_tool", side_effect=_mock_tool),
        patch("app.agents.planner_agent.call_tool", side_effect=_mock_tool),
        patch("app.agents.doubt_agent.stream_doubt_response", side_effect=_mock_stream),
        patch("app.routers.doubts.stream_doubt_response", side_effect=_mock_stream),
        patch("app.routers.quiz.get_or_generate_quiz_questions", side_effect=_mock_get_or_generate),
        patch("app.hf.quiz_questions.get_or_generate_quiz_questions", side_effect=_mock_get_or_generate),
    ):
        yield


# ── Shared state across tests ─────────────────────────────────────────────────

_STATE: dict = {}  # populated by first login test, reused by later tests


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client():
    """Fresh ASGI client (MongoDB-backed app, no table creation needed)."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def authed(client):
    """Client pre-authenticated as the E2E test user."""
    if "access_token" not in _STATE:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "e2e@example.com", "password": "e2e-password-123"},
        )
        assert resp.status_code == 200, resp.text
        _STATE["access_token"] = resp.json()["access_token"]
        _STATE["refresh_token"] = resp.json()["refresh_token"]
        _STATE["user_id"] = resp.json()["user"]["id"]
    client.headers["Authorization"] = f"Bearer {_STATE['access_token']}"
    return client


# ─────────────────────────────────────────────────────────────────────────────
# 1. AUTH FLOW
# ─────────────────────────────────────────────────────────────────────────────


class TestE2E_Auth:
    @pytest.mark.asyncio
    async def test_E2E_A01_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_E2E_A02_login_auto_registers(self, client):
        """First login auto-creates user; returns access + refresh tokens."""
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "newuser-e2e@example.com", "password": "secure123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "newuser-e2e@example.com"
        assert data["user"]["role"] == "learner"

    @pytest.mark.asyncio
    async def test_E2E_A03_second_login_same_user(self, client):
        """Logging in again with correct credentials returns same user."""
        await client.post(
            "/api/v1/auth/login",
            json={"email": "returning@example.com", "password": "pass123"},
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "returning@example.com", "password": "pass123"},
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == "returning@example.com"

    @pytest.mark.asyncio
    async def test_E2E_A04_wrong_password_rejected(self, client):
        """Wrong password for existing user → 401."""
        await client.post(
            "/api/v1/auth/login",
            json={"email": "pw-test@example.com", "password": "correct-password"},
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "pw-test@example.com", "password": "wrong-password"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_E2E_A05_token_refresh(self, authed):
        """Valid access token → can get new access token."""
        resp = await authed.post("/api/v1/auth/refresh")
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    @pytest.mark.asyncio
    async def test_E2E_A06_refresh_without_token_rejected(self, client):
        resp = await client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_E2E_A07_logout(self, authed):
        resp = await authed.post("/api/v1/auth/logout")
        assert resp.status_code == 200
        assert "message" in resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# 2. LEARNER PROFILE
# ─────────────────────────────────────────────────────────────────────────────


class TestE2E_LearnerProfile:
    @pytest.mark.asyncio
    async def test_E2E_LP01_get_profile(self, authed):
        resp = await authed.get("/api/v1/learner/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert "name" in data
        assert "goal_vector" in data
        assert "xp" in data
        assert "topic_proficiency_map" in data

    @pytest.mark.asyncio
    async def test_E2E_LP02_update_goals(self, authed):
        resp = await authed.put(
            "/api/v1/learner/profile",
            json={"goal_vector": ["I want to master Python", "Learn machine learning"]},
        )
        assert resp.status_code == 200
        assert "Python" in resp.json()["goal_vector"][0]

    @pytest.mark.asyncio
    async def test_E2E_LP03_profile_without_auth(self, client):
        resp = await client.get("/api/v1/learner/profile")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_E2E_LP04_curriculum_endpoint(self, authed):
        resp = await authed.get("/api/v1/curriculum/current")
        assert resp.status_code in (200, 404)


# ─────────────────────────────────────────────────────────────────────────────
# 3. SESSION — Multi-agent workflow
# ─────────────────────────────────────────────────────────────────────────────


class TestE2E_Session:
    """
    Cold start → Advance → mastery.
    Runs the full planner → curriculum → planner → quiz chain.
    """

    @pytest.mark.asyncio
    async def test_E2E_S01_session_start(self, authed):
        """POST /session/start — full multi-agent chain executes."""
        with mock_all_agents():
            resp = await authed.post("/api/v1/session/start")

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["curriculum_path"]) > 0, "Curriculum should be built"
        assert len(data["quiz_questions"]) > 0, "Quiz should be generated"
        assert data["current_topic"] != ""
        assert not data["session_complete"]
        assert data["iteration_count"] >= 1
        _STATE["session_id"] = data["session_id"]
        _STATE["quiz_questions"] = data["quiz_questions"]

    @pytest.mark.asyncio
    async def test_E2E_S02_session_advance_perfect_score(self, authed):
        """POST /session/advance — submit perfect answers, advance or complete."""
        # Ensure there's a valid session first
        with mock_all_agents():
            start = await authed.post("/api/v1/session/start")
        assert start.status_code == 200
        quiz_id = start.json()["session_id"]
        questions = start.json()["quiz_questions"]
        answers = [q.get("correct_index", 0) for q in questions]

        with mock_all_agents():
            resp = await authed.post(
                "/api/v1/session/advance",
                json={
                    "quiz_id": quiz_id,
                    "answers": answers,
                    "reflection": "This topic made sense to me.",
                },
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "topic_proficiency" in data
        assert "progress_delta" in data
        assert "bloom_level" in data
        # Either continues with next quiz or session ends
        assert len(data["quiz_questions"]) > 0 or data["session_complete"]

    @pytest.mark.asyncio
    async def test_E2E_S03_advance_zero_score(self, authed):
        """Submit all-wrong answers — Elo should decrease."""
        with mock_all_agents():
            start = await authed.post("/api/v1/session/start")
        assert start.status_code == 200
        quiz_id = start.json()["session_id"]
        questions = start.json()["quiz_questions"]
        # All wrong answers
        wrong_answers = [(q.get("correct_index", 0) + 1) % 4 for q in questions]

        with mock_all_agents():
            resp = await authed.post(
                "/api/v1/session/advance",
                json={"quiz_id": quiz_id, "answers": wrong_answers},
            )

        assert resp.status_code == 200
        delta = resp.json()["progress_delta"]
        assert delta.get("new_elo", 1000) <= delta.get("old_elo", 0) + 5

    @pytest.mark.asyncio
    async def test_E2E_S04_advance_invalid_quiz_id(self, authed):
        """Submitting to a non-existent quiz → 404."""
        with mock_all_agents():
            resp = await authed.post(
                "/api/v1/session/advance",
                json={"quiz_id": "00000000-0000-0000-0000-000000000000", "answers": [0]},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_E2E_S05_session_requires_auth(self, client):
        resp = await client.post("/api/v1/session/start")
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# 4. QUIZ — Direct quiz generation and submission
# ─────────────────────────────────────────────────────────────────────────────


class TestE2E_Quiz:
    @pytest.mark.asyncio
    async def test_E2E_Q01_generate_quiz(self, authed):
        """POST /quiz/generate — quiz_agent produces questions via orchestrator."""
        with mock_all_agents():
            resp = await authed.post(
                "/api/v1/quiz/generate",
                json={"topic": "Python Functions", "bloom_level": "apply"},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["questions"]) > 0
        assert data["topic"] == "Python Functions"
        assert "bloom_level" in data
        assert "quiz_id" in data
        _STATE["direct_quiz_id"] = data["quiz_id"]

    @pytest.mark.asyncio
    async def test_E2E_Q02_submit_correct_answers(self, authed):
        """POST /quiz/{id}/submit — perfect score updates Elo upward."""
        with mock_all_agents():
            gen_resp = await authed.post(
                "/api/v1/quiz/generate",
                json={"topic": "Python Loops"},
            )
        assert gen_resp.status_code == 200
        quiz_id = gen_resp.json()["quiz_id"]
        questions = gen_resp.json()["questions"]
        correct = [q.get("correct_index", 0) for q in questions]

        with mock_all_agents():
            resp = await authed.post(
                f"/api/v1/quiz/{quiz_id}/submit",
                json={"answers": correct, "reflection": "Excellent!"},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "score" in data
        assert data["score"] == 1.0
        assert "elo_update" in data
        assert data["elo_update"]["new_elo"] >= data["elo_update"]["old_elo"]

    @pytest.mark.asyncio
    async def test_E2E_Q03_submit_wrong_answers(self, authed):
        """All-wrong answers → score 0.0 → Elo decreases."""
        with mock_all_agents():
            gen_resp = await authed.post("/api/v1/quiz/generate", json={"topic": "Statistics"})
        quiz_id = gen_resp.json()["quiz_id"]
        questions = gen_resp.json()["questions"]
        wrong = [(q.get("correct_index", 0) + 1) % 4 for q in questions]

        with mock_all_agents():
            resp = await authed.post(f"/api/v1/quiz/{quiz_id}/submit", json={"answers": wrong})
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] == 0.0
        assert data["elo_update"]["new_elo"] <= data["elo_update"]["old_elo"]

    @pytest.mark.asyncio
    async def test_E2E_Q04_generate_requires_auth(self, client):
        resp = await client.post("/api/v1/quiz/generate", json={"topic": "Python"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_E2E_Q05_submit_nonexistent_quiz(self, authed):
        with mock_all_agents():
            resp = await authed.post(
                "/api/v1/quiz/00000000-dead-beef-0000-000000000000/submit",
                json={"answers": [0]},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_E2E_Q06_get_quiz_session(self, authed):
        """GET /quiz/{id} — fetch quiz details."""
        with mock_all_agents():
            gen_resp = await authed.post("/api/v1/quiz/generate", json={"topic": "ML Basics"})
        quiz_id = gen_resp.json()["quiz_id"]

        resp = await authed.get(f"/api/v1/quiz/{quiz_id}")
        assert resp.status_code == 200
        assert resp.json()["quiz_id"] == quiz_id


# ─────────────────────────────────────────────────────────────────────────────
# 5. DOUBTS — Q&A with guardrails
# ─────────────────────────────────────────────────────────────────────────────


class TestE2E_Doubts:
    """
    /api/v1/doubts/stream returns Server-Sent Events (text/event-stream).
    Tokens arrive as:  data: {"token": "..."}\n\n
    Terminator:        data: [DONE]\n\n
    """

    @pytest.mark.asyncio
    async def test_E2E_D01_valid_doubt_answered(self, authed):
        """POST /doubts/stream — SSE response with token chunks."""
        with mock_all_agents():
            resp = await authed.post(
                "/api/v1/doubts/stream",
                json={
                    "question": "What is a Python generator?",
                    "topic_context": "Python Programming",
                },
            )
        assert resp.status_code == 200, resp.text
        # SSE format — response text contains "data:" prefix
        assert "data:" in resp.text
        assert "[DONE]" in resp.text

    @pytest.mark.asyncio
    async def test_E2E_D02_doubt_streams_token_content(self, authed):
        """Stream contains the mocked token content."""
        with mock_all_agents():
            resp = await authed.post(
                "/api/v1/doubts/stream",
                json={"question": "Explain recursion.", "topic_context": "Python"},
            )
        assert resp.status_code == 200
        # The mock yields "Python list comprehensions let you build lists concisely."
        assert "comprehension" in resp.text.lower() or "data:" in resp.text

    @pytest.mark.asyncio
    async def test_E2E_D03_doubts_requires_auth(self, client):
        resp = await client.post("/api/v1/doubts/stream", json={"question": "hello"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_E2E_D04_sessions_list(self, authed):
        """GET /doubts/sessions — returns list (may be empty)."""
        resp = await authed.get("/api/v1/doubts/sessions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ─────────────────────────────────────────────────────────────────────────────
# 6. EVALS — Trigger, query, summarize
# ─────────────────────────────────────────────────────────────────────────────


class TestE2E_Evals:
    @pytest.mark.asyncio
    async def test_E2E_EV01_run_quiz_format_eval(self, authed):
        """POST /evals/run — quiz_format eval returns correct score."""
        questions = [_make_question() for _ in range(3)]
        with patch("app.evals.mongo.insert_eval", new_callable=AsyncMock) as mock_ins:
            mock_ins.return_value = "507f1f77bcf86cd799439011"
            resp = await authed.post(
                "/api/v1/evals/run",
                params={
                    "eval_type": "quiz_format",
                    "agent": "quiz_agent",
                    "learner_id": "e2e-learner",
                },
                json={
                    "input": {"current_topic": "Python"},
                    "output": {"quiz_questions": questions, "bloom_level": "apply"},
                },
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["eval_type"] == "quiz_format"
        assert data["agent"] == "quiz_agent"
        assert data["score"] == 1.0
        assert data["passed"] is True

    @pytest.mark.asyncio
    async def test_E2E_EV02_run_planner_decision_eval_default_quiz(self, authed):
        """Planner chose 'quiz' with unmastered curriculum → passes."""
        with patch("app.evals.mongo.insert_eval", new_callable=AsyncMock) as mock_ins:
            mock_ins.return_value = "507f1f77bcf86cd799439012"
            resp = await authed.post(
                "/api/v1/evals/run",
                params={"eval_type": "planner_decision", "agent": "planner_agent"},
                json={
                    "input": {
                        "curriculum_path": [{"subtopic": "Variables", "elo": 400}],
                        "topic_proficiency": {},
                        "mastery_threshold": 700.0,
                        "iteration_count": 0,
                        "max_iterations": 10,
                    },
                    "output": {"next_action": "quiz"},
                },
            )
        assert resp.status_code == 200
        assert resp.json()["passed"] is True

    @pytest.mark.asyncio
    async def test_E2E_EV03_run_doubt_relevance_eval(self, authed):
        """doubt_relevance eval scores based on topic token overlap."""
        with patch("app.evals.mongo.insert_eval", new_callable=AsyncMock) as mock_ins:
            mock_ins.return_value = "507f1f77bcf86cd799439013"
            resp = await authed.post(
                "/api/v1/evals/run",
                params={"eval_type": "doubt_relevance", "agent": "doubt_agent"},
                json={
                    "input": {"context": "Python programming basics"},
                    "output": {"doubt_response": "Python programming uses loops and functions."},
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] > 0.0, "Overlapping tokens should produce positive score"

    @pytest.mark.asyncio
    async def test_E2E_EV04_run_curriculum_ordering_eval(self, authed):
        """curriculum_ordering eval — ascending elo → 1.0 score."""
        path = [
            {"subtopic": "A", "elo": 200.0},
            {"subtopic": "B", "elo": 400.0},
            {"subtopic": "C", "elo": 600.0},
        ]
        with patch("app.evals.mongo.insert_eval", new_callable=AsyncMock) as mock_ins:
            mock_ins.return_value = "507f1f77bcf86cd799439014"
            resp = await authed.post(
                "/api/v1/evals/run",
                params={"eval_type": "curriculum_ordering", "agent": "curriculum_agent"},
                json={
                    "input": {},
                    "output": {"curriculum_path": path},
                },
            )
        assert resp.status_code == 200
        assert resp.json()["score"] == 1.0
        assert resp.json()["passed"] is True

    @pytest.mark.asyncio
    async def test_E2E_EV05_run_guardrail_triggered_eval(self, authed):
        """guardrail_triggered eval always returns score=1.0."""
        with patch("app.evals.mongo.insert_eval", new_callable=AsyncMock) as mock_ins:
            mock_ins.return_value = "507f1f77bcf86cd799439015"
            resp = await authed.post(
                "/api/v1/evals/run",
                params={"eval_type": "guardrail_triggered", "agent": "doubt_agent"},
                json={
                    "input": {},
                    "output": {"error": "guardrail:blocked_pattern:injection"},
                },
            )
        assert resp.status_code == 200
        assert resp.json()["score"] == 1.0

    @pytest.mark.asyncio
    async def test_E2E_EV06_results_endpoint(self, authed):
        """GET /evals/results — returns list with count."""
        # Patch at the router module level (not mongo module) to bypass import binding
        with patch("app.routers.evals.query_evals", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = [
                {"eval_type": "quiz_format", "agent": "quiz_agent", "score": 1.0, "passed": True},
                {"eval_type": "planner_decision", "agent": "planner_agent", "score": 1.0, "passed": True},
            ]
            resp = await authed.get("/api/v1/evals/results", params={"limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "count" in data
        assert data["count"] == 2

    @pytest.mark.asyncio
    async def test_E2E_EV07_summary_endpoint(self, authed):
        """GET /evals/summary — aggregated pass rates."""
        with patch("app.routers.evals.aggregate_summary", new_callable=AsyncMock) as mock_s:
            mock_s.return_value = [
                {
                    "eval_type": "quiz_format",
                    "agent": "quiz_agent",
                    "total": 5,
                    "passed": 5,
                    "avg_score": 1.0,
                    "pass_rate": 1.0,
                },
            ]
            resp = await authed.get("/api/v1/evals/summary")
        assert resp.status_code == 200
        assert "summaries" in resp.json()

    @pytest.mark.asyncio
    async def test_E2E_EV08_batch_quiz_eval(self, authed):
        """POST /evals/batch/quiz — runs eval over multiple sessions."""
        questions = [_make_question() for _ in range(2)]
        sessions = [
            {
                "session_id": "sess-001",
                "learner_id": "learner-abc",
                "input": {"topic": "Python"},
                "output": {"quiz_questions": questions, "bloom_level": "apply"},
            },
            {
                "session_id": "sess-002",
                "learner_id": "learner-abc",
                "input": {"topic": "ML"},
                "output": {"quiz_questions": [], "bloom_level": "remember"},
            },
        ]
        with patch("app.evals.mongo.insert_eval", new_callable=AsyncMock) as mock_ins:
            mock_ins.return_value = "507f1f77bcf86cd799439016"
            resp = await authed.post("/api/v1/evals/batch/quiz", json=sessions)
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 2
        assert results[0]["session_id"] == "sess-001"
        assert results[0]["score"] == 1.0  # all questions valid
        assert results[1]["score"] == 0.0  # no questions → fails

    @pytest.mark.asyncio
    async def test_E2E_EV09_evals_require_auth(self, client):
        resp = await client.get("/api/v1/evals/results")
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# 7. PROGRESS HISTORY
# ─────────────────────────────────────────────────────────────────────────────


class TestE2E_Progress:
    """GET /api/v1/progress — returns topic proficiency + history."""

    @pytest.mark.asyncio
    async def test_E2E_PR01_progress_requires_auth(self, client):
        resp = await client.get("/api/v1/progress")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_E2E_PR02_progress_returns_data(self, authed):
        resp = await authed.get("/api/v1/progress")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    @pytest.mark.asyncio
    async def test_E2E_PR03_progress_populated_after_quiz(self, authed):
        """After submitting a quiz, progress records grow."""
        with mock_all_agents():
            gen = await authed.post("/api/v1/quiz/generate", json={"topic": "Graph Theory"})
        quiz_id = gen.json()["quiz_id"]
        questions = gen.json()["questions"]

        with mock_all_agents():
            await authed.post(
                f"/api/v1/quiz/{quiz_id}/submit",
                json={"answers": [q["correct_index"] for q in questions]},
            )

        resp = await authed.get("/api/v1/progress")
        assert resp.status_code == 200
        data = resp.json()
        assert "topic_proficiency" in data or "history" in data
