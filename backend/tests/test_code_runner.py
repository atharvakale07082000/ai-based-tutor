"""Tests for the interview code checker (Piston execution + LLM review fallback)."""

import pytest
from app.services import code_runner


def _mock_review(monkeypatch, response: str):
    """Point the reviewer's LLM call at a canned response.

    `_review_with_llm` imports the helper at call time, so patching the source module
    is what takes effect.
    """

    async def _fake(**kwargs):
        return response

    monkeypatch.setattr("app.hf.client.hf_chat_completion_with_resilience", _fake)


# ─── LLM review (default path: no Piston configured) ──────────────────────────


@pytest.mark.asyncio
async def test_review_is_the_default_when_piston_is_unset(monkeypatch):
    monkeypatch.setattr(code_runner.settings, "PISTON_BASE_URL", "")
    _mock_review(
        monkeypatch,
        '{"verdict": "looks_correct", "predicted_output": "hello world\\n", "issues": [], '
        '"notes": "Clean and correct."}',
    )
    out = await code_runner.run_code("python", "print('hello world')")

    assert out["mode"] == "ai-review"
    assert out["exit_code"] == 0
    assert out["stdout"] == "hello world\n"
    assert out["review"]["verdict"] == "looks_correct"
    assert out["review"]["notes"] == "Clean and correct."


@pytest.mark.asyncio
async def test_review_reports_non_python_languages(monkeypatch):
    """The old local fallback rejected everything but Python; the reviewer handles any language."""
    monkeypatch.setattr(code_runner.settings, "PISTON_BASE_URL", "")
    _mock_review(
        monkeypatch,
        '{"verdict": "looks_correct", "predicted_output": "", "issues": []}',
    )
    out = await code_runner.run_code(
        "java", "class Main { public static void main(String[] a) {} }"
    )

    assert out["mode"] == "ai-review"
    assert out["exit_code"] == 0


@pytest.mark.asyncio
async def test_will_not_run_verdict_is_an_error(monkeypatch):
    monkeypatch.setattr(code_runner.settings, "PISTON_BASE_URL", "")
    _mock_review(
        monkeypatch,
        '{"verdict": "will_not_run", "predicted_output": "", "issues": ["Missing colon on line 1"], '
        '"notes": "SyntaxError before any output."}',
    )
    out = await code_runner.run_code("python", "if True\n  pass")

    assert out["exit_code"] == 1
    assert out["stderr"] == "SyntaxError before any output."
    assert out["review"]["issues"] == ["Missing colon on line 1"]


@pytest.mark.asyncio
async def test_malformed_llm_json_degrades_instead_of_raising(monkeypatch):
    monkeypatch.setattr(code_runner.settings, "PISTON_BASE_URL", "")
    _mock_review(monkeypatch, "I could not produce JSON today, sorry.")
    out = await code_runner.run_code("python", "print(1)")

    assert out["mode"] == "ai-review"
    assert out["exit_code"] == 0  # never blocks the interview
    assert out["review"]["verdict"] == "has_issues"
    assert out["review"]["issues"] == []


@pytest.mark.asyncio
async def test_llm_failure_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(code_runner.settings, "PISTON_BASE_URL", "")

    async def _boom(**kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.hf.client.hf_chat_completion_with_resilience", _boom)
    out = await code_runner.run_code("python", "print(1)")

    assert out["exit_code"] == 1
    assert "could not review" in out["stderr"].lower()


@pytest.mark.asyncio
async def test_empty_code_is_noop_and_calls_no_model(monkeypatch):
    monkeypatch.setattr(code_runner.settings, "PISTON_BASE_URL", "")

    async def _boom(**kwargs):
        raise AssertionError("empty code must not reach the model")

    monkeypatch.setattr("app.hf.client.hf_chat_completion_with_resilience", _boom)
    out = await code_runner.run_code("python", "   ")

    assert out["stdout"] == "" and out["stderr"] == "" and out["exit_code"] == 0


def test_review_normalizer_coerces_garbage():
    review = code_runner._normalize_review(
        {"verdict": "nonsense", "issues": ["a", "", "b", "c", "d", "e"]}
    )
    assert review["verdict"] == "has_issues"  # unknown verdicts fall back
    assert review["issues"] == ["a", "b", "c", "d"]  # blanks dropped, capped at 4
    assert review["predicted_output"] == "" and review["notes"] == ""


# ─── Security regression ──────────────────────────────────────────────────────


def test_no_local_execution_path_exists():
    """Learner code must never run in the API container — that was an RCE hole.

    Matches code, not prose: the module docstring explains *why* there is no such path.
    """
    import inspect

    source = inspect.getsource(code_runner)
    assert "import subprocess" not in source
    assert "subprocess.run" not in source
    assert "subprocess" not in dir(code_runner)  # nothing imported it either
    assert not hasattr(code_runner, "_run_local_python")


# ─── Piston (real execution, when configured) ─────────────────────────────────


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

    assert out["stdout"] == "ok\n" and out["stderr"] == "" and out["exit_code"] == 0
    assert out["mode"] == "executed" and out["review"] is None
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
            return {
                "compile": {"code": 1, "stderr": "syntax error"},
                "run": {"stdout": "", "stderr": "", "code": 1},
            }

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
