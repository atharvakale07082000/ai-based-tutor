"""
Robust JSON extraction for LLM agent steps.

Agents ask the model for a bare JSON value, but models occasionally wrap it in
code fences, prepend a sentence, or emit trailing tokens. ``extract_json`` and
``extract_json_array`` recover the value in those cases instead of letting a single
``json.loads`` failure collapse the whole turn into a canned error.

Prefer these over a hand-rolled ``re.search(r"\\{.*\\}")`` + ``json.loads`` pair: a
greedy regex spans from the first brace to the *last* one in the response, so any
trailing prose containing a brace silently corrupts the parse, and an unguarded
``json.loads`` raises where these return ``None``.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Ask the provider to constrain the response to JSON. Passed to NVIDIA NIM only —
# generation_client drops it on the HF-Together fallback, so the "Return ONLY the JSON"
# instruction in prompts/*.yaml stays load-bearing and must not be deleted.
# Only for prompts whose top level is an OBJECT: json_object mode does not admit a
# top-level array, so the array-returning prompts (analyze_answers, design_rounds,
# flashcard generate, trend distill) deliberately do not pass it.
JSON_OBJECT: dict = {"type": "json_object"}

_FENCE_RE = re.compile(r"```(?:json)?", re.IGNORECASE)


def _clean(raw: str) -> str:
    """Strip markdown code fences and stray backticks from a model response."""
    return _FENCE_RE.sub("", raw).strip().strip("`").strip()


def _first_balanced(cleaned: str, opener: str, closer: str) -> str | None:
    """Return the first balanced ``opener…closer`` span, or None.

    Quote- and escape-aware, so braces/brackets inside string literals don't throw
    off the depth count.
    """
    start = cleaned.find(opener)
    if start == -1:
        return None

    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(cleaned)):
        c = cleaned[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return cleaned[start : i + 1]
    return None


def _extract(raw: str, opener: str, closer: str, want: type) -> Any | None:
    """Parse the first JSON value of type ``want`` out of a model response."""
    if not raw:
        return None

    cleaned = _clean(raw)

    # Fast path: the whole string is the JSON value.
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, want) else None
    except json.JSONDecodeError:
        pass

    # Slow path: pull the first balanced span out of the surrounding prose.
    span = _first_balanced(cleaned, opener, closer)
    if span is None:
        return None
    try:
        value = json.loads(span)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, want) else None


def extract_json(raw: str) -> dict | None:
    """Best-effort parse of a JSON **object** from an LLM response.

    Returns the parsed dict, or ``None`` if nothing parses to an object.
    """
    return _extract(raw, "{", "}", dict)


def extract_json_array(raw: str) -> list | None:
    """Best-effort parse of a JSON **array** from an LLM response.

    Returns the parsed list, or ``None`` if nothing parses to an array.
    """
    return _extract(raw, "[", "]", list)
