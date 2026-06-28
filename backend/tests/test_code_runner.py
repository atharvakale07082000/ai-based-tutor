"""Tests for the multi-language code runner (Piston primary + local Python fallback)."""

import pytest
from app.services import code_runner


@pytest.mark.asyncio
async def test_local_python_fallback_runs(monkeypatch):
    monkeypatch.setattr(code_runner.settings, "PISTON_BASE_URL", "")
    out = await code_runner.run_code("python", "print('hello world')")
    assert out["exit_code"] == 0
    assert "hello world" in out["stdout"]


@pytest.mark.asyncio
async def test_local_fallback_rejects_non_python(monkeypatch):
    monkeypatch.setattr(code_runner.settings, "PISTON_BASE_URL", "")
    out = await code_runner.run_code("java", "class Main {}")
    assert out["exit_code"] == 1
    assert "piston" in out["stderr"].lower() or "isn't available" in out["stderr"].lower()


@pytest.mark.asyncio
async def test_empty_code_is_noop(monkeypatch):
    monkeypatch.setattr(code_runner.settings, "PISTON_BASE_URL", "")
    assert await code_runner.run_code("python", "   ") == {"stdout": "", "stderr": "", "exit_code": 0}


@pytest.mark.asyncio
async def test_piston_request_shape_and_response(monkeypatch):
    monkeypatch.setattr(code_runner.settings, "PISTON_BASE_URL", "http://piston:2000")
    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"run": {"stdout": "ok\n", "stderr": "", "code": 0}}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(code_runner.httpx, "AsyncClient", _Client)
    out = await code_runner.run_code("cpp", "int main(){}", stdin="data")

    assert out == {"stdout": "ok\n", "stderr": "", "exit_code": 0}
    assert captured["url"].endswith("/api/v2/execute")
    assert captured["json"]["language"] == "c++"  # alias mapped
    assert captured["json"]["files"][0]["name"] == "main.cpp"
    assert captured["json"]["stdin"] == "data"


@pytest.mark.asyncio
async def test_piston_compile_error_is_surfaced(monkeypatch):
    monkeypatch.setattr(code_runner.settings, "PISTON_BASE_URL", "http://p:2000")

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"compile": {"code": 1, "stderr": "syntax error"}, "run": {"stdout": "", "stderr": "", "code": 1}}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(code_runner.httpx, "AsyncClient", _Client)
    out = await code_runner.run_code("c", "bad code")
    assert "syntax error" in out["stderr"]
    assert out["exit_code"] == 1


def test_supported_language_ids_deduped():
    ids = code_runner.supported_language_ids()
    assert "python" in ids and "cpp" in ids
    # aliases collapse: python3→python and js→javascript shouldn't double-list the piston lang
    assert ids.count("python") == 1
