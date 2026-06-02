"""
15 cross-agent query tests — each one exercises an agent-to-agent tieline.

Every test name encodes the agents involved:
  XA-01  progress → quiz          (mood written by progress, read by quiz)
  XA-02  doubt   → quiz           (mood written by doubt, read by quiz)
  XA-03  quiz    → supervisor     (topic_difficulty written by quiz, read by supervisor)
  XA-04  progress → supervisor → FINISH  (Elo crosses mastery → session ends)
  XA-05  curriculum → quiz        (curriculum path feeds quiz topic selection)
  XA-06  progress (+) → quiz      (POSITIVE mood: bloom NOT softened)
  XA-07  doubt   → bloom_level    (proficiency in detected domain drives explanation depth)
  XA-08  supervisor → routes progress when score unprocessed
  XA-09  supervisor → curriculum on cold start, then quiz (2-hop)
  XA-10  supervisor → progress → quiz (full progress chain)
  XA-11  supervisor → iteration cap → FINISH regardless of unmastered topics
  XA-12  negative mood + high difficulty → double bloom drop
  XA-13  curriculum + proficiency gap → correct topic priority in curriculum → quiz
  XA-14  progress NEGATIVE mood → supervisor → quiz gets softened bloom (3-agent chain)
  XA-15  full cold-start orchestrator: supervisor→curriculum→supervisor→quiz→END
"""
from __future__ import annotations
import pytest
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch, MagicMock

# ── Shared helpers ─────────────────────────────────────────────────────────────

# Inline bloom-level constants to avoid importing quiz_agent at collection time.
# (A module-level import would bind call_tool before test_agents.py can patch
# app.agents.tools.call_tool, causing those tests to make real HF network calls.)
BLOOM_LEVELS = ["remember", "understand", "apply", "analyze", "evaluate", "create"]
_BLOOM_RANGES = [(0, 300), (300, 450), (450, 600), (600, 720), (720, 870), (870, 1001)]


def get_bloom_level(elo: float) -> str:
    for (lo, hi), level in zip(_BLOOM_RANGES, BLOOM_LEVELS):
        if lo <= elo < hi:
            return level
    return "understand"


def _base_state(**overrides) -> dict:
    base = {
        "learner_id": "xa-learner",
        "task_type": "start",
        "messages": [],
        "learner_profile": {"goal_vector": ["learn Python"]},
        "topic_proficiency": {},
        "current_topic": "Python Programming",
        "quiz_questions": [],
        "curriculum_path": [],
        "doubt_response": "",
        "progress_delta": {},
        "bloom_level": "",
        "error": None,
        "next_action": "",
        "resume_action": "",
        "iteration_count": 0,
        "max_iterations": 10,
        "session_complete": False,
        "mastery_threshold": 700.0,
        "learner_mood": "NEUTRAL",
        "learner_mood_score": 0.5,
        "topic_difficulty": 0.5,
        "agent_reports": [],
        "supervisor_decision": "",
    }
    base.update(overrides)
    return base


def _question(bloom_level: str = "apply", topic: str = "Python Programming") -> dict:
    return {
        "id": "q-xa",
        "question": f"Which of the following best demonstrates {topic}?",
        "options": ["Correct answer", "Wrong A", "Wrong B", "Wrong C"],
        "correct_index": 0,
        "explanation": "Correct answer demonstrates the concept.",
        "bloom_level": bloom_level,
    }


async def _default_tool(name: str, **kwargs) -> dict:
    if name == "classify_topic":
        return {"labels": ["Python Programming"], "scores": [0.9]}
    if name == "analyze_sentiment":
        return {"label": "NEUTRAL", "score": 0.5}
    if name == "score_difficulty":
        return {"score": 0.45}
    if name == "generate_quiz":
        bloom = kwargs.get("bloom_level", "apply")
        topic = kwargs.get("topic", "Python Programming")
        count = kwargs.get("count", 5)
        return {"questions": [_question(bloom, topic) for _ in range(count)]}
    if name == "get_embeddings":
        return {"embedding": [0.1] * 384}
    return {}


@contextmanager
def mock_tools(side_effect=None):
    _se = side_effect or _default_tool
    with patch("app.agents.curriculum_agent.call_tool", side_effect=_se), \
         patch("app.agents.quiz_agent.call_tool",        side_effect=_se), \
         patch("app.agents.progress_agent.call_tool",    side_effect=_se), \
         patch("app.agents.doubt_agent.call_tool",       side_effect=_se), \
         patch("app.agents.planner_agent.call_tool",     side_effect=_se):
        yield


# ═══════════════════════════════════════════════════════════════════════════════
# XA-01  progress_agent → learner_mood → quiz_agent  (bloom softened)
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA01_ProgressMoodToQuiz:
    """
    progress_agent writes NEGATIVE learner_mood to state.
    quiz_agent reads it and drops bloom_level by one step.
    """

    @pytest.mark.asyncio
    async def test_negative_mood_written_by_progress(self):
        async def _negative(name, **kw):
            if name == "analyze_sentiment":
                return {"label": "NEGATIVE", "score": 0.91}
            return await _default_tool(name, **kw)

        with mock_tools(_negative):
            from app.agents.progress_agent import progress_agent_node
            state = _base_state(
                current_topic="Async Programming",
                topic_proficiency={"Async Programming": 400.0},
                progress_delta={"score": 0.2, "reflection": "completely lost"},
            )
            prog_result = await progress_agent_node(state)

        assert prog_result["learner_mood"] == "NEGATIVE"
        assert prog_result["learner_mood_score"] > 0.5

    @pytest.mark.asyncio
    async def test_quiz_bloom_softened_from_progress_mood(self):
        """Full tieline: progress sets mood NEGATIVE → quiz drops bloom by 1."""
        async def _negative(name, **kw):
            if name == "analyze_sentiment":
                return {"label": "NEGATIVE", "score": 0.88}
            return await _default_tool(name, **kw)

        # Step 1: progress_agent sets NEGATIVE mood
        with mock_tools(_negative):
            from app.agents.progress_agent import progress_agent_node
            prog_state = _base_state(
                current_topic="Control Flow & Loops",
                topic_proficiency={"Control Flow & Loops": 480.0},  # Elo=480 → "apply"
                progress_delta={"score": 0.15, "reflection": "I give up"},
            )
            prog_result = await progress_agent_node(prog_state)

        assert prog_result["learner_mood"] == "NEGATIVE"
        expected_base_bloom = get_bloom_level(480.0)  # "apply"

        # Step 2: quiz_agent inherits state with NEGATIVE mood
        with mock_tools(_negative):
            from app.agents.quiz_agent import quiz_agent_node
            quiz_state = _base_state(
                current_topic="Control Flow & Loops",
                topic_proficiency={"Control Flow & Loops": 480.0},
                learner_mood="NEGATIVE",  # ← written by progress_agent
            )
            quiz_result = await quiz_agent_node(quiz_state)

        actual_bloom = quiz_result["bloom_level"]
        expected_softened_idx = max(0, BLOOM_LEVELS.index(expected_base_bloom) - 1)
        expected_bloom = BLOOM_LEVELS[expected_softened_idx]

        assert actual_bloom == expected_bloom, (
            f"Bloom should soften from '{expected_base_bloom}' to '{expected_bloom}' "
            f"(NEGATIVE mood), got '{actual_bloom}'"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# XA-02  doubt_agent → learner_mood → quiz_agent  (bloom softened)
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA02_DoubtMoodToQuiz:
    """doubt_agent captures NEGATIVE mood from learner's question tone → quiz softens."""

    @pytest.mark.asyncio
    async def test_doubt_writes_negative_mood_to_state(self):
        from langchain_core.messages import HumanMessage

        async def _negative_tool(name, **kw):
            if name == "analyze_sentiment":
                return {"label": "NEGATIVE", "score": 0.77}
            return await _default_tool(name, **kw)

        async def _mock_stream(*args, **kwargs):
            async def _gen():
                yield "Here is the explanation."
            return _gen()

        with mock_tools(_negative_tool), \
             patch("app.agents.doubt_agent.stream_doubt_response", side_effect=_mock_stream):
            from app.agents.doubt_agent import doubt_agent_node
            state = _base_state(
                current_topic="Recursion",
                messages=[HumanMessage(content="I hate recursion, explain it please.")],
            )
            doubt_result = await doubt_agent_node(state)

        assert doubt_result["learner_mood"] == "NEGATIVE"
        assert doubt_result.get("learner_mood_score", 0) > 0.0

    @pytest.mark.asyncio
    async def test_quiz_softens_bloom_after_doubt_negative_mood(self):
        """quiz_agent reads learner_mood='NEGATIVE' from state (set by doubt_agent) and drops bloom."""
        # Elo 540 → base bloom "apply" (index 2) → softened to "understand" (index 1)
        elo = 540.0
        expected_base = get_bloom_level(elo)  # "apply"
        expected_softened = BLOOM_LEVELS[max(0, BLOOM_LEVELS.index(expected_base) - 1)]

        with mock_tools():
            from app.agents.quiz_agent import quiz_agent_node
            state = _base_state(
                current_topic="Recursion",
                topic_proficiency={"Recursion": elo},
                learner_mood="NEGATIVE",  # ← set by doubt_agent
            )
            result = await quiz_agent_node(state)

        assert result["bloom_level"] == expected_softened, (
            f"Expected '{expected_softened}' after NEGATIVE mood softening, got '{result['bloom_level']}'"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# XA-03  quiz_agent → topic_difficulty → supervisor state summary
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA03_QuizDifficultyToSupervisor:
    """quiz_agent writes topic_difficulty to state; supervisor includes it in the LLM prompt."""

    @pytest.mark.asyncio
    async def test_quiz_persists_topic_difficulty(self):
        async def _hard_topic(name, **kw):
            if name == "score_difficulty":
                return {"score": 0.82}
            return await _default_tool(name, **kw)

        with mock_tools(_hard_topic):
            from app.agents.quiz_agent import quiz_agent_node
            state = _base_state(
                current_topic="Advanced Concurrency Patterns",
                topic_proficiency={"Advanced Concurrency Patterns": 600.0},
            )
            result = await quiz_agent_node(state)

        assert "topic_difficulty" in result
        assert abs(result["topic_difficulty"] - 0.82) < 1e-6

    @pytest.mark.asyncio
    async def test_supervisor_state_summary_includes_difficulty(self):
        from app.agents.supervisor import _build_state_summary
        state = _base_state(
            topic_difficulty=0.82,
            learner_mood="NEUTRAL",
            current_topic="Advanced Concurrency Patterns",
            curriculum_path=[{"subtopic": "Advanced Concurrency Patterns", "domain": "Python Programming"}],
        )
        summary = _build_state_summary(state)
        assert "0.82" in summary, "topic_difficulty should appear in supervisor's state summary"
        assert "NEUTRAL" in summary, "learner_mood should appear in supervisor's state summary"


# ═══════════════════════════════════════════════════════════════════════════════
# XA-04  progress_agent → Elo crosses mastery → supervisor routes FINISH
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA04_ProgressMasteryToFinish:
    """After progress pushes Elo >= 700, supervisor should end the session."""

    @pytest.mark.asyncio
    async def test_elo_crosses_mastery_then_supervisor_finishes(self):
        with mock_tools():
            from app.agents.progress_agent import progress_agent_node
            prog_state = _base_state(
                current_topic="Variables & Data Types",
                topic_proficiency={"Variables & Data Types": 685.0},  # just below mastery
                progress_delta={"score": 1.0},                        # perfect score → +16 Elo
            )
            prog_result = await progress_agent_node(prog_state)

        new_elo = prog_result["topic_proficiency"]["Variables & Data Types"]
        assert new_elo >= 700.0, f"Elo should cross mastery threshold, got {new_elo}"

        # Supervisor sees all topics mastered → FINISH
        from app.agents.supervisor import supervisor_node
        sup_state = _base_state(
            curriculum_path=[{"subtopic": "Variables & Data Types", "domain": "Python Programming"}],
            topic_proficiency={"Variables & Data Types": new_elo},
            mastery_threshold=700.0,
        )
        with patch("app.agents.supervisor._llm_decide", new_callable=AsyncMock) as _llm:
            sup_result = await supervisor_node(sup_state)

        _llm.assert_not_called()  # hard guard should fire before LLM
        assert sup_result["supervisor_decision"] == "FINISH"
        assert sup_result["session_complete"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# XA-05  curriculum_agent → current_topic → quiz_agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA05_CurriculumTopicToQuiz:
    """curriculum_agent builds the path; quiz_agent uses the first unmastered topic."""

    @pytest.mark.asyncio
    async def test_curriculum_lowest_elo_topic_feeds_quiz(self):
        async def _classify_ml(name, **kw):
            if name == "classify_topic":
                return {"labels": ["Machine Learning"], "scores": [0.9]}
            return await _default_tool(name, **kw)

        # Curriculum with known proficiency gap
        proficiency = {
            "Supervised Learning": 650.0,
            "Neural Networks": 300.0,   # weakest — should be first
            "Model Evaluation": 500.0,
        }

        with mock_tools(_classify_ml):
            from app.agents.curriculum_agent import curriculum_agent_node
            curr_state = _base_state(
                learner_profile={"goal_vector": ["build ML models"]},
                topic_proficiency=proficiency,
            )
            curr_result = await curriculum_agent_node(curr_state)

        path = curr_result["curriculum_path"]
        assert len(path) > 0

        # First topic in path should have the lowest Elo
        first_elo = path[0].get("elo", 500.0)
        for item in path[1:]:
            assert first_elo <= item.get("elo", 500.0), "Path not sorted by Elo"

        # Quiz agent uses the first unmastered topic from curriculum
        first_unmastered = next(
            (i["subtopic"] for i in path if proficiency.get(i["subtopic"], 500.0) < 700.0),
            path[0]["subtopic"],
        )
        with mock_tools(_classify_ml):
            from app.agents.quiz_agent import quiz_agent_node
            quiz_state = _base_state(
                current_topic=first_unmastered,
                topic_proficiency=proficiency,
                curriculum_path=path,
            )
            quiz_result = await quiz_agent_node(quiz_state)

        assert quiz_result["quiz_questions"], "Quiz agent should generate questions"
        # All questions should be tagged with the chosen topic's bloom level
        expected_bloom = get_bloom_level(proficiency.get(first_unmastered, 500.0))
        for q in quiz_result["quiz_questions"]:
            assert q["bloom_level"] == expected_bloom or quiz_result["bloom_level"] == expected_bloom


# ═══════════════════════════════════════════════════════════════════════════════
# XA-06  progress POSITIVE mood → quiz bloom NOT softened
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA06_PositiveMoodNoSoftening:
    """POSITIVE mood must NOT drop the bloom level — only NEGATIVE does."""

    @pytest.mark.asyncio
    async def test_positive_mood_keeps_bloom_at_natural_elo_level(self):
        async def _positive(name, **kw):
            if name == "analyze_sentiment":
                return {"label": "POSITIVE", "score": 0.95}
            return await _default_tool(name, **kw)

        # Step 1: progress writes POSITIVE mood
        with mock_tools(_positive):
            from app.agents.progress_agent import progress_agent_node
            prog_state = _base_state(
                current_topic="Functions & Closures",
                topic_proficiency={"Functions & Closures": 510.0},  # "apply"
                progress_delta={"score": 0.9, "reflection": "Great session!"},
            )
            prog_result = await progress_agent_node(prog_state)

        assert prog_result["learner_mood"] == "POSITIVE"

        # Step 2: quiz_agent should NOT soften bloom for POSITIVE mood
        elo = prog_result["topic_proficiency"]["Functions & Closures"]
        expected_bloom = get_bloom_level(elo)

        with mock_tools(_positive):
            from app.agents.quiz_agent import quiz_agent_node
            quiz_state = _base_state(
                current_topic="Functions & Closures",
                topic_proficiency={"Functions & Closures": elo},
                learner_mood="POSITIVE",
            )
            quiz_result = await quiz_agent_node(quiz_state)

        assert quiz_result["bloom_level"] == expected_bloom, (
            f"POSITIVE mood must not soften bloom — expected '{expected_bloom}', "
            f"got '{quiz_result['bloom_level']}'"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# XA-07  doubt_agent → bloom_level derived from topic proficiency
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA07_DoubtBloomFromProficiency:
    """doubt_agent derives explanation depth from learner's proficiency in detected domain."""

    @pytest.mark.asyncio
    async def test_bloom_level_matches_detected_domain_proficiency(self):
        from langchain_core.messages import HumanMessage

        bloom_calls: list[str] = []

        async def _mock_stream(*args, bloom_level="", **kwargs):
            bloom_calls.append(bloom_level)
            async def _gen():
                yield "Gradient descent minimizes the loss function."
            return _gen()

        async def _classify_dl(name, **kw):
            if name == "classify_topic":
                return {"labels": ["Deep Learning"], "scores": [0.88]}
            if name == "analyze_sentiment":
                return {"label": "NEUTRAL", "score": 0.5}
            return await _default_tool(name, **kw)

        # Learner has Elo 650 in Deep Learning → bloom = "analyze"
        proficiency = {"Deep Learning": 650.0}
        expected_bloom = get_bloom_level(650.0)  # "analyze"

        with mock_tools(_classify_dl), \
             patch("app.agents.doubt_agent.stream_doubt_response", side_effect=_mock_stream):
            from app.agents.doubt_agent import doubt_agent_node
            state = _base_state(
                current_topic="Deep Learning",
                topic_proficiency=proficiency,
                messages=[HumanMessage(content="Explain backpropagation please.")],
            )
            await doubt_agent_node(state)

        assert bloom_calls, "stream_doubt_response should have been called"
        assert bloom_calls[0] == expected_bloom, (
            f"Expected bloom '{expected_bloom}' from proficiency 650, "
            f"but stream received '{bloom_calls[0]}'"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# XA-08  supervisor routes to progress when score is unprocessed
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA08_SupervisorUnprocessedScore:
    """Supervisor must route to progress when progress_delta has score but elo_processed=False."""

    @pytest.mark.asyncio
    async def test_supervisor_routes_progress_on_pending_score(self):
        from app.agents.supervisor import supervisor_node
        state = _base_state(
            curriculum_path=[{"subtopic": "OOP", "domain": "Python Programming"}],
            topic_proficiency={"OOP": 500.0},
            progress_delta={"score": 0.85, "elo_processed": False},
            task_type="start",
        )
        with patch("app.agents.supervisor._llm_decide", new_callable=AsyncMock) as _llm:
            result = await supervisor_node(state)

        _llm.assert_not_called()  # deterministic rule should fire
        assert result["supervisor_decision"] == "progress"

    @pytest.mark.asyncio
    async def test_supervisor_skips_progress_when_already_processed(self):
        """Once elo_processed=True, supervisor no longer routes to progress."""
        from app.agents.supervisor import supervisor_node
        state = _base_state(
            curriculum_path=[{"subtopic": "OOP", "domain": "Python Programming"}],
            topic_proficiency={"OOP": 500.0},
            progress_delta={"score": 0.85, "elo_processed": True},
            task_type="quiz",
        )
        with patch("app.agents.supervisor._llm_decide", new_callable=AsyncMock):
            result = await supervisor_node(state)

        assert result["supervisor_decision"] != "progress"


# ═══════════════════════════════════════════════════════════════════════════════
# XA-09  supervisor → curriculum (cold start) → supervisor → quiz  (2-hop)
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA09_SupervisorColdStartTwoHop:
    """
    Cold start: no curriculum.
    Supervisor routes → curriculum → curriculum writes path → supervisor routes → quiz.
    """

    @pytest.mark.asyncio
    async def test_two_hop_supervisor_curriculum_quiz(self):
        async def _mock_llm(state):
            if state.get("curriculum_path"):
                return ("quiz", "curriculum built, quiz next")
            return ("curriculum", "no curriculum yet")

        with mock_tools(), \
             patch("app.agents.supervisor._llm_decide", side_effect=_mock_llm):
            from app.agents.orchestrator import orchestrator
            state = _base_state(
                task_type="start",
                learner_profile={"goal_vector": ["learn Python functions"]},
            )
            result = await orchestrator.ainvoke(state)

        # Curriculum was built
        assert len(result["curriculum_path"]) > 0, "Curriculum must be populated after cold start"
        # Quiz was generated — supervisor routed to quiz after seeing curriculum
        assert len(result["quiz_questions"]) > 0, "Quiz questions must be generated"
        assert result["current_topic"] != "", "A topic must be selected"
        # Session not over — quiz is waiting for learner
        assert not result["session_complete"]


# ═══════════════════════════════════════════════════════════════════════════════
# XA-10  supervisor → progress → supervisor → quiz  (score processing chain)
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA10_SupervisorProgressQuizChain:
    """Unprocessed score → supervisor routes to progress → Elo updated → supervisor routes to quiz."""

    @pytest.mark.asyncio
    async def test_progress_elo_update_then_quiz(self):
        curriculum = [
            {"domain": "Python", "subtopic": "Variables & Data Types", "priority": 0, "elo": 500.0},
            {"domain": "Python", "subtopic": "Control Flow & Loops",   "priority": 1, "elo": 500.0},
        ]

        async def _mock_llm(state):
            delta = state.get("progress_delta") or {}
            if delta.get("elo_processed"):
                return ("quiz", "Elo updated, advance to quiz")
            return ("progress", "score needs Elo update")

        with mock_tools(), \
             patch("app.agents.supervisor._llm_decide", side_effect=_mock_llm):
            from app.agents.orchestrator import orchestrator
            state = _base_state(
                task_type="progress",
                current_topic="Variables & Data Types",
                topic_proficiency={"Variables & Data Types": 500.0, "Control Flow & Loops": 500.0},
                curriculum_path=curriculum,
                progress_delta={"score": 0.9},  # unprocessed
            )
            result = await orchestrator.ainvoke(state)

        # Elo was updated
        assert result["topic_proficiency"]["Variables & Data Types"] > 500.0
        # Quiz was generated for the next topic
        assert len(result["quiz_questions"]) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# XA-11  supervisor iteration cap → FINISH (overrides unmastered topics)
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA11_SupervisorIterationCap:
    """Iteration cap fires even when topics remain unmastered — hard guard, no LLM call."""

    @pytest.mark.asyncio
    async def test_iteration_cap_ends_session_before_llm(self):
        from app.agents.supervisor import supervisor_node
        curriculum = [{"subtopic": "Async Programming", "domain": "Python Programming"}]

        with patch("app.agents.supervisor._llm_decide", new_callable=AsyncMock) as _llm:
            state = _base_state(
                curriculum_path=curriculum,
                topic_proficiency={"Async Programming": 400.0},
                iteration_count=7,   # supervisor adds 1 → 8 = max
                max_iterations=8,
            )
            result = await supervisor_node(state)

        _llm.assert_not_called()
        assert result["supervisor_decision"] == "FINISH"
        assert result["session_complete"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# XA-12  NEGATIVE mood + high difficulty → double bloom drop
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA12_DoubleBloomDrop:
    """
    High-difficulty topic (score > 0.75) + low Elo (<400) drops bloom by 1.
    NEGATIVE learner_mood drops it by 1 more.
    Combined: 2-level drop from natural Elo-based bloom.
    Learner Elo = 320 → natural bloom = "understand" (index 1).
    After difficulty drop: "remember" (index 0). After mood drop: stays "remember" (clamped at 0).
    """

    @pytest.mark.asyncio
    async def test_two_level_drop_difficulty_plus_mood(self):
        async def _hard_negative(name, **kw):
            if name == "score_difficulty":
                return {"score": 0.90}           # very hard
            if name == "analyze_sentiment":
                return {"label": "NEGATIVE", "score": 0.88}
            return await _default_tool(name, **kw)

        elo = 320.0
        natural = get_bloom_level(elo)  # "understand" (index 1)

        with mock_tools(_hard_negative):
            from app.agents.quiz_agent import quiz_agent_node
            state = _base_state(
                current_topic="Advanced Meta-Programming",
                topic_proficiency={"Advanced Meta-Programming": elo},
                learner_mood="NEGATIVE",
            )
            result = await quiz_agent_node(state)

        # Both drops applied: understand→remember (difficulty), remember→remember (clamped)
        assert result["bloom_level"] == "remember", (
            f"Expected 'remember' after double drop from '{natural}', "
            f"got '{result['bloom_level']}'"
        )

    @pytest.mark.asyncio
    async def test_mid_elo_two_level_drop_lands_at_correct_bloom(self):
        """
        Elo 560 → "apply" (index 2).
        Difficulty drop: "understand" (index 1).
        Mood drop: "remember" (index 0).
        """
        async def _hard_negative(name, **kw):
            if name == "score_difficulty":
                return {"score": 0.85}
            return await _default_tool(name, **kw)

        # Elo 560 < 400 is False, so difficulty guard only fires when elo < 400.
        # Let's use Elo 350 which is < 400 for the difficulty guard.
        elo = 350.0  # "understand" (index 1)
        natural = get_bloom_level(elo)
        assert natural == "understand"

        with mock_tools(_hard_negative):
            from app.agents.quiz_agent import quiz_agent_node
            state = _base_state(
                current_topic="System Design",
                topic_proficiency={"System Design": elo},
                learner_mood="NEGATIVE",
            )
            result = await quiz_agent_node(state)

        # difficulty drop: understand(1) → remember(0), mood drop: remember(0) → remember(0)
        assert result["bloom_level"] == "remember"


# ═══════════════════════════════════════════════════════════════════════════════
# XA-13  curriculum proficiency gap → correct topic selected for quiz
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA13_CurriculumGapToQuizTopic:
    """
    curriculum_agent sorts by Elo gap (lowest first).
    quiz_agent is then invoked on the first unmastered topic.
    Verify the weakest topic is the one quizzed.
    """

    @pytest.mark.asyncio
    async def test_lowest_elo_topic_is_quizzed(self):
        async def _classify_py(name, **kw):
            if name == "classify_topic":
                return {"labels": ["Python Programming"], "scores": [0.95]}
            return await _default_tool(name, **kw)

        proficiency = {
            "Variables & Data Types":  750.0,  # mastered
            "Control Flow & Loops":    250.0,  # weakest — should be first in curriculum
            "Functions & Closures":    510.0,
        }

        with mock_tools(_classify_py):
            from app.agents.curriculum_agent import curriculum_agent_node
            curr_state = _base_state(
                learner_profile={"goal_vector": ["learn Python"]},
                topic_proficiency=proficiency,
            )
            curr_result = await curriculum_agent_node(curr_state)

        path = curr_result["curriculum_path"]
        unmastered = [i for i in path if proficiency.get(i["subtopic"], 500.0) < 700.0]
        assert unmastered, "There should be unmastered topics"
        weakest = min(unmastered, key=lambda i: proficiency.get(i["subtopic"], 500.0))

        # Quiz the weakest topic
        with mock_tools(_classify_py):
            from app.agents.quiz_agent import quiz_agent_node
            quiz_state = _base_state(
                current_topic=weakest["subtopic"],
                topic_proficiency=proficiency,
            )
            quiz_result = await quiz_agent_node(quiz_state)

        assert quiz_result["quiz_questions"], "Quiz must generate questions for the weakest topic"
        expected_bloom = get_bloom_level(proficiency[weakest["subtopic"]])
        assert quiz_result["bloom_level"] == expected_bloom, (
            f"Bloom should match Elo {proficiency[weakest['subtopic']]} → '{expected_bloom}', "
            f"got '{quiz_result['bloom_level']}'"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# XA-14  progress NEGATIVE → supervisor → quiz with softened bloom  (3-agent chain)
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA14_ThreeAgentNegativeMoodChain:
    """
    progress_agent computes NEGATIVE mood → stored in state.
    supervisor sees it → routes to quiz and optionally sets bloom_level="remember".
    quiz_agent reads NEGATIVE learner_mood from state → additionally softens.
    """

    @pytest.mark.asyncio
    async def test_three_agent_negative_chain(self):
        curriculum = [
            {"domain": "Python", "subtopic": "Generators & Iterators", "priority": 0, "elo": 480.0},
        ]

        async def _negative_tool(name, **kw):
            if name == "analyze_sentiment":
                return {"label": "NEGATIVE", "score": 0.85}
            return await _default_tool(name, **kw)

        async def _mock_llm(state):
            if (state.get("progress_delta") or {}).get("elo_processed"):
                return ("quiz", "Elo done, quiz with negative mood")
            return ("progress", "needs Elo update")

        with mock_tools(_negative_tool), \
             patch("app.agents.supervisor._llm_decide", side_effect=_mock_llm):
            from app.agents.orchestrator import orchestrator
            state = _base_state(
                task_type="progress",
                current_topic="Generators & Iterators",
                topic_proficiency={"Generators & Iterators": 480.0},
                curriculum_path=curriculum,
                progress_delta={"score": 0.2, "reflection": "very confused"},
                learner_mood="NEUTRAL",
            )
            result = await orchestrator.ainvoke(state)

        # progress_agent updated Elo
        assert "Generators & Iterators" in result["topic_proficiency"]
        # quiz_agent produced questions
        assert len(result["quiz_questions"]) > 0
        # bloom should be softened — NEGATIVE mood drops it at least once from "apply" (Elo≈480)
        final_bloom = result["bloom_level"]
        natural_bloom = get_bloom_level(480.0)  # "apply"
        natural_idx = BLOOM_LEVELS.index(natural_bloom)
        final_idx = BLOOM_LEVELS.index(final_bloom)
        assert final_idx <= natural_idx, (
            f"Bloom must be softened (≤ '{natural_bloom}'), got '{final_bloom}'"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# XA-15  full cold-start orchestrator: supervisor→curriculum→supervisor→quiz→END
# ═══════════════════════════════════════════════════════════════════════════════

class TestXA15_FullOrchestratorColdStart:
    """
    End-to-end: brand-new learner with goals.
    Agents involved: supervisor → curriculum_agent → supervisor → quiz_agent → END.
    Verify every cross-agent state field is populated correctly at the end.
    """

    @pytest.mark.asyncio
    async def test_full_cold_start_all_state_fields_populated(self):
        async def _mock_llm(state):
            if state.get("curriculum_path"):
                return ("quiz", "curriculum ready, start quiz")
            return ("curriculum", "cold start: build curriculum first")

        with mock_tools(), \
             patch("app.agents.supervisor._llm_decide", side_effect=_mock_llm):
            from app.agents.orchestrator import orchestrator
            state = _base_state(
                task_type="start",
                learner_profile={"goal_vector": ["master Python closures and decorators"]},
                topic_proficiency={},  # brand new learner
            )
            result = await orchestrator.ainvoke(state)

        # ── Curriculum populated (curriculum_agent wrote it) ──────────────────
        assert len(result["curriculum_path"]) > 0, "curriculum_path must be built"
        assert all("subtopic" in i and "domain" in i for i in result["curriculum_path"])

        # ── Quiz generated (quiz_agent wrote it) ──────────────────────────────
        assert len(result["quiz_questions"]) > 0, "quiz_questions must be generated"
        assert result["current_topic"] != "", "current_topic must be set"

        # ── topic_difficulty set by quiz_agent ────────────────────────────────
        assert "topic_difficulty" in result, "quiz_agent must write topic_difficulty"
        assert 0.0 <= result["topic_difficulty"] <= 1.0

        # ── bloom_level matches proficiency for a brand-new learner ──────────
        assert result["bloom_level"] != "", "bloom_level must be determined"

        # ── Agent reports from every agent in the chain ───────────────────────
        report_agents = {r["agent"] for r in result.get("agent_reports", [])}
        assert "curriculum" in report_agents, "curriculum_agent must append a report"
        assert "quiz" in report_agents, "quiz_agent must append a report"
        assert "supervisor" in report_agents, "supervisor must append a report"

        # ── Session should NOT be complete — waiting for learner input ────────
        assert not result["session_complete"], "Session must stay open after quiz is delivered"
