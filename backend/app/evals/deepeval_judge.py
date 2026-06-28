"""
DeepEval judge that wraps the platform's NVIDIA NIM client (OpenAI-compatible) — no new credentials.

DeepEval metrics call the judge with a pydantic ``schema`` to extract structured output (claims,
verdicts, scores). We use ``instructor`` (the docs-recommended path for API models) in ``MD_JSON``
mode — it prompts for JSON and validates against the schema, which works on any OpenAI-compatible
model without needing native ``response_format`` support. A plain ``extract_json`` repair is the last
resort. The no-schema path returns raw text via the unpatched client.
"""

from __future__ import annotations

import structlog
from deepeval.models import DeepEvalBaseLLM
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

from app.config import settings

log = structlog.get_logger()


class NvidiaJudge(DeepEvalBaseLLM):
    """A DeepEval judge over the NVIDIA NIM (OpenAI-compatible) client."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.EVAL_JUDGE_MODEL
        self._raw: OpenAI | None = None
        self._araw: AsyncOpenAI | None = None
        self._instr = None
        self._ainstr = None

    # ── DeepEvalBaseLLM interface ────────────────────────────────────────────
    def get_model_name(self) -> str:
        return f"nvidia:{self.model}"

    def load_model(self):
        return self._raw_client()

    def generate(self, prompt: str, schema: type[BaseModel] | None = None):
        if schema is None:
            resp = self._raw_client().chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            return resp.choices[0].message.content or ""
        try:
            return self._instr_client().chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_model=schema,
                temperature=0,
                max_retries=2,
            )
        except Exception as e:  # noqa: BLE001 - fall back to manual JSON repair
            log.warning("deepeval_judge_instructor_failed", error=str(e)[:200])
            return self._repair(self.generate(prompt + "\n\nReturn ONLY valid JSON.", None), schema)

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None):
        if schema is None:
            resp = await self._araw_client().chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            return resp.choices[0].message.content or ""
        try:
            return await self._ainstr_client().chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_model=schema,
                temperature=0,
                max_retries=2,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("deepeval_judge_instructor_failed_async", error=str(e)[:200])
            text = await self.a_generate(prompt + "\n\nReturn ONLY valid JSON.", None)
            return self._repair(text, schema)

    # ── clients (lazy) ───────────────────────────────────────────────────────
    def _raw_client(self) -> OpenAI:
        if self._raw is None:
            # max_retries makes the OpenAI client back off + retry on NVIDIA 429 (rate limit) / 5xx.
            self._raw = OpenAI(
                base_url=settings.NVIDIA_BASE_URL,
                api_key=settings.NVIDIA_API_KEY,
                max_retries=settings.EVAL_JUDGE_MAX_RETRIES,
                timeout=settings.EVAL_JUDGE_TIMEOUT_S,
            )
        return self._raw

    def _araw_client(self) -> AsyncOpenAI:
        if self._araw is None:
            self._araw = AsyncOpenAI(
                base_url=settings.NVIDIA_BASE_URL,
                api_key=settings.NVIDIA_API_KEY,
                max_retries=settings.EVAL_JUDGE_MAX_RETRIES,
                timeout=settings.EVAL_JUDGE_TIMEOUT_S,
            )
        return self._araw

    def _instr_client(self):
        if self._instr is None:
            import instructor

            self._instr = instructor.from_openai(self._raw_client(), mode=instructor.Mode.MD_JSON)
        return self._instr

    def _ainstr_client(self):
        if self._ainstr is None:
            import instructor

            self._ainstr = instructor.from_openai(self._araw_client(), mode=instructor.Mode.MD_JSON)
        return self._ainstr

    @staticmethod
    def _repair(text: str, schema: type[BaseModel]) -> BaseModel:
        """Last-resort: pull JSON out of free text and validate it against the schema."""
        from app.agents.json_utils import extract_json

        data = extract_json(text) or {}
        return schema(**data)


def get_judge(model: str | None = None) -> NvidiaJudge:
    """Return a DeepEval-compatible judge backed by the NVIDIA NIM client."""
    return NvidiaJudge(model)
