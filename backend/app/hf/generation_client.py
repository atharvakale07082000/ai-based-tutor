"""Resilient generation client for the Qwen2.5-7B-Instruct generation paths
(doubt solver, quiz generator, course planner, interview scorer,
content generator).

Primary: NVIDIA NIM (OpenAI-compatible), rotating between two NVIDIA models
so a single bad/rate-limited model doesn't take down the primary path.
Fallback: Hugging Face "together" provider (Qwen2.5-7B-Instruct) on any
NVIDIA failure.
"""

from __future__ import annotations

from typing import Iterator

import structlog
from huggingface_hub import InferenceClient

# Plain OpenAI client, deliberately NOT `langfuse.openai`. Importing that wrapper
# patches the openai module process-wide, which also instruments the client Strands
# builds internally — so every agent LLM call was recorded twice: once by Strands and
# again by the wrapper, as parent and child with identical token counts. Strands traces
# its own calls, so this path is instrumented by hand instead (below).
from openai import OpenAI

from app.config import settings
from app.observability import observation

log = structlog.get_logger()


def _record_completion(gen, result) -> None:
    """Copy an OpenAI-shaped completion's output + token usage onto its observation."""
    try:
        usage = getattr(result, "usage", None)
        gen.update(
            output=result.choices[0].message.content,
            usage_details={
                "input": getattr(usage, "prompt_tokens", None),
                "output": getattr(usage, "completion_tokens", None),
            }
            if usage
            else None,
        )
    except Exception:  # noqa: BLE001 - never fail a generation over tracing
        pass


class ResilientGenerationClient:
    """Mimics `huggingface_hub.InferenceClient.chat_completion()`."""

    def __init__(self, hf_client: InferenceClient, nvidia_client: OpenAI) -> None:
        self._hf = hf_client
        self._nvidia = nvidia_client
        self._fallback_models = (settings.NVIDIA_MODEL, settings.NVIDIA_FALLBACK_MODEL)
        self._rotation = 0

    def _next_nvidia_model(self) -> str:
        """Return the next NVIDIA model ID in round-robin rotation."""
        model = self._fallback_models[self._rotation % len(self._fallback_models)]
        self._rotation += 1
        return model

    @staticmethod
    def _nvidia_extra_body() -> dict:
        """Return extra_body kwargs that disable CoT thinking mode on NVIDIA NIM reasoning models."""
        # Disable chain-of-thought "thinking" mode so reasoning models (e.g.
        # nemotron) put the answer directly in `content` instead of consuming
        # the whole max_tokens budget on `reasoning_content` and leaving
        # `content` as None.
        return {"chat_template_kwargs": {"enable_thinking": False}}

    def chat_completion(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int = 512,
        temperature: float = 0.1,
        stream: bool = False,
        response_format: dict | None = None,
        pin_nvidia_model: str | None = None,
    ):
        """Route to NVIDIA NIM (primary) or HF Together (fallback) for chat completion.

        ``pin_nvidia_model`` forces a specific NVIDIA model instead of the round-robin rotation —
        use it for strict structured output (e.g. quiz JSON), so the call always lands on the
        instruct model and never the reasoning model (which mangles JSON). ``response_format``
        (e.g. ``{"type": "json_object"}``) is passed through to NVIDIA only.
        """
        if not stream:
            nvidia_model = pin_nvidia_model or self._next_nvidia_model()
            try:
                kwargs = dict(
                    model=nvidia_model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    extra_body=self._nvidia_extra_body(),
                )
                if response_format is not None:
                    kwargs["response_format"] = response_format
                with observation(
                    "generate-completion",
                    as_type="generation",
                    input=messages,
                    model=nvidia_model,
                    metadata={"provider": "nvidia-nim"},
                    model_parameters={
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    },
                ) as gen:
                    result = self._nvidia.chat.completions.create(**kwargs)
                    _record_completion(gen, result)
                    return result
            except Exception as e:
                log.warning(
                    "nvidia_generation_failed",
                    error=str(e)[:200],
                    fallback="hf_together",
                    model=model,
                )
                return self._hf_fallback_completion(
                    model, messages, max_tokens, temperature
                )

        return self._stream_with_fallback(model, messages, max_tokens, temperature)

    # ── HF "together" fallback ────────────────────────────────────────────────
    # The langfuse.openai wrapper only instruments the NVIDIA (OpenAI-SDK) path. Without
    # these, a NIM outage would make every generation vanish from Langfuse exactly when
    # the traces matter most, so the fallback is traced by hand.

    def _hf_fallback_completion(
        self, model: str, messages: list[dict], max_tokens: int, temperature: float
    ):
        """Non-streaming HF fallback, recorded as a `generation` observation."""
        with observation(
            "generate-completion-fallback",
            as_type="generation",
            input=messages,
            model=model,
            metadata={"provider": "hf-together", "reason": "nvidia_failed"},
            model_parameters={"max_tokens": max_tokens, "temperature": temperature},
        ) as gen:
            result = self._hf.chat_completion(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            _record_completion(gen, result)
            return result

    def _hf_fallback_stream(
        self, model: str, messages: list[dict], max_tokens: int, temperature: float
    ) -> Iterator:
        """Streaming HF fallback; accumulates chunks so the observation has an output."""
        with observation(
            "generate-completion-fallback",
            as_type="generation",
            input=messages,
            model=model,
            metadata={
                "provider": "hf-together",
                "reason": "nvidia_failed",
                "stream": True,
            },
            model_parameters={"max_tokens": max_tokens, "temperature": temperature},
        ) as gen:
            chunks: list[str] = []
            for chunk in self._hf.chat_completion(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            ):
                try:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        chunks.append(delta)
                except Exception:  # noqa: BLE001
                    pass
                yield chunk
            gen.update(output="".join(chunks))

    def _stream_with_fallback(
        self, model: str, messages: list[dict], max_tokens: int, temperature: float
    ) -> Iterator:
        """Stream from NVIDIA NIM; fall back to HF Together if the first chunk fails."""
        nvidia_model = self._next_nvidia_model()
        try:
            nvidia_stream = self._nvidia.chat.completions.create(
                model=nvidia_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                extra_body=self._nvidia_extra_body(),
            )
            first_chunk = next(nvidia_stream)
        except Exception as e:
            log.warning(
                "nvidia_generation_stream_failed",
                error=str(e)[:200],
                fallback="hf_together",
                model=model,
            )
            return self._hf_fallback_stream(model, messages, max_tokens, temperature)

        def _resume():
            """Re-yield the already-consumed first chunk then continue the NVIDIA stream."""
            with observation(
                "generate-completion",
                as_type="generation",
                input=messages,
                model=nvidia_model,
                metadata={"provider": "nvidia-nim", "stream": True},
                model_parameters={
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            ) as gen:
                chunks: list[str] = []
                for chunk in (first_chunk, *nvidia_stream):
                    try:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            chunks.append(delta)
                    except Exception:  # noqa: BLE001
                        pass
                    yield chunk
                gen.update(output="".join(chunks))

        return _resume()


_client: ResilientGenerationClient | None = None


def get_resilient_generation_client() -> ResilientGenerationClient:
    """Return the module-level singleton ResilientGenerationClient, creating it on first call."""
    global _client
    if _client is None:
        if not settings.NVIDIA_API_KEY:
            log.error(
                "nvidia_api_key_missing",
                msg="NVIDIA_API_KEY not set — generation calls go straight to HF together fallback",
            )
        if not settings.HF_TOKEN:
            log.error(
                "hf_token_missing",
                msg="HF_TOKEN not set — fallback generation calls will fail",
            )
        hf_client = InferenceClient(
            token=settings.HF_TOKEN or None, provider="together"
        )
        nvidia_client = OpenAI(
            base_url=settings.NVIDIA_BASE_URL, api_key=settings.NVIDIA_API_KEY
        )
        _client = ResilientGenerationClient(hf_client, nvidia_client)
    return _client
