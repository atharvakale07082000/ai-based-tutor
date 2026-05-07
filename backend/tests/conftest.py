import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async")


@pytest_asyncio.fixture
async def client():
    from app.main import app
    from app.database import create_all_tables
    await create_all_tables()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def client_with_db_override():
    """Client with DB dependency overridden — no real DB connection required."""
    from unittest.mock import MagicMock
    from app.main import app
    from app.database import get_db

    async def _mock_db():
        # execute() is awaited, so AsyncMock; its result is used synchronously
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        result_mock.scalars.return_value.all.return_value = []

        mock = AsyncMock()
        mock.execute.return_value = result_mock
        mock.add = MagicMock()
        yield mock

    app.dependency_overrides[get_db] = _mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)
