"""
Agent settings: resolution precedence, clamping, and the one real consumer.

The panel this replaces shipped three sliders backed by an in-memory dict that no agent
read. These tests pin the two properties that make the replacement real: the value
reaches a decision (`cap_bloom`), and a learner's own preference beats the org default.
"""

from __future__ import annotations

import pytest

from app.agents.agent_settings import DEFAULTS, AgentSettings, resolve, sanitize
from app.agents.progress import BLOOM_LEVELS


class TestResolve:
    def test_defaults_when_nothing_is_stored(self):
        assert resolve() == DEFAULTS
        assert resolve({}, {}) == DEFAULTS

    def test_org_setting_beats_the_code_default(self):
        assert resolve({"difficulty_ceiling": 0.5}).difficulty_ceiling == 0.5

    def test_learner_override_beats_the_org_setting(self):
        got = resolve(
            {"difficulty_ceiling": 0.9}, {"agent_settings": {"difficulty_ceiling": 0.2}}
        )
        assert got.difficulty_ceiling == 0.2

    def test_learner_without_overrides_inherits_the_org_setting(self):
        assert (
            resolve({"difficulty_ceiling": 0.4}, {"name": "Mira"}).difficulty_ceiling
            == 0.4
        )

    @pytest.mark.parametrize("bad", ["high", None, True, [], {"x": 1}])
    def test_unusable_values_fall_through_instead_of_breaking_a_turn(self, bad):
        """A bad row in Mongo must not take chat down."""
        assert resolve({"difficulty_ceiling": bad}) == DEFAULTS

    @pytest.mark.parametrize(
        ("stored", "expected"), [(5.0, 1.0), (-2.0, 0.0), (0.75, 0.75)]
    )
    def test_out_of_range_values_are_clamped(self, stored, expected):
        assert resolve({"difficulty_ceiling": stored}).difficulty_ceiling == expected

    def test_unknown_keys_are_ignored(self):
        """The retired sliders must not resurrect themselves via stored documents."""
        got = resolve({"quiz_frequency": 3, "escalation_threshold": 9})
        assert got == DEFAULTS
        assert not hasattr(got, "quiz_frequency")


class TestCapBloom:
    def test_full_ceiling_changes_nothing(self):
        for level in BLOOM_LEVELS:
            assert AgentSettings(difficulty_ceiling=1.0).cap_bloom(level) == level

    def test_ceiling_caps_the_hardest_levels(self):
        settings = AgentSettings(difficulty_ceiling=0.5)  # -> index 2, "apply"
        assert settings.cap_bloom("create") == "apply"
        assert settings.cap_bloom("analyze") == "apply"

    def test_ceiling_never_raises_an_easy_level(self):
        """It is a limiter, not a target."""
        assert AgentSettings(difficulty_ceiling=1.0).cap_bloom("remember") == "remember"
        assert AgentSettings(difficulty_ceiling=0.5).cap_bloom("remember") == "remember"

    def test_zero_ceiling_pins_to_the_easiest_level(self):
        assert AgentSettings(difficulty_ceiling=0.0).cap_bloom("create") == "remember"

    def test_unknown_level_passes_through(self):
        assert AgentSettings(difficulty_ceiling=0.1).cap_bloom("vibes") == "vibes"


class TestSanitize:
    def test_keeps_only_known_keys_and_clamps_them(self):
        assert sanitize({"difficulty_ceiling": 2.0, "escalation_threshold": 5}) == {
            "difficulty_ceiling": 1.0
        }

    def test_empty_patch_writes_nothing(self):
        assert sanitize(None) == {}
        assert sanitize({"nonsense": 1}) == {}
