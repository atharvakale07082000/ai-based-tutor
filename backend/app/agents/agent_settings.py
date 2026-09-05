"""
Agent settings — the knobs that change how agents behave, resolved per learner.

Pure resolution logic here (``resolve``); the I/O lives in ``routers/admin.py`` and the
learner document. Same split as ``bar.py`` / ``progress.py`` / ``learner_context.py``.

**Every setting in this module must have a real consumer.** The panel this replaces
shipped three sliders — ``quiz_frequency``, ``difficulty_ceiling`` and
``escalation_threshold`` — stored in a module-level dict that no agent ever read, that
reset on every restart and diverged between instances, behind a button that toasted
"Agent config updated". Two of the three named systems that do not exist in this
codebase (there is no nudging scheduler and nothing has any notion of escalation), so
they are gone rather than wired to something invented. Adding a setting here means
adding the code that reads it in the same change.

Resolution order, lowest to highest: **code default -> org setting -> learner override.**
A learner's own preference should win over an org-wide default, and an org default should
win over whatever this file happens to ship.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from app.agents.progress import BLOOM_LEVELS

# Field name -> (default, minimum, maximum). Values outside the range are clamped rather
# than rejected: a bad number in the database must not break every chat turn.
_SPEC: dict[str, tuple[float, float, float]] = {
    # Ceiling on how cognitively demanding generated questions may get, as a fraction of
    # the Bloom ladder. 1.0 allows "create"; 0.5 caps around "apply". Consumed by
    # `cap_bloom` below, which quiz generation applies on top of `bloom_for_elo`.
    "difficulty_ceiling": (1.0, 0.0, 1.0),
}


@dataclass(frozen=True)
class AgentSettings:
    difficulty_ceiling: float = 1.0

    def cap_bloom(self, level: str) -> str:
        """Clamp a Bloom level to this learner's ceiling.

        Applied *after* ``bloom_for_elo``: proficiency picks the level, the ceiling caps
        it. An unknown level is returned untouched — this is a limiter, not a validator.
        """
        if level not in BLOOM_LEVELS:
            return level
        top = round(self.difficulty_ceiling * (len(BLOOM_LEVELS) - 1))
        return BLOOM_LEVELS[min(BLOOM_LEVELS.index(level), max(0, top))]


DEFAULTS = AgentSettings()


def _coerce(name: str, value: object) -> float | None:
    """A usable number for ``name``, clamped to its range, or None if unusable."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    _, low, high = _SPEC[name]
    return max(low, min(high, float(value)))


def resolve(
    org: dict | None = None,
    learner: dict | None = None,
) -> AgentSettings:
    """Layer code defaults <- org settings <- this learner's overrides.

    Both inputs are raw dicts straight from Mongo, so both are untrusted: unknown keys
    are ignored and unusable values fall through to the layer below.
    """
    values = {f.name: getattr(DEFAULTS, f.name) for f in fields(AgentSettings)}
    for source in (org or {}, (learner or {}).get("agent_settings") or {}):
        if not isinstance(source, dict):
            continue
        for name in values:
            if name in source and (coerced := _coerce(name, source[name])) is not None:
                values[name] = coerced
    return AgentSettings(**values)


def sanitize(patch: dict | None) -> dict:
    """The writable subset of a settings patch, clamped. Used by the admin endpoint."""
    out: dict[str, float] = {}
    for name in _SPEC:
        if patch and name in patch and (v := _coerce(name, patch[name])) is not None:
            out[name] = v
    return out
