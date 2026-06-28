"""
Multi-language code execution for the interview compiler.

Primary backend is **Piston** (self-hosted, sandboxed, 60+ languages) when ``PISTON_BASE_URL`` is
configured. Without it, falls back to a local Python-only subprocess with OS resource limits — fine
for dev, but not a real sandbox (it runs in the API container), so production should run Piston.

All paths return the same shape: ``{"stdout": str, "stderr": str, "exit_code": int}``.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

import httpx
import structlog

from app.config import settings

log = structlog.get_logger()

_MAX_OUTPUT = 4000  # chars
_CODE_TIMEOUT = 10  # seconds (local subprocess wall clock)
_MEM_LIMIT_BYTES = 128 * 1024 * 1024  # 128 MB
_CPU_LIMIT_S = 8  # seconds CPU (< _CODE_TIMEOUT so it fires first)

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


async def run_code(language: str, code: str, stdin: str = "") -> dict:
    """Execute ``code`` in ``language``; route to Piston if configured, else local Python fallback."""
    lang = (language or "python").strip().lower()
    code = (code or "").strip()
    if not code:
        return {"stdout": "", "stderr": "", "exit_code": 0}

    if settings.PISTON_BASE_URL:
        return await _run_piston(lang, code, stdin)
    return await _run_local_python(lang, code, stdin)


async def _run_piston(lang: str, code: str, stdin: str) -> dict:
    """Run via the Piston execute API (sandboxed)."""
    if lang not in SUPPORTED_LANGUAGES:
        return {"stdout": "", "stderr": f"Unsupported language: {lang}", "exit_code": 1}
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
        async with httpx.AsyncClient(timeout=(settings.CODE_RUN_TIMEOUT_MS / 1000) + 10) as client:
            resp = await client.post(f"{settings.PISTON_BASE_URL.rstrip('/')}/api/v2/execute", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:  # noqa: BLE001
        log.warning("piston_execute_failed", lang=lang, error=str(e)[:200])
        return {"stdout": "", "stderr": "Code execution is unavailable right now — please try again.", "exit_code": 1}

    run = data.get("run") or {}
    compile_stage = data.get("compile") or {}
    # Surface compile errors first (they explain why run produced nothing).
    stderr = ""
    if compile_stage.get("code", 0) not in (0, None) and compile_stage.get("stderr"):
        stderr += compile_stage["stderr"]
    if run.get("stderr"):
        stderr += run["stderr"]
    return {
        "stdout": _truncate(run.get("stdout", "")),
        "stderr": _truncate(stderr),
        "exit_code": run.get("code", 0) or 0,
    }


async def _run_local_python(lang: str, code: str, stdin: str) -> dict:
    """Local fallback (no Piston): Python only, in a resource-limited subprocess."""
    if lang not in ("python", "python3"):
        return {
            "stdout": "",
            "stderr": f"'{lang}' isn't available here — the multi-language sandbox (Piston) is not configured.",
            "exit_code": 1,
        }

    def _preexec_limits() -> None:
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (_MEM_LIMIT_BYTES, _MEM_LIMIT_BYTES))
            resource.setrlimit(resource.RLIMIT_CPU, (_CPU_LIMIT_S, _CPU_LIMIT_S))
        except Exception:
            pass  # non-Unix — skip

    def _run() -> dict:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                input=stdin or "",
                capture_output=True,
                text=True,
                timeout=_CODE_TIMEOUT,
                preexec_fn=_preexec_limits if sys.platform != "win32" else None,
            )
            return {"stdout": _truncate(proc.stdout), "stderr": _truncate(proc.stderr), "exit_code": proc.returncode}
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": f"Execution timed out after {_CODE_TIMEOUT}s", "exit_code": 124}
        except Exception as e:  # noqa: BLE001
            return {"stdout": "", "stderr": str(e)[:500], "exit_code": 1}

    return await asyncio.to_thread(_run)
