"""
LearnerContext — the learner briefing injected into every specialist's system prompt.

Pure tests: no Mongo, no model. What a model *does* with the briefing can't be asserted
here (see the plan's model-facing verification), but everything about what the briefing
*says* is deterministic and pinned below.
"""

from __future__ import annotations

import pytest

from app.agents.learner_context import LearnerContext
from app.agents.progress import MASTERY_ELO, bloom_for_elo

NEW_LEARNER = {"id": "L1", "name": "Mira", "topic_proficiency_map": {}}

SENIOR = {
    "id": "L2",
    "name": "Ada",
    "target_role": "Staff Engineer",
    "current_role": "Senior Engineer",
    "years_of_experience": 8,
    "goal_vector": ["distributed systems", "system design"],
    "learning_style": "reading",
    "session_cadence": {"pace": "aggressive"},
    "xp": 4200,
    "streak": 12,
    "topic_proficiency_map": {
        "Concurrency": 880.0,
        "Databases": 760.0,
        "System Design": 720.0,
        "Kubernetes": 300.0,
        "Rust": 220.0,
    },
}


class TestFromDoc:
    def test_maps_the_profile_fields_that_used_to_be_dropped(self):
        ctx = LearnerContext.from_doc(SENIOR)
        assert ctx.target_role == "Staff Engineer"
        assert ctx.current_role == "Senior Engineer"
        assert ctx.years_experience == 8
        assert ctx.goals == ("distributed systems", "system design")
        assert ctx.pace == "aggressive"
        assert ctx.style == "reading"
        assert ctx.tracked_topics == 5

    def test_missing_doc_is_tolerated(self):
        assert LearnerContext.from_doc(None).render() == ""
        assert LearnerContext.from_doc({}).render() == ""

    def test_strengths_are_mastery_and_gaps_are_weak_topics(self):
        ctx = LearnerContext.from_doc(SENIOR)
        assert [t for t, _ in ctx.strengths] == [
            "Concurrency",
            "Databases",
            "System Design",
        ]
        assert all(e >= MASTERY_ELO for _, e in ctx.strengths)
        assert [t for t, _ in ctx.gaps] == ["Rust", "Kubernetes"]

    def test_non_numeric_elo_is_ignored_not_crashed_on(self):
        ctx = LearnerContext.from_doc(
            {"topic_proficiency_map": {"Good": 800.0, "Bad": None, "Worse": "high"}}
        )
        assert ctx.tracked_topics == 1
        assert [t for t, _ in ctx.strengths] == ["Good"]

    def test_focus_topic_drives_the_level(self):
        ctx = LearnerContext.from_doc(SENIOR, current_topic="Kubernetes")
        assert ctx.focus_elo == 300.0
        assert ctx.level == bloom_for_elo(300.0)

    def test_level_is_empty_without_a_score(self):
        """Unknown must read as unknown — never as the bottom rung."""
        assert LearnerContext.from_doc(SENIOR).level == ""
        assert LearnerContext.from_doc(SENIOR, current_topic="Haskell").level == ""


class TestRender:
    def test_a_brand_new_learner_gets_no_briefing(self):
        """Silence beats a block that says 'level: unknown, gaps: none'."""
        assert LearnerContext.from_doc(NEW_LEARNER).render() == ""

    def test_a_name_alone_is_not_signal(self):
        ctx = LearnerContext.from_doc({"id": "x", "name": "Sam"})
        assert not ctx.has_signal
        assert ctx.render() == ""

    def test_briefing_carries_facts_and_directives(self):
        out = LearnerContext.from_doc(SENIOR, current_topic="Kubernetes").render()
        assert "Staff Engineer" in out
        assert "8 yrs experience" in out
        assert "Kubernetes" in out
        # Directives, not just facts — facts alone don't change behaviour.
        assert "## How to pitch this answer" in out
        assert "plain language" in out  # Elo 300 -> early on this topic

    def test_strong_topic_gets_depth_not_basics(self):
        out = LearnerContext.from_doc(SENIOR, current_topic="Concurrency").render()
        assert "skip the basics" in out
        assert "plain language" not in out

    def test_never_leaks_the_briefing_or_the_numbers_to_the_learner(self):
        out = LearnerContext.from_doc(SENIOR, current_topic="Rust").render()
        assert "Never mention" in out

    @pytest.mark.parametrize("topics", [10, 108, 500])
    def test_output_stays_bounded_as_history_grows(self, topics):
        """The old JSON blob grew with the learner; this must not."""
        doc = dict(SENIOR)
        doc["topic_proficiency_map"] = {
            f"Topic {i}": float(i % 1000) for i in range(topics)
        }
        out = LearnerContext.from_doc(doc, current_topic="Topic 5").render()
        assert len(out) < 1200, f"briefing grew to {len(out)} chars at {topics} topics"
        # At most three of each are ever named.
        assert out.count("Topic ") <= 7

    def test_style_only_affects_format_never_difficulty(self):
        """learning_style is self-reported; it must not override the Elo evidence."""
        weak = dict(SENIOR, learning_style="visual")
        out = LearnerContext.from_doc(weak, current_topic="Rust").render()
        assert "diagram-in-words" in out
        # The difficulty directive still comes from the score, not the style.
        assert "plain language" in out

    def test_unknown_pace_and_style_are_skipped_silently(self):
        doc = dict(
            SENIOR, learning_style="telepathic", session_cadence={"pace": "warp"}
        )
        out = LearnerContext.from_doc(doc, current_topic="Rust").render()
        assert "telepathic" not in out and "warp" not in out


class TestSystemPromptIntegration:
    def test_briefing_is_appended_last_so_the_shared_prefix_is_cacheable(self):
        """
        Everything above the briefing must be byte-identical across learners, or the
        provider cannot KV-cache it. This is the property the old design lost by putting
        learner data in the user turn.
        """
        from app.agents.specialists import SPECIALISTS, _system_prompt

        spec = SPECIALISTS["doubt"]
        base = _system_prompt(spec)
        a = _system_prompt(spec, LearnerContext.from_doc(SENIOR, current_topic="Rust"))
        b = _system_prompt(spec, LearnerContext.from_doc(NEW_LEARNER))

        assert a.startswith(base), "learner briefing must come after the stable blocks"
        assert b == base, "a learner with no signal must not change the prompt at all"
        assert a != b
