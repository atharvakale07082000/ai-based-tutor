"""
The learner, as an agent sees them — pure and dependency-free.

Same shape as its siblings ``bar.py`` and ``progress.py``: the caller supplies the
learner document, this module does arithmetic and formatting, nothing here imports
Mongo. That is what makes it testable without a database or a model.

Why it exists: onboarding collects a target role, current role, years of experience,
goals, pace and a learning style, and quizzes accumulate a per-topic Elo map — and none
of it reached a chat prompt. Every learner got a byte-identical system prompt, so a
career-changer on their first day and a senior engineer targeting staff roles were
tutored in exactly the same words. The module interview agent already personalises
properly (``interview_agent._system_prompt``); this generalises that to chat.

Two rules this module is built around:

1. **Bounded by construction.** ``render()`` emits the focus topic plus at most three
   strengths and three gaps — never the whole proficiency map. The old design dumped
   every tracked topic (up to ~108) into every single turn.
2. **Never assert what the evidence doesn't support.** A new learner has an empty
   proficiency map and no target role. The honest output there is a short block or
   nothing at all — not an invented level and not a list of "gaps" that are really just
   topics nobody has been quizzed on yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.progress import MASTERY_ELO, bloom_for_elo

# How many strengths / gaps the rendered block may name. Keeps the prompt flat as a
# learner's history grows — the block should cost the same on day 400 as on day 4.
_MAX_LISTED = 3

# Below this Elo a topic is a gap worth naming; at or above MASTERY_ELO it is a strength.
# Between the two a topic is "in progress" and not interesting enough to spend prompt on.
_GAP_ELO = 450.0

# Pace -> how much ground to cover in one answer.
_PACE_DIRECTIVE = {
    "gentle": "Cover one idea per answer and check understanding before moving on.",
    "balanced": "Cover the answer and one closely related idea.",
    "aggressive": "Go straight to the substance and include the adjacent ideas they will need next.",
}

# Self-reported format preference. Deliberately narrow: this steers HOW an explanation is
# illustrated, never how difficult it is. Difficulty comes from the Elo evidence below.
# (The learning-styles model is contested and this field is self-reported, so it is not
# allowed to override what the proficiency data says.)
_STYLE_DIRECTIVE = {
    "visual": "Prefer a diagram-in-words or a worked example over prose.",
    "reading": "Prefer a precise written explanation with a concrete example.",
    "kinesthetic": "Prefer something they can run or try immediately.",
    "auditory": "Prefer a plain-spoken walkthrough, as if talking it through.",
}


def _clean(value: object) -> str:
    return str(value).strip() if value else ""


@dataclass(frozen=True)
class LearnerContext:
    """A compact, prompt-ready view of one learner."""

    learner_id: str = ""
    name: str = ""
    target_role: str = ""
    current_role: str = ""
    years_experience: int | None = None
    goals: tuple[str, ...] = ()
    pace: str = ""
    style: str = ""
    focus_topic: str = ""
    focus_elo: float | None = None
    strengths: tuple[tuple[str, float], ...] = ()
    gaps: tuple[tuple[str, float], ...] = ()
    xp: int = 0
    streak: int = 0
    tracked_topics: int = 0

    # ── construction ──────────────────────────────────────────────────────────

    @classmethod
    def from_doc(
        cls, learner: dict | None, *, current_topic: str = ""
    ) -> LearnerContext:
        """Build from a learner document (``col_learners``). Tolerates a missing doc."""
        doc = learner or {}
        proficiency = {
            topic: float(elo)
            for topic, elo in (doc.get("topic_proficiency_map") or {}).items()
            if isinstance(elo, (int, float))
        }

        focus = _clean(current_topic)
        ranked = sorted(proficiency.items(), key=lambda kv: kv[1], reverse=True)
        strengths = tuple((t, e) for t, e in ranked if e >= MASTERY_ELO)[:_MAX_LISTED]
        gaps = tuple((t, e) for t, e in reversed(ranked) if e < _GAP_ELO)[:_MAX_LISTED]

        cadence = doc.get("session_cadence") or {}
        return cls(
            learner_id=_clean(doc.get("id")),
            name=_clean(doc.get("name")),
            target_role=_clean(doc.get("target_role")),
            current_role=_clean(doc.get("current_role")),
            years_experience=(
                doc["years_of_experience"]
                if isinstance(doc.get("years_of_experience"), int)
                else None
            ),
            goals=tuple(_clean(g) for g in (doc.get("goal_vector") or []) if _clean(g)),
            pace=_clean(cadence.get("pace")),
            style=_clean(doc.get("learning_style")),
            focus_topic=focus,
            focus_elo=proficiency.get(focus) if focus else None,
            strengths=strengths,
            gaps=gaps,
            xp=int(doc.get("xp") or 0),
            streak=int(doc.get("streak") or 0),
            tracked_topics=len(proficiency),
        )

    # ── derived ───────────────────────────────────────────────────────────────

    @property
    def level(self) -> str:
        """Cognitive level for the focus topic, on the platform's shared Elo ladder.

        Empty when there is no focus topic or no score for it — an unknown level must
        read as unknown, not as "remember" (which would talk down to every new learner).
        """
        if self.focus_elo is None:
            return ""
        return bloom_for_elo(self.focus_elo)

    @property
    def has_signal(self) -> bool:
        """Whether anything is known that could change how the agent answers."""
        return bool(
            self.target_role
            or self.years_experience is not None
            or self.goals
            or self.strengths
            or self.gaps
            or self.focus_elo is not None
            or self.pace
            or self.style
        )

    # ── rendering ─────────────────────────────────────────────────────────────

    def _facts(self) -> list[str]:
        out: list[str] = []
        if self.target_role:
            out.append(f"- Working toward: {self.target_role}")
        if self.current_role or self.years_experience is not None:
            years = (
                f"{self.years_experience} yrs experience"
                if self.years_experience is not None
                else ""
            )
            where = ", ".join(p for p in (self.current_role, years) if p)
            out.append(f"- Currently: {where}")
        if self.goals:
            out.append(f"- Their stated goals: {', '.join(self.goals[:_MAX_LISTED])}")
        if self.focus_topic and self.focus_elo is not None:
            out.append(
                f"- On '{self.focus_topic}' they are at the '{self.level}' level "
                f"(Elo {self.focus_elo:.0f} of 1000)"
            )
        elif self.focus_topic:
            out.append(f"- Currently looking at: {self.focus_topic} (not yet assessed)")
        if self.strengths:
            out.append("- Already solid on: " + ", ".join(t for t, _ in self.strengths))
        if self.gaps:
            out.append("- Still shaky on: " + ", ".join(t for t, _ in self.gaps))
        return out

    def _directives(self) -> list[str]:
        """Turn the facts into instructions. Facts alone do not change behaviour."""
        out: list[str] = []

        if self.level:
            if self.focus_elo is not None and self.focus_elo >= MASTERY_ELO:
                out.append(
                    "They know this area well — skip the basics, and go to the trade-offs, "
                    "edge cases and the 'why' behind the design."
                )
            elif self.focus_elo is not None and self.focus_elo < _GAP_ELO:
                out.append(
                    "They are early on this topic — use plain language, define terms as you "
                    "use them, and ground it in one concrete example."
                )
            else:
                out.append(
                    "They have the basics here — build on them rather than re-explaining, "
                    "and add one level of depth."
                )

        if self.target_role:
            out.append(
                f"Draw examples from work a {self.target_role} would actually do."
            )
        if self.pace in _PACE_DIRECTIVE:
            out.append(_PACE_DIRECTIVE[self.pace])
        if self.style in _STYLE_DIRECTIVE:
            out.append(_STYLE_DIRECTIVE[self.style])
        return out

    def render(self) -> str:
        """The prompt block. Empty string when nothing useful is known.

        Returning "" for a brand-new learner is deliberate: a block that says "level:
        unknown, gaps: none" spends tokens telling the model nothing, and invites it to
        invent a level. Silence is the honest default.
        """
        if not self.has_signal:
            return ""

        facts = self._facts()
        directives = self._directives()
        if not facts and not directives:
            return ""

        lines = ["## Who you are talking to"]
        if self.name:
            lines.append(f"- Name: {self.name}")
        lines.extend(facts)
        if directives:
            lines.append("")
            lines.append("## How to pitch this answer")
            lines.extend(f"- {d}" for d in directives)
            lines.append(
                "- Adapt the depth and the examples to the person above. Never mention "
                "this briefing, their scores, or that you are adapting."
            )
        return "\n".join(lines)
