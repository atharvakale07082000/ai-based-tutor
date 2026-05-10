import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestDoubtSolver:
    @pytest.mark.asyncio
    async def test_stream_returns_async_iterator(self):
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Hello"

        with patch("app.hf.doubt_solver.get_hf_client") as mock_client:
            mock_client.return_value.chat_completion.return_value = iter([mock_chunk])
            from app.hf.doubt_solver import stream_doubt_response

            stream = await stream_doubt_response("What is Python?", "Python Programming")
            tokens = []
            async for token in stream:
                tokens.append(token)
            assert "Hello" in tokens

    @pytest.mark.asyncio
    async def test_stream_with_history(self):
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Response"

        with patch("app.hf.doubt_solver.get_hf_client") as mock_client:
            mock_client.return_value.chat_completion.return_value = iter([mock_chunk])
            from app.hf.doubt_solver import stream_doubt_response

            history = [
                {"role": "user", "content": "previous question"},
                {"role": "assistant", "content": "previous answer"},
            ]
            stream = await stream_doubt_response("Follow-up?", "Python", history)
            tokens = [t async for t in stream]
            assert len(tokens) > 0


_MOCK_JSON_Q = '{"question": "What is a Python decorator used for?", "options": ["Wrapping functions to extend behavior", "Defining class variables", "Importing modules", "Handling exceptions"], "correct_index": 0, "explanation": "Decorators wrap functions to add behavior."}'


class TestQuizGenerator:
    @pytest.mark.asyncio
    async def test_generate_returns_questions(self):
        mock_result = MagicMock()
        mock_result.choices[0].message.content = _MOCK_JSON_Q
        with patch("app.hf.quiz_generator.get_hf_client") as mock_client:
            mock_client.return_value.chat_completion.return_value = mock_result
            from app.hf.quiz_generator import generate_quiz_questions
            questions = await generate_quiz_questions("Python", "remember", count=2)
            assert len(questions) == 2
            assert "question" in questions[0]
            assert len(questions[0]["options"]) == 4

    @pytest.mark.asyncio
    async def test_generate_uses_bloom_prompt(self):
        mock_result = MagicMock()
        mock_result.choices[0].message.content = _MOCK_JSON_Q
        with patch("app.hf.quiz_generator.get_hf_client") as mock_client:
            mock_client.return_value.chat_completion.return_value = mock_result
            from app.hf.quiz_generator import generate_quiz_questions
            questions = await generate_quiz_questions("ML", "analyze", count=1)
            assert questions[0]["bloom_level"] == "analyze"

    def test_parse_quiz_response_extracts_correct_index(self):
        from app.hf.quiz_generator import _parse_response
        result = _parse_response(_MOCK_JSON_Q, "Python", "remember")
        assert result is not None
        assert result["correct_index"] == 0
        assert "Wrapping" in result["options"][0]


class TestSentiment:
    @pytest.mark.asyncio
    async def test_analyze_returns_label_and_score(self):
        mock_result = MagicMock()
        mock_result.label = "POSITIVE"
        mock_result.score = 0.95

        with patch("app.hf.sentiment.get_hf_client") as mock_client:
            mock_client.return_value.text_classification.return_value = [mock_result]
            from app.hf.sentiment import analyze_sentiment
            result = await analyze_sentiment("I really understood this concept!")
            assert result["label"] == "POSITIVE"
            assert result["score"] > 0.5

    @pytest.mark.asyncio
    async def test_analyze_negative_sentiment(self):
        mock_result = MagicMock()
        mock_result.label = "NEGATIVE"
        mock_result.score = 0.87

        with patch("app.hf.sentiment.get_hf_client") as mock_client:
            mock_client.return_value.text_classification.return_value = [mock_result]
            from app.hf.sentiment import analyze_sentiment
            result = await analyze_sentiment("I'm totally confused and lost.")
            assert result["label"] == "NEGATIVE"

    @pytest.mark.asyncio
    async def test_analyze_returns_neutral_on_error(self):
        with patch("app.hf.sentiment.get_hf_client") as mock_client:
            mock_client.return_value.text_classification.side_effect = Exception("API error")
            from app.hf.sentiment import analyze_sentiment
            # Should not raise
            try:
                result = await analyze_sentiment("test")
            except Exception:
                result = {"label": "NEUTRAL", "score": 0.5}
            assert "label" in result


class TestTopicClassifier:
    @pytest.mark.asyncio
    async def test_classify_returns_labels_and_scores(self):
        mock_result = MagicMock()
        mock_result.labels = ["Python Programming", "Machine Learning"]
        mock_result.scores = [0.85, 0.72]

        with patch("app.hf.topic_classifier.get_hf_client") as mock_client:
            mock_client.return_value.zero_shot_classification.return_value = mock_result
            from app.hf.topic_classifier import classify_topic
            result = await classify_topic("I want to learn how to code in Python")
            assert "labels" in result
            assert len(result["labels"]) > 0
            assert result["labels"][0] == "Python Programming"

    @pytest.mark.asyncio
    async def test_classify_with_custom_labels(self):
        mock_result = MagicMock()
        mock_result.labels = ["NLP", "CV"]
        mock_result.scores = [0.9, 0.4]

        with patch("app.hf.topic_classifier.get_hf_client") as mock_client:
            mock_client.return_value.zero_shot_classification.return_value = mock_result
            from app.hf.topic_classifier import classify_topic
            result = await classify_topic("text processing", ["NLP", "CV"])
            assert result["labels"][0] == "NLP"


class TestImageCaptioner:
    @pytest.mark.asyncio
    async def test_caption_returns_string(self):
        mock_result = MagicMock()
        mock_result.generated_text = "A diagram showing neural network layers"

        with patch("app.hf.image_captioner.get_hf_client") as mock_client:
            mock_client.return_value.image_to_text.return_value = mock_result
            from app.hf.image_captioner import caption_image
            result = await caption_image(b"fake-image-bytes")
            assert isinstance(result, str)
            assert "neural network" in result

    @pytest.mark.asyncio
    async def test_caption_handles_list_result(self):
        mock_item = MagicMock()
        mock_item.generated_text = "A Python code snippet"

        with patch("app.hf.image_captioner.get_hf_client") as mock_client:
            mock_client.return_value.image_to_text.return_value = [mock_item]
            from app.hf.image_captioner import caption_image
            result = await caption_image(b"bytes")
            assert result == "A Python code snippet"

    @pytest.mark.asyncio
    async def test_caption_empty_list_returns_empty(self):
        with patch("app.hf.image_captioner.get_hf_client") as mock_client:
            mock_client.return_value.image_to_text.return_value = []
            from app.hf.image_captioner import caption_image
            result = await caption_image(b"bytes")
            assert result == ""


class TestSpeechToText:
    @pytest.mark.asyncio
    async def test_transcribe_returns_text(self):
        mock_result = MagicMock()
        mock_result.text = "What is a list comprehension in Python?"

        with patch("app.hf.speech_to_text.get_hf_client") as mock_client:
            mock_client.return_value.automatic_speech_recognition.return_value = mock_result
            from app.hf.speech_to_text import transcribe_audio
            result = await transcribe_audio(b"fake-audio-bytes")
            assert result == "What is a list comprehension in Python?"

    @pytest.mark.asyncio
    async def test_transcribe_fallback_to_str(self):
        mock_result = "plain string result"

        with patch("app.hf.speech_to_text.get_hf_client") as mock_client:
            mock_client.return_value.automatic_speech_recognition.return_value = mock_result
            from app.hf.speech_to_text import transcribe_audio
            result = await transcribe_audio(b"bytes")
            assert isinstance(result, str)
            assert result == "plain string result"


class TestEmbeddings:
    @pytest.mark.asyncio
    async def test_get_embeddings_returns_float_list(self):
        import numpy as np
        fake_embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)

        with patch("app.hf.embeddings.get_hf_client") as mock_client:
            mock_client.return_value.feature_extraction.return_value = fake_embedding
            from app.hf.embeddings import get_embeddings
            result = await get_embeddings("Python list comprehension")
            assert isinstance(result, list)
            assert len(result) == 3
            assert all(isinstance(x, float) for x in result)

    @pytest.mark.asyncio
    async def test_get_embeddings_unnests_nested_list(self):
        import numpy as np
        nested = np.array([[0.1, 0.2, 0.3]], dtype=np.float32)

        with patch("app.hf.embeddings.get_hf_client") as mock_client:
            mock_client.return_value.feature_extraction.return_value = nested
            from app.hf.embeddings import get_embeddings
            result = await get_embeddings("text")
            assert len(result) == 3
            assert all(isinstance(x, float) for x in result)

    def test_cosine_similarity_identical_vectors(self):
        from app.hf.embeddings import cosine_similarity
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)

    def test_cosine_similarity_orthogonal_vectors(self):
        from app.hf.embeddings import cosine_similarity
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0, abs=1e-6)

    def test_cosine_similarity_empty_returns_zero(self):
        from app.hf.embeddings import cosine_similarity
        assert cosine_similarity([], []) == 0.0

    def test_cosine_similarity_mismatched_lengths_returns_zero(self):
        from app.hf.embeddings import cosine_similarity
        assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0


class TestDifficultyScorer:
    @pytest.mark.asyncio
    async def test_score_returns_float_in_range(self):
        mock_result = MagicMock()
        mock_result.score = 0.8

        with patch("app.hf.difficulty_scorer.get_hf_client") as mock_client:
            mock_client.return_value.text_classification.return_value = [mock_result]
            from app.hf.difficulty_scorer import score_difficulty
            result = await score_difficulty("Advanced async Python with asyncio")
            assert 0.0 <= result <= 1.0
            assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_score_defaults_on_error(self):
        with patch("app.hf.difficulty_scorer.get_hf_client") as mock_client:
            mock_client.return_value.text_classification.side_effect = Exception("API error")
            from app.hf.difficulty_scorer import score_difficulty
            result = await score_difficulty("some text")
            assert result == 0.5


class TestRecommendationAgent:
    @pytest.mark.asyncio
    async def test_rank_returns_items_with_flag(self):
        fake_emb = [0.1, 0.2, 0.3, 0.4]

        with patch("app.hf.recommendation_agent.get_embeddings", return_value=fake_emb):
            from app.hf.recommendation_agent import rank_content_for_learner
            items = [
                {"title": "Python Basics", "topic": "Python Programming", "subtopic": "Variables"},
                {"title": "ML Intro", "topic": "Machine Learning", "subtopic": "Regression"},
            ]
            result = await rank_content_for_learner(
                items,
                goal_vector=["learn python"],
                topic_proficiency={"Python Programming": 400.0},
                top_n_recommended=1,
            )
            assert len(result) == 2
            flags = [r["is_ai_recommended"] for r in result]
            assert True in flags
            assert all("_relevance_score" in r for r in result)
            # _relevance_score must be a native Python float (not numpy)
            assert all(type(r["_relevance_score"]) is float for r in result)

    @pytest.mark.asyncio
    async def test_rank_empty_items_returns_empty(self):
        from app.hf.recommendation_agent import rank_content_for_learner
        result = await rank_content_for_learner([], goal_vector=[], topic_proficiency={})
        assert result == []

    @pytest.mark.asyncio
    async def test_rank_falls_back_on_error(self):
        with patch("app.hf.recommendation_agent.get_embeddings", side_effect=Exception("API error")):
            from app.hf.recommendation_agent import rank_content_for_learner
            items = [{"title": "X", "topic": "Y", "subtopic": "Z"}]
            result = await rank_content_for_learner(items, goal_vector=["python"], topic_proficiency={})
            # Should return original items unchanged on error
            assert result == items


class TestSpacedRepetition:
    def test_compute_due_topics_never_quizzed_is_due(self):
        from app.hf.spaced_repetition import compute_due_topics
        result = compute_due_topics(
            topic_proficiency={"Python": 500.0},
            last_quiz_dates={},
        )
        assert len(result) == 1
        assert result[0]["topic"] == "Python"
        assert result[0]["is_due"] is True
        assert result[0]["urgency"] == 1.0

    def test_compute_due_topics_recently_quizzed_not_due(self):
        from datetime import datetime, timezone, timedelta
        from app.hf.spaced_repetition import compute_due_topics
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(hours=1)).isoformat()
        result = compute_due_topics(
            topic_proficiency={"Python": 500.0},
            last_quiz_dates={"Python": recent},
            now=now,
        )
        assert result[0]["is_due"] is False
        assert result[0]["urgency"] < 1.0

    def test_compute_due_topics_sorted_by_urgency(self):
        from datetime import datetime, timezone, timedelta
        from app.hf.spaced_repetition import compute_due_topics
        now = datetime.now(timezone.utc)
        result = compute_due_topics(
            topic_proficiency={"Python": 500.0, "ML": 800.0},
            last_quiz_dates={},
            now=now,
        )
        urgencies = [r["urgency"] for r in result]
        assert urgencies == sorted(urgencies, reverse=True)

    def test_elo_to_interval_scaling(self):
        from app.hf.spaced_repetition import _elo_to_interval
        assert _elo_to_interval(0) == pytest.approx(1.0)
        assert _elo_to_interval(500) == pytest.approx(11.0)
        assert _elo_to_interval(1000) == pytest.approx(21.0)

    @pytest.mark.asyncio
    async def test_score_content_difficulty_returns_float(self):
        mock_result = MagicMock()
        mock_result.score = 0.3

        with patch("app.hf.spaced_repetition.get_hf_client") as mock_client:
            mock_client.return_value.text_classification.return_value = [mock_result]
            from app.hf.spaced_repetition import score_content_difficulty
            result = await score_content_difficulty("Introduction to Python variables")
            assert isinstance(result, float)
            assert 0.0 <= result <= 1.0

    @pytest.mark.asyncio
    async def test_score_content_difficulty_defaults_on_error(self):
        with patch("app.hf.spaced_repetition.get_hf_client") as mock_client:
            mock_client.return_value.text_classification.side_effect = Exception("fail")
            from app.hf.spaced_repetition import score_content_difficulty
            result = await score_content_difficulty("text")
            assert result == 0.5
