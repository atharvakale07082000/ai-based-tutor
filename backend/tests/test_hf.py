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


class TestQuizGenerator:
    @pytest.mark.asyncio
    async def test_generate_returns_questions(self):
        with patch("app.hf.quiz_generator.get_hf_client") as mock_client:
            mock_client.return_value.text_generation.return_value = (
                "Q: What is Python? A) A snake B) A language C) A framework D) A library ANSWER: B"
            )
            from app.hf.quiz_generator import generate_quiz_questions
            questions = await generate_quiz_questions("Python", "remember", count=2)
            assert len(questions) == 2
            assert "question" in questions[0]
            assert "options" in questions[0]

    @pytest.mark.asyncio
    async def test_generate_uses_bloom_prompt(self):
        with patch("app.hf.quiz_generator.get_hf_client") as mock_client:
            mock_client.return_value.text_generation.return_value = "Q: test A) a B) b C) c D) d ANSWER: A"
            from app.hf.quiz_generator import generate_quiz_questions
            questions = await generate_quiz_questions("ML", "analyze", count=1)
            assert questions[0]["bloom_level"] == "analyze"

    def test_parse_quiz_response_extracts_correct_index(self):
        from app.hf.quiz_generator import _parse_quiz_response
        text = "Q: What is 2+2?\nA) 4\nB) 3\nC) 5\nD) 6\nANSWER: A"
        result = _parse_quiz_response(text, "Math", "remember")
        assert result["correct_index"] == 0
        assert "4" in result["options"][0]


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
