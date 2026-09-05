"""
Pin the numbers the landing page states as fact to the code they describe.

The landing page claimed "32 sub-skills rated" while the curriculum topic graph held
108, and nothing connected the two, so nothing caught it. These tests fail when the
curriculum changes and the marketing copy doesn't — which is the only thing that keeps
the claim true over time.

Deliberately deterministic: no LLM, no network, no DB.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_CURRICULUM = _REPO / "backend" / "app" / "prompts" / "curriculum.yaml"
_FACTS = _REPO / "frontend" / "src" / "lib" / "platformFacts.ts"


def _topic_graph() -> dict[str, list]:
    graph = yaml.safe_load(_CURRICULUM.read_text())["topic_graph"]
    assert isinstance(graph, dict) and graph, "curriculum.yaml lost its topic_graph"
    return graph


def _declared(name: str) -> int:
    """Read `export const <name> = <int>` out of the frontend facts module."""
    match = re.search(rf"^export const {name} = (\d+)$", _FACTS.read_text(), re.M)
    assert match, f"{name} is not declared in {_FACTS.name}"
    return int(match.group(1))


def test_facts_module_exists() -> None:
    """The landing page must source its numbers from one pinned module."""
    assert _FACTS.is_file(), (
        f"{_FACTS} is missing — marketing numbers belong there, not inline in a page, "
        "so this test can pin them."
    )


def test_sub_skills_rated_matches_the_curriculum() -> None:
    actual = sum(len(topics) for topics in _topic_graph().values())
    assert _declared("SUB_SKILLS_RATED") == actual, (
        f"The landing page claims {_declared('SUB_SKILLS_RATED')} sub-skills but the "
        f"topic graph holds {actual}. Update SUB_SKILLS_RATED in platformFacts.ts "
        "(or stop putting a number on it)."
    )


def test_curriculum_domains_matches_the_curriculum() -> None:
    actual = len(_topic_graph())
    assert _declared("CURRICULUM_DOMAINS") == actual, (
        f"The landing page claims {_declared('CURRICULUM_DOMAINS')} domains but the "
        f"topic graph holds {actual}."
    )


@pytest.mark.parametrize("stale", ["32 sub-skills", "Rates 32 sub-skills"])
def test_the_old_hardcoded_count_is_gone(stale: str) -> None:
    """Guard the specific wrong number from coming back by copy-paste."""
    landing = (_REPO / "frontend" / "src" / "pages" / "LandingPage.tsx").read_text()
    assert stale not in landing, f"{stale!r} is back in LandingPage.tsx"
