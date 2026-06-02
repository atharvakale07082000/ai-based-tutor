"""
Tests for the custom eval functions in app/evals/evaluator.py.

LLM-judge evals (doubt_accuracy, quiz_bloom_alignment, curriculum_coherence)
mock app.evals.llm_judge.score to return controlled scores — no external calls.

Structural evals (supervisor_routing) are pure Python and need no mocking.
"""
import pytest
from unittest.mock import AsyncMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _good_judge(criteria: list[str]) -> dict[str, float]:
    """Simulate a judge that rates everything 4/5 → normalized 0.75."""
    return {c: 0.75 for c in criteria}


def _poor_judge(criteria: list[str]) -> dict[str, float]:
    """Simulate a judge that rates everything 2/5 → normalized 0.25."""
    return {c: 0.25 for c in criteria}


def _mixed_judge(high: list[str], low: list[str]) -> dict[str, float]:
    return {c: 0.75 for c in high} | {c: 0.25 for c in low}


_SAMPLE_QUESTIONS = [
    {
        "id": "q1",
        "question": "What does the 'self' parameter represent in a Python method?",
        "options": ["The class itself", "The instance", "A module", "A built-in function"],
        "correct_index": 1,
        "explanation": "self refers to the instance.",
        "bloom_level": "understand",
    },
    {
        "id": "q2",
        "question": "Which keyword is used to define a class in Python?",
        "options": ["def", "class", "object", "type"],
        "correct_index": 1,
        "explanation": "class is the keyword.",
        "bloom_level": "remember",
    },
]

_SAMPLE_CURRICULUM = [
    {"domain": "Python Programming", "subtopic": "Variables & Data Types",  "priority": 0, "elo": 300.0},
    {"domain": "Python Programming", "subtopic": "Control Flow & Loops",    "priority": 1, "elo": 400.0},
    {"domain": "Python Programming", "subtopic": "Functions & Closures",    "priority": 2, "elo": 500.0},
    {"domain": "Python Programming", "subtopic": "Object-Oriented Python",  "priority": 3, "elo": 600.0},
]


# ── eval_supervisor_routing ───────────────────────────────────────────────────

class TestSupervisorRouting:
    """Pure rule-based eval — no LLM or mocking needed."""

    def _run(self, state_input: dict, decision: str) -> tuple[float, bool, dict]:
        from app.evals.evaluator import eval_supervisor_routing
        return eval_supervisor_routing(state_input, {"supervisor_decision": decision})

    def test_no_curriculum_expects_curriculum(self):
        score, passed, details = self._run({"curriculum_path": []}, "curriculum")
        assert passed
        assert score == 1.0
        assert details["rule"] == "no_curriculum"

    def test_no_curriculum_wrong_decision_fails(self):
        score, passed, details = self._run({"curriculum_path": []}, "quiz")
        assert not passed
        assert score == 0.0
        assert details["expected"] == "curriculum"

    def test_quiz_task_with_no_questions_expects_quiz(self):
        state = {
            "curriculum_path": [{"subtopic": "OOP", "domain": "Python Programming"}],
            "task_type": "quiz",
            "quiz_questions": [],
            "topic_proficiency": {},
        }
        score, passed, details = self._run(state, "quiz")
        assert passed
        assert details["rule"] == "quiz_requested"

    def test_doubt_task_expects_doubt(self):
        state = {
            "curriculum_path": [{"subtopic": "OOP", "domain": "Python Programming"}],
            "task_type": "doubt",
            "topic_proficiency": {},
        }
        score, passed, details = self._run(state, "doubt")
        assert passed
        assert details["rule"] == "doubt_requested"

    def test_unprocessed_score_expects_progress(self):
        state = {
            "curriculum_path": [{"subtopic": "OOP", "domain": "Python Programming"}],
            "task_type": "start",
            "topic_proficiency": {},
            "progress_delta": {"score": 0.8, "elo_processed": False},
        }
        score, passed, details = self._run(state, "progress")
        assert passed
        assert details["rule"] == "unprocessed_score"

    def test_all_mastered_expects_finish(self):
        state = {
            "curriculum_path": [{"subtopic": "OOP", "domain": "Python Programming"}],
            "task_type": "start",
            "topic_proficiency": {"OOP": 800.0},
            "mastery_threshold": 700.0,
            "progress_delta": {},
        }
        score, passed, details = self._run(state, "FINISH")
        assert passed
        assert details["rule"] == "all_mastered"

    def test_unmastered_topics_default_to_quiz(self):
        state = {
            "curriculum_path": [{"subtopic": "OOP", "domain": "Python Programming"}],
            "task_type": "start",
            "topic_proficiency": {"OOP": 400.0},
            "mastery_threshold": 700.0,
            "progress_delta": {},
        }
        score, passed, details = self._run(state, "quiz")
        assert passed
        assert details["rule"] == "default_quiz"

    def test_wrong_routing_returns_zero(self):
        state = {
            "curriculum_path": [{"subtopic": "OOP", "domain": "Python Programming"}],
            "task_type": "start",
            "topic_proficiency": {"OOP": 400.0},
            "mastery_threshold": 700.0,
            "progress_delta": {},
        }
        score, passed, details = self._run(state, "FINISH")  # wrong — should be quiz
        assert not passed
        assert score == 0.0
        assert details["expected"] == "quiz"


# ── eval_doubt_accuracy ───────────────────────────────────────────────────────

class TestDoubtAccuracy:
    @pytest.mark.asyncio
    async def test_high_quality_response_passes(self):
        async def _mock_score(prompt, criteria, **kw):
            return _good_judge(criteria)

        with patch("app.evals.llm_judge.score", side_effect=_mock_score):
            from app.evals.evaluator import eval_doubt_accuracy
            inp = {"question": "What is recursion?", "context": "Python Programming", "bloom_level": "understand"}
            out = {"doubt_response": "Recursion is when a function calls itself. Python Programming uses recursion for many algorithms."}
            score, passed, details = await eval_doubt_accuracy(inp, out)

        assert passed
        assert score >= 0.6
        assert "criteria_scores" in details
        assert set(details["criteria_scores"].keys()) == {"correctness", "clarity", "topic_relevance", "bloom_fit"}

    @pytest.mark.asyncio
    async def test_low_quality_response_fails(self):
        async def _mock_score(prompt, criteria, **kw):
            return _poor_judge(criteria)

        with patch("app.evals.llm_judge.score", side_effect=_mock_score):
            from app.evals.evaluator import eval_doubt_accuracy
            inp = {"question": "What is recursion?", "context": "Python Programming", "bloom_level": "understand"}
            out = {"doubt_response": "It is a thing in programming."}
            score, passed, details = await eval_doubt_accuracy(inp, out)

        assert not passed
        assert score < 0.6

    @pytest.mark.asyncio
    async def test_empty_response_returns_zero(self):
        from app.evals.evaluator import eval_doubt_accuracy
        score, passed, details = await eval_doubt_accuracy(
            {"question": "What is recursion?", "context": "Python"},
            {"doubt_response": ""},
        )
        assert score == 0.0
        assert not passed
        assert details["reason"] == "empty_response"

    @pytest.mark.asyncio
    async def test_judge_failure_falls_back_gracefully(self):
        """If the LLM judge fails, score = 0.5 avg — should not raise."""
        async def _failing_score(prompt, criteria, **kw):
            return {c: 0.5 for c in criteria}  # fallback values from llm_judge

        with patch("app.evals.llm_judge.score", side_effect=_failing_score):
            from app.evals.evaluator import eval_doubt_accuracy
            inp = {"question": "Explain lists", "context": "Python", "bloom_level": "remember"}
            out = {"doubt_response": "Lists store ordered items."}
            score, passed, details = await eval_doubt_accuracy(inp, out)

        assert score == pytest.approx(0.5)
        assert not passed  # 0.5 < 0.6 threshold

    @pytest.mark.asyncio
    async def test_score_is_average_of_criteria(self):
        async def _mixed(prompt, criteria, **kw):
            # correctness=0.75, clarity=0.75, topic_relevance=0.25, bloom_fit=0.25 → avg=0.5
            return _mixed_judge(["correctness", "clarity"], ["topic_relevance", "bloom_fit"])

        with patch("app.evals.llm_judge.score", side_effect=_mixed):
            from app.evals.evaluator import eval_doubt_accuracy
            score, passed, details = await eval_doubt_accuracy(
                {"question": "q", "context": "Python", "bloom_level": "apply"},
                {"doubt_response": "Some answer here about Python."},
            )

        assert score == pytest.approx(0.5)
        assert not passed


# ── eval_quiz_bloom_alignment ─────────────────────────────────────────────────

class TestQuizBloomAlignment:
    @pytest.mark.asyncio
    async def test_well_aligned_questions_pass(self):
        async def _mock_score(prompt, criteria, **kw):
            return _good_judge(criteria)

        with patch("app.evals.llm_judge.score", side_effect=_mock_score):
            from app.evals.evaluator import eval_quiz_bloom_alignment
            out = {"quiz_questions": _SAMPLE_QUESTIONS, "bloom_level": "understand"}
            score, passed, details = await eval_quiz_bloom_alignment({}, out)

        assert passed
        assert score >= 0.6
        assert "per_question" in details
        assert len(details["per_question"]) == 2  # only 2 sample questions

    @pytest.mark.asyncio
    async def test_misaligned_questions_fail(self):
        async def _mock_score(prompt, criteria, **kw):
            return _poor_judge(criteria)

        with patch("app.evals.llm_judge.score", side_effect=_mock_score):
            from app.evals.evaluator import eval_quiz_bloom_alignment
            out = {"quiz_questions": _SAMPLE_QUESTIONS, "bloom_level": "create"}
            score, passed, details = await eval_quiz_bloom_alignment({}, out)

        assert not passed
        assert score < 0.6

    @pytest.mark.asyncio
    async def test_no_questions_returns_zero(self):
        from app.evals.evaluator import eval_quiz_bloom_alignment
        score, passed, details = await eval_quiz_bloom_alignment({}, {"quiz_questions": [], "bloom_level": "remember"})
        assert score == 0.0
        assert not passed
        assert details["reason"] == "no_questions"

    @pytest.mark.asyncio
    async def test_samples_at_most_3_questions(self):
        """Judge should only be called for the first 3 questions even with a longer list."""
        call_count = 0

        async def _counting_score(prompt, criteria, **kw):
            nonlocal call_count
            call_count += 1
            return _good_judge(criteria)

        long_list = _SAMPLE_QUESTIONS * 5  # 10 questions
        with patch("app.evals.llm_judge.score", side_effect=_counting_score):
            from app.evals.evaluator import eval_quiz_bloom_alignment
            await eval_quiz_bloom_alignment({}, {"quiz_questions": long_list, "bloom_level": "apply"})

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_alignment_score_uses_bloom_alignment_not_distractor(self):
        """avg_alignment is computed only from bloom_alignment, not distractor_quality."""
        async def _mock_score(prompt, criteria, **kw):
            return {"bloom_alignment": 0.75, "distractor_quality": 0.0}

        with patch("app.evals.llm_judge.score", side_effect=_mock_score):
            from app.evals.evaluator import eval_quiz_bloom_alignment
            score, passed, details = await eval_quiz_bloom_alignment(
                {}, {"quiz_questions": [_SAMPLE_QUESTIONS[0]], "bloom_level": "understand"}
            )

        assert score == pytest.approx(0.75)
        assert passed


# ── eval_curriculum_coherence ─────────────────────────────────────────────────

class TestCurriculumCoherence:
    @pytest.mark.asyncio
    async def test_good_curriculum_passes(self):
        async def _mock_score(prompt, criteria, **kw):
            return _good_judge(criteria)

        with patch("app.evals.llm_judge.score", side_effect=_mock_score):
            from app.evals.evaluator import eval_curriculum_coherence
            inp = {"learner_profile": {"goal_vector": ["learn Python", "build web apps"]}}
            out = {"curriculum_path": _SAMPLE_CURRICULUM}
            score, passed, details = await eval_curriculum_coherence(inp, out)

        assert passed
        assert score >= 0.6
        assert "criteria_scores" in details
        assert set(details["criteria_scores"].keys()) == {"ordering_logic", "goal_alignment", "coverage_breadth"}

    @pytest.mark.asyncio
    async def test_poor_curriculum_fails(self):
        async def _mock_score(prompt, criteria, **kw):
            return _poor_judge(criteria)

        with patch("app.evals.llm_judge.score", side_effect=_mock_score):
            from app.evals.evaluator import eval_curriculum_coherence
            score, passed, details = await eval_curriculum_coherence(
                {"learner_profile": {}},
                {"curriculum_path": _SAMPLE_CURRICULUM},
            )

        assert not passed
        assert score < 0.6

    @pytest.mark.asyncio
    async def test_empty_path_returns_zero(self):
        from app.evals.evaluator import eval_curriculum_coherence
        score, passed, details = await eval_curriculum_coherence({}, {"curriculum_path": []})
        assert score == 0.0
        assert not passed
        assert details["reason"] == "empty_path"

    @pytest.mark.asyncio
    async def test_prompt_caps_at_8_topics(self):
        """Judge is called exactly once regardless of curriculum length."""
        call_count = 0

        async def _counting_score(prompt, criteria, **kw):
            nonlocal call_count
            call_count += 1
            # Verify prompt only includes up to 8 topics
            assert "9." not in prompt
            return _good_judge(criteria)

        long_curriculum = _SAMPLE_CURRICULUM * 5  # 20 topics
        with patch("app.evals.llm_judge.score", side_effect=_counting_score):
            from app.evals.evaluator import eval_curriculum_coherence
            score, passed, details = await eval_curriculum_coherence(
                {"learner_profile": {"goal_vector": ["learn Python"]}},
                {"curriculum_path": long_curriculum},
            )

        assert call_count == 1
        assert details["path_length"] == 20

    @pytest.mark.asyncio
    async def test_no_goals_still_runs(self):
        """Curriculum eval should work even when learner has no stated goals."""
        async def _mock_score(prompt, criteria, **kw):
            assert "not specified" in prompt
            return _good_judge(criteria)

        with patch("app.evals.llm_judge.score", side_effect=_mock_score):
            from app.evals.evaluator import eval_curriculum_coherence
            score, passed, details = await eval_curriculum_coherence(
                {"learner_profile": {}},
                {"curriculum_path": _SAMPLE_CURRICULUM},
            )

        assert passed


# ── llm_judge internals ───────────────────────────────────────────────────────

class TestLlmJudge:
    def test_parse_scores_normalises_correctly(self):
        from app.evals.llm_judge import _parse_scores
        raw = '{"correctness": 5, "clarity": 1}'
        result = _parse_scores(raw, ["correctness", "clarity"])
        assert result["correctness"] == pytest.approx(1.0)
        assert result["clarity"] == pytest.approx(0.0)

    def test_parse_scores_clamps_out_of_range(self):
        from app.evals.llm_judge import _parse_scores
        raw = '{"correctness": 6, "clarity": 0}'  # out of [1–5]
        result = _parse_scores(raw, ["correctness", "clarity"])
        assert result["correctness"] == pytest.approx(1.0)
        assert result["clarity"] == pytest.approx(0.0)

    def test_parse_scores_handles_missing_criterion(self):
        from app.evals.llm_judge import _parse_scores
        raw = '{"correctness": 4}'
        result = _parse_scores(raw, ["correctness", "clarity"])
        # Missing "clarity" → defaults to 3/5 = 0.5
        assert result["clarity"] == pytest.approx(0.5)

    def test_parse_scores_strips_markdown_fences(self):
        from app.evals.llm_judge import _parse_scores
        raw = '```json\n{"correctness": 3}\n```'
        result = _parse_scores(raw, ["correctness"])
        assert result["correctness"] == pytest.approx(0.5)

    def test_parse_scores_invalid_json_returns_fallback(self):
        from app.evals.llm_judge import _parse_scores
        raw = "Sorry, I cannot rate this."
        result = _parse_scores(raw, ["correctness", "clarity"])
        assert result == {"correctness": 0.5, "clarity": 0.5}

    @pytest.mark.asyncio
    async def test_score_returns_fallback_on_timeout(self):
        import asyncio as real_asyncio
        from unittest.mock import MagicMock
        from app.evals import llm_judge

        # Patch wait_for to close the coroutine before raising so we don't get
        # "coroutine was never awaited" warnings from the to_thread object.
        async def _timeout(coro, timeout):
            coro.close()
            raise real_asyncio.TimeoutError()

        mock_client = MagicMock()
        mock_client.chat_completion = MagicMock(return_value=MagicMock())

        with patch("app.evals.llm_judge.asyncio.wait_for", side_effect=_timeout), \
             patch("app.hf.client.get_hf_client", return_value=mock_client):
            result = await llm_judge.score("some prompt", ["correctness"])

        assert result == {"correctness": 0.5}

    @pytest.mark.asyncio
    async def test_score_returns_fallback_on_client_error(self):
        from app.evals import llm_judge
        with patch("app.hf.client.get_hf_client", side_effect=RuntimeError("no creds")):
            result = await llm_judge.score("some prompt", ["correctness", "clarity"])
        assert result == {"correctness": 0.5, "clarity": 0.5}


# ── run_eval dispatches async evals correctly ─────────────────────────────────

class TestRunEvalDispatch:
    @pytest.mark.asyncio
    async def test_run_eval_async_doubt_accuracy(self):
        async def _mock_score(prompt, criteria, **kw):
            return _good_judge(criteria)

        with patch("app.evals.llm_judge.score", side_effect=_mock_score):
            from app.evals.evaluator import run_eval
            record = await run_eval(
                "doubt_accuracy",
                "doubt_agent",
                {"question": "What is a list?", "context": "Python", "bloom_level": "remember"},
                {"doubt_response": "A list is a data structure in Python."},
                store=False,
            )

        assert record.score >= 0.6
        assert record.eval_type == "doubt_accuracy"

    @pytest.mark.asyncio
    async def test_run_eval_sync_supervisor_routing(self):
        from app.evals.evaluator import run_eval
        state_in = {"curriculum_path": [], "task_type": "start"}
        record = await run_eval(
            "supervisor_routing",
            "supervisor",
            state_in,
            {"supervisor_decision": "curriculum"},
            store=False,
        )
        assert record.passed
        assert record.score == 1.0

    @pytest.mark.asyncio
    async def test_run_eval_raises_on_unknown_type(self):
        from app.evals.evaluator import run_eval
        with pytest.raises(ValueError, match="Unknown eval_type"):
            await run_eval("nonexistent_eval", "agent", {}, {}, store=False)
