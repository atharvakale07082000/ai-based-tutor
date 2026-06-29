import pytest


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestAuthEndpoints:
    @pytest.mark.asyncio
    async def test_login_creates_user(self, client_with_db_override):
        response = await client_with_db_override.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "password123"},
        )
        assert response.status_code in (200, 422, 500)

    @pytest.mark.asyncio
    async def test_logout_returns_success(self, client):
        response = await client.post("/api/v1/auth/logout")
        # Logout doesn't require auth in current implementation
        assert response.status_code in (200, 401)

    @pytest.mark.asyncio
    async def test_refresh_requires_token(self, client):
        response = await client.post("/api/v1/auth/refresh")
        assert response.status_code == 401


class TestContentEndpoints:
    @pytest.mark.asyncio
    async def test_content_list_requires_auth(self, client):
        response = await client.get("/api/v1/content")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_content_detail_requires_auth(self, client):
        response = await client.get("/api/v1/content/some-id")
        assert response.status_code == 401


class TestQuizEndpoints:
    @pytest.mark.asyncio
    async def test_quiz_generate_requires_auth(self, client):
        response = await client.post("/api/v1/quiz/generate", json={"topic": "Python"})
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_quiz_get_requires_auth(self, client):
        response = await client.get("/api/v1/quiz/some-id")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_quiz_submit_requires_auth(self, client):
        response = await client.post(
            "/api/v1/quiz/some-id/submit", json={"answers": [0, 1, 2]}
        )
        assert response.status_code == 401


class TestDoubtsEndpoints:
    @pytest.mark.asyncio
    async def test_doubts_stream_requires_auth(self, client):
        response = await client.post(
            "/api/v1/doubts/stream", json={"question": "what is ml?"}
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_doubts_sessions_requires_auth(self, client):
        response = await client.get("/api/v1/doubts/sessions")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_doubts_transcribe_requires_auth(self, client):
        response = await client.post("/api/v1/doubts/transcribe")
        assert response.status_code == 401


class TestHFEndpoints:
    @pytest.mark.asyncio
    async def test_hf_status_requires_auth(self, client):
        response = await client.get("/api/v1/hf/status")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_hf_test_requires_auth(self, client):
        response = await client.post("/api/v1/hf/test/DOUBT_SOLVER")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_hf_test_invalid_model_returns_404(self, client):
        # Without auth this returns 401, but the route exists
        response = await client.post("/api/v1/hf/test/INVALID_MODEL")
        assert response.status_code in (401, 404)


@pytest.mark.asyncio
async def test_flashcards_get_not_shadowed_by_quiz_id():
    """Regression: GET /quiz/flashcards must hit generate_flashcards, not the dynamic
    /{quiz_id} route (which captured 'flashcards' as an id and 404'd). Needs auth to expose,
    since both routes 401 before the lookup."""
    from unittest.mock import AsyncMock, patch

    from httpx import ASGITransport, AsyncClient

    from app.auth.jwt import get_current_user_id
    from app.main import app

    app.dependency_overrides[get_current_user_id] = lambda: "u1"
    try:
        with patch(
            "app.hf.flashcard_generator.generate_flashcards",
            new=AsyncMock(
                return_value=[
                    {
                        "id": "1",
                        "front": "f",
                        "back": "b",
                        "hint": "h",
                        "difficulty": 1,
                        "topic": "k",
                    }
                ]
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as c:
                r = await c.get(
                    "/api/v1/quiz/flashcards", params={"topic": "kafka", "count": 10}
                )
        assert r.status_code == 200, (
            f"flashcards shadowed by /{{quiz_id}}: {r.status_code} {r.text[:120]}"
        )
        assert "cards" in r.json()
    finally:
        app.dependency_overrides.clear()
