"""
Robust JSON extraction for LLM agent steps.

Agents ask the model for a bare JSON object, but models occasionally wrap it in
code fences, prepend a sentence, or emit trailing tokens. ``extract_json`` recovers
the object in those cases instead of letting a single ``json.loads`` failure collapse
the whole turn into a canned error.
"""

from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?", re.IGNORECASE)


def extract_json(raw: str) -> dict | None:
    """Best-effort parse of a JSON object from an LLM response.

    Tries, in order:
      1. Direct ``json.loads`` after stripping markdown code fences.
      2. A balanced-brace scan that pulls the first complete ``{...}`` object out
         of surrounding prose (quote- and escape-aware so braces inside strings
         don't throw off the depth count).

    Returns the parsed dict, or ``None`` if nothing parses to an object.
    """
    if not raw:
        return None

    cleaned = _FENCE_RE.sub("", raw).strip().strip("`").strip()

    # Fast path: the whole string is the JSON object.
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    # Slow path: scan for the first balanced top-level {...}.
    start = cleaned.find("{")
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
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(cleaned[start : i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None
