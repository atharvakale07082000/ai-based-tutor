import pytest_asyncio
from httpx import ASGITransport, AsyncClient


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async")


@pytest_asyncio.fixture
async def client():
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def client_with_db_override():
    """Alias for client — MongoDB has no FastAPI DB dependency to override."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
