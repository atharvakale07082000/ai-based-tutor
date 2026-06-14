import pytest_asyncio
from httpx import ASGITransport, AsyncClient


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async")


@pytest_asyncio.fixture(autouse=True)
async def _reset_mongo_client():
    """
    AsyncMongoClient binds to the event loop it was created on. pytest-asyncio
    gives each test function its own loop, so the module-level client singleton
    in app.db.mongo must be torn down between tests to avoid
    "Cannot use AsyncMongoClient in different event loop" errors.
    """
    import app.db.mongo as mongo

    yield
    if mongo._client is not None:
        await mongo._client.close()
        mongo._client = None


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
