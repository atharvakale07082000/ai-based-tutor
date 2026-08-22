"""Tests for company-specific interview loops: the bar, round planning, and transitions.

Pure logic only — the round plan, the bar and the status ladder are deliberately free
of I/O so they can be tested without a database or an LLM.
"""

import pytest

from app.agents import loops as loops_mod
from app.agents.bar import (
    DEFAULT_BAR,
    ROUND_KINDS,
    round_bar,
    seniority_bar,
)
from app.agents.loops import (
    LOOP_FAILED,
    LOOP_IN_PROGRESS,
    LOOP_PASSED,
    MAX_ROUNDS,
    MIN_ROUNDS,
    ROUND_AVAILABLE,
    ROUND_FAILED,
    ROUND_LOCKED,
    ROUND_PASSED,
    apply_round_result,
    build_loop,
    is_resolved,
    loop_view,
    normalize_rounds,
)


# ─── The bar ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "seniority,expected",
    [
        ("Junior", 5.5),
        ("junior software engineer", 5.5),
        ("Mid-level", 6.5),
        ("Senior", 7.5),
        ("Staff", 8.0),
        ("Principal Engineer", 8.0),
    ],
)
def test_seniority_bar_maps_known_titles(seniority, expected):
    assert seniority_bar(seniority) == expected


@pytest.mark.parametrize("unknown", ["", None, "   ", "wizard", "rockstar ninja"])
def test_seniority_bar_falls_back_to_default(unknown):
    """An unrecognised seniority must grade like a normal interview, never a staff one."""
    assert seniority_bar(unknown) == DEFAULT_BAR


def test_compound_title_takes_the_highest_bar():
    """ "senior staff" is a staff role — the higher of the two bars must win."""
    assert seniority_bar("senior staff engineer") == 8.0
    assert seniority_bar("Senior Director") == 8.0


def test_round_bar_adjusts_per_kind_and_clamps():
    # A screen is easier than system design at the same seniority.
    assert round_bar("senior", "screen") < round_bar("senior", "system_design")
    # Unknown kinds get no adjustment rather than an exception.
    assert round_bar("senior", "not_a_round") == seniority_bar("senior")
    # Clamped: the easiest possible combination never drops below the floor.
    assert round_bar("intern", "screen") >= 4.0
    assert round_bar("principal", "system_design") <= 9.0


# ─── Round planning ───────────────────────────────────────────────────────────

SKILLS = ["Python", "SQL", "Kubernetes", "System Design"]


def test_normalize_rounds_accepts_a_valid_plan():
    raw = [
        {"kind": "screen", "focus_skills": ["Python"]},
        {"kind": "coding", "focus_skills": ["Python", "SQL"]},
    ]
    rounds = normalize_rounds(raw, SKILLS, "senior")

    assert [r["kind"] for r in rounds] == ["screen", "coding"]
    assert rounds[0]["status"] == ROUND_AVAILABLE  # first round is playable
    assert rounds[1]["status"] == ROUND_LOCKED  # the rest are not
    assert rounds[1]["focus_skills"] == ["Python", "SQL"]
    # Bars come from the seniority, per kind.
    assert rounds[0]["bar"] == round_bar("senior", "screen")
    assert rounds[1]["bar"] == round_bar("senior", "coding")
    # Each round carries its own question budget.
    assert rounds[0]["max_questions"] != rounds[1]["max_questions"]


def test_normalize_rounds_drops_unknown_kinds_and_duplicates():
    raw = [
        {"kind": "screen", "focus_skills": []},
        {"kind": "screen", "focus_skills": []},  # duplicate
        {"kind": "vibes_check", "focus_skills": []},  # not a real kind
        {"kind": "coding", "focus_skills": []},
    ]
    rounds = normalize_rounds(raw, SKILLS, "mid")
    assert [r["kind"] for r in rounds] == ["screen", "coding"]


def test_normalize_rounds_constrains_focus_skills_to_the_jd():
    """A hallucinated skill must never become the subject of a round."""
    raw = [
        {"kind": "screen", "focus_skills": ["Python", "Blockchain", "Telepathy"]},
        {"kind": "coding", "focus_skills": ["sql"]},  # case-insensitive match
    ]
    rounds = normalize_rounds(raw, SKILLS, "mid")
    assert rounds[0]["focus_skills"] == ["Python"]
    assert rounds[1]["focus_skills"] == ["SQL"]  # normalised to the JD's own casing


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "not a list",
        [],
        [{"kind": "screen"}],  # too few
        [{"kind": "nope"}, {"kind": "also_nope"}],  # none valid
        ["screen", "coding"],  # right length, wrong element type
    ],
)
def test_normalize_rounds_falls_back_when_unusable(raw):
    rounds = normalize_rounds(raw, SKILLS, "mid")
    assert MIN_ROUNDS <= len(rounds) <= MAX_ROUNDS
    assert all(r["kind"] in ROUND_KINDS for r in rounds)
    assert rounds[0]["status"] == ROUND_AVAILABLE


def test_normalize_rounds_gives_every_round_a_subject():
    """A round the model left empty falls back to the JD's skills, never nothing."""
    rounds = normalize_rounds(
        [{"kind": "screen", "focus_skills": []}, {"kind": "coding"}], SKILLS, "mid"
    )
    assert all(r["focus_skills"] for r in rounds)


# ─── Status transitions ───────────────────────────────────────────────────────


def _loop(seniority="senior"):
    rounds = normalize_rounds(
        [
            {"kind": "screen", "focus_skills": ["Python"]},
            {"kind": "coding", "focus_skills": ["Python"]},
        ],
        SKILLS,
        seniority,
    )
    return build_loop(
        learner_id="L1",
        job={
            "id": "J1",
            "company": "Acme",
            "role": "Backend Engineer",
            "seniority": seniority,
            "required_skills": SKILLS,
        },
        rounds=rounds,
        company_signals={"process_summary": "s", "sources": []},
    )


def test_clearing_a_round_unlocks_the_next():
    loop = _loop()
    bar = loop["rounds"][0]["bar"]

    apply_round_result(loop, loop["rounds"][0]["key"], bar + 1)

    assert loop["rounds"][0]["status"] == ROUND_PASSED
    assert loop["rounds"][1]["status"] == ROUND_AVAILABLE
    assert loop["status"] == LOOP_IN_PROGRESS  # not done until every round resolves


def test_failing_a_round_still_unlocks_the_next():
    """This is practice, not a gate — a weak screen must not end the loop."""
    loop = _loop()
    apply_round_result(loop, loop["rounds"][0]["key"], 0.0)

    assert loop["rounds"][0]["status"] == ROUND_FAILED
    assert loop["rounds"][1]["status"] == ROUND_AVAILABLE
    assert loop["status"] == LOOP_IN_PROGRESS


def test_loop_passes_only_when_every_round_clears_its_bar():
    loop = _loop()
    for rnd in list(loop["rounds"]):
        apply_round_result(loop, rnd["key"], rnd["bar"] + 0.5)

    assert loop["status"] == LOOP_PASSED
    assert loop["completed_at"] is not None
    assert is_resolved(loop)


def test_one_failed_round_fails_the_loop():
    loop = _loop()
    apply_round_result(loop, loop["rounds"][0]["key"], loop["rounds"][0]["bar"] + 1)
    apply_round_result(loop, loop["rounds"][1]["key"], 1.0)

    assert loop["status"] == LOOP_FAILED
    assert is_resolved(loop)


def test_a_score_exactly_on_the_bar_passes():
    loop = _loop()
    rnd = loop["rounds"][0]
    apply_round_result(loop, rnd["key"], rnd["bar"])
    assert rnd["status"] == ROUND_PASSED


def test_loop_view_hides_scraped_company_text():
    """Third-party scraped content is untrusted and has no business being rendered."""
    loop = _loop()
    loop["company_signals"]["raw_results"] = "<script>alert(1)</script>"

    view = loop_view(loop)

    assert "raw_results" not in view
    assert "company_signals" not in view
    assert view["process_summary"] == "s"  # the vetted summary still surfaces
    assert view["rounds"][0]["bar"] == loop["rounds"][0]["bar"]


# ─── Pins ─────────────────────────────────────────────────────────────────────


def test_pass_threshold_lives_only_in_the_bar_module():
    """Nothing may re-hardcode the pass mark; agents/bar.py is the single home."""
    import inspect

    from app.agents import interview_scorer

    source = inspect.getsource(interview_scorer)
    assert ">= 6.0" not in source
    assert "6.0" not in source.replace("DEFAULT_BAR", "")


def test_agent_tools_use_the_canonical_proficiency_field():
    """db_tools once wrote topic_proficiency, which no router ever read."""
    import inspect

    from app.tools.implementations import db_tools

    source = inspect.getsource(db_tools)
    # Every mention must be the canonical field, never the stray one.
    assert source.count("topic_proficiency") == source.count("topic_proficiency_map")


def test_round_kinds_have_rubrics_and_budgets():
    """Every kind the planner can emit must have a rubric skill and a question budget."""
    from app.agents.interview_agent import _ROUND_RUBRICS
    from app.agents.skills import load_all_skills

    skills = load_all_skills()
    for kind in ROUND_KINDS:
        assert kind in _ROUND_RUBRICS, f"{kind} has no rubric skill"
        assert _ROUND_RUBRICS[kind] in skills, f"{kind}'s SKILL.md is missing"
        assert kind in loops_mod._ROUND_BUDGETS, f"{kind} has no question budget"
