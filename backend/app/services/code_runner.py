"""
Code checking for the interview compiler.

Two backends, one response shape:

- **Piston** (``PISTON_BASE_URL`` set) — real sandboxed execution, 60+ languages.
- **LLM review** (the default) — an LLM reads the submission and reports what it *would* do:
  a verdict, the output it would print, and the issues an interviewer would raise.

There is deliberately **no local-subprocess path**. Running learner code in the API container
was a remote-code-execution hole: any authenticated user could read the process environment
(Mongo URI, JWT secret, provider keys) and exfiltrate it. Never reintroduce one — if you need
real execution, run Piston.

All paths return ``{"stdout", "stderr", "exit_code", "mode", "review"}``.
``mode`` is ``"executed"`` or ``"ai-review"``; ``review`` is populated only for the latter.
"""

from __future__ import annotations

import httpx
import structlog

from app.config import settings

log = structlog.get_logger()

_MAX_OUTPUT = 4000  # chars
_MAX_CODE_CHARS = 7000  # prompt budget (matches interview_scorer._chat)
_MAX_STDIN_CHARS = 1000
_REVIEW_TIMEOUT_S = 30.0

_VERDICTS = ("looks_correct", "has_issues", "will_not_run")

# our language id (and aliases) → (Piston language, source filename)
SUPPORTED_LANGUAGES: dict[str, tuple[str, str]] = {
    "python": ("python", "main.py"),
    "python3": ("python", "main.py"),
    "javascript": ("javascript", "main.js"),
    "js": ("javascript", "main.js"),
    "typescript": ("typescript", "main.ts"),
    "ts": ("typescript", "main.ts"),
    "java": ("java", "Main.java"),
    "c": ("c", "main.c"),
    "cpp": ("c++", "main.cpp"),
    "c++": ("c++", "main.cpp"),
    "csharp": ("csharp", "main.cs"),
    "go": ("go", "main.go"),
    "rust": ("rust", "main.rs"),
    "ruby": ("ruby", "main.rb"),
    "php": ("php", "main.php"),
    "kotlin": ("kotlin", "Main.kt"),
    "swift": ("swift", "main.swift"),
    "bash": ("bash", "main.sh"),
}


def supported_language_ids() -> list[str]:
    """Canonical language ids the UI can offer (deduped, aliases collapsed)."""
    seen, out = set(), []
    for key, (piston, _) in SUPPORTED_LANGUAGES.items():
        if piston not in seen:
            seen.add(piston)
            out.append(key)
    return out


def _truncate(text: str) -> str:
    return (text or "")[:_MAX_OUTPUT]


def _result(
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    mode: str = "executed",
    review: dict | None = None,
) -> dict:
    """Build the one response shape every backend returns."""
    return {
        "stdout": _truncate(stdout),
        "stderr": _truncate(stderr),
        "exit_code": exit_code,
        "mode": mode,
        "review": review,
    }


def _canonical_language(lang: str) -> str:
    """Display/Piston name for a language id ('cpp' → 'c++'); unknown ids pass through."""
    return SUPPORTED_LANGUAGES.get(lang, (lang, ""))[0]


async def run_code(language: str, code: str, stdin: str = "") -> dict:
    """Check ``code``: execute it in Piston when configured, otherwise have an LLM review it."""
    lang = (language or "python").strip().lower()
    code = (code or "").strip()
    if not code:
        return _result()

    if settings.PISTON_BASE_URL:
        return await _run_piston(lang, code, stdin)
    return await _review_with_llm(lang, code, stdin)


async def _run_piston(lang: str, code: str, stdin: str) -> dict:
    """Run via the Piston execute API (sandboxed)."""
    if lang not in SUPPORTED_LANGUAGES:
        return _result(stderr=f"Unsupported language: {lang}", exit_code=1)
    piston_lang, filename = SUPPORTED_LANGUAGES[lang]
    payload = {
        "language": piston_lang,
        "version": "*",
        "files": [{"name": filename, "content": code}],
        "stdin": stdin or "",
        "run_timeout": settings.CODE_RUN_TIMEOUT_MS,
        "compile_timeout": settings.CODE_RUN_TIMEOUT_MS,
    }
    try:
        async with httpx.AsyncClient(
            timeout=(settings.CODE_RUN_TIMEOUT_MS / 1000) + 10
        ) as client:
            resp = await client.post(
                f"{settings.PISTON_BASE_URL.rstrip('/')}/api/v2/execute", json=payload
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:  # noqa: BLE001
        log.warning("piston_execute_failed", lang=lang, error=str(e)[:200])
        return _result(
            stderr="Code execution is unavailable right now — please try again.",
            exit_code=1,
        )

    run = data.get("run") or {}
    compile_stage = data.get("compile") or {}
    # Surface compile errors first (they explain why run produced nothing).
    stderr = ""
    if compile_stage.get("code", 0) not in (0, None) and compile_stage.get("stderr"):
        stderr += compile_stage["stderr"]
    if run.get("stderr"):
        stderr += run["stderr"]
    return _result(
        stdout=run.get("stdout", ""), stderr=stderr, exit_code=run.get("code", 0) or 0
    )


def _normalize_review(data: dict | None) -> dict:
    """Coerce a raw LLM object into the review contract, whatever it actually returned."""
    data = data or {}
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in _VERDICTS:
        verdict = "has_issues"
    issues = [str(i).strip() for i in (data.get("issues") or []) if str(i).strip()][:4]
    return {
        "verdict": verdict,
        "predicted_output": str(data.get("predicted_output") or ""),
        "issues": issues,
        "notes": str(data.get("notes") or "").strip(),
    }


async def _review_with_llm(lang: str, code: str, stdin: str) -> dict:
    """Default backend: an LLM reads the code and reports what it would do (never executes it)."""
    from app.agents.json_utils import JSON_OBJECT, extract_json
    from app.hf.client import hf_chat_completion_with_resilience
    from app.hf.models import HF_MODELS
    from app.prompts.loader import render_prompt

    prompt = render_prompt(
        "interview_scorer",
        "code_review",
        language=_canonical_language(lang),
        code=code[:_MAX_CODE_CHARS],
        stdin=(stdin or "")[:_MAX_STDIN_CHARS] or "(no input provided)",
    )
    cfg = HF_MODELS["DOUBT_SOLVER"]
    try:
        text = await hf_chat_completion_with_resilience(
            provider=cfg["provider"],
            model_id=cfg["model_id"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.1,
            timeout_s=_REVIEW_TIMEOUT_S,
            response_format=JSON_OBJECT,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("code_review_failed", lang=lang, error=str(e)[:200])
        return _result(
            stderr="The interviewer could not review your code just now — try again in a moment.",
            exit_code=1,
            mode="ai-review",
        )

    review = _normalize_review(extract_json(text))
    failed = review["verdict"] == "will_not_run"
    log.info(
        "code_reviewed",
        lang=lang,
        verdict=review["verdict"],
        issues=len(review["issues"]),
    )
    return _result(
        stdout="" if failed else review["predicted_output"],
        stderr=(review["notes"] or "This code would not run as written.")
        if failed
        else "",
        exit_code=1 if failed else 0,
        mode="ai-review",
        review=review,
    )
