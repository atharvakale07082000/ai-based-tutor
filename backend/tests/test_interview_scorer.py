"""Interview scoring pipeline — pins from the 2026-09-06 prompt audit.

Two findings are pinned here:
- Node 2 was a third LLM call that mapped node 1's (correctness, depth) pair onto a
  0-10 score. Its inputs fully determined its output, so it is now plain code.
- ``_chat`` truncated the *assembled* prompt at 7000 chars. ``analyze_answers`` ends
  with its ``## Output format`` block, so a long transcript lost the JSON schema and
  every question scored 0. Only the per-answer text may be bounded.
"""

from __future__ import annotations

import json

from app.agents import interview_scorer as scorer


def _questions(n: int) -> list[dict]:
    return [
        {"id": i, "text": f"Question {i}?", "expected_depth": "applied"}
        for i in range(1, n + 1)
    ]


def test_scoring_makes_one_analysis_call_not_two(monkeypatch):
    """Node 2 is deterministic — the pipeline calls the model for analysis + summary only."""
    prompts: list[str] = []

    def fake_chat(prompt, max_tokens=1200, temperature=0.1):
        prompts.append(prompt)
        if "## Scoring scale" in prompt:  # node 1
            return json.dumps(
                [
                    {
                        "question_id": 1,
                        "correctness": "correct",
                        "depth_achieved": "deep",
                        "score": 9,
                        "justification": "Nailed the trade-offs.",
                        "concepts_covered": ["joins"],
                        "concepts_missed": [],
                    }
                ]
            )
        return "Strong work on joins. Next, tighten your indexing story."

    monkeypatch.setattr(scorer, "_chat", fake_chat)

    out = scorer.run_scoring_agent(
        "SQL",
        ["joins"],
        _questions(1),
        [{"question_id": 1, "answer_text": "A long, correct answer about joins."}],
    )

    assert len(prompts) == 2, (
        f"expected analyze + summary only, got {len(prompts)} calls"
    )
    assert out["scoring_matrix"][0]["score"] == 9
    assert out["scoring_matrix"][0]["justification"] == "Nailed the trade-offs."
    assert out["final_score"] == 9.0


def test_score_falls_back_to_the_table_when_the_model_omits_it():
    """The (correctness, depth) -> score mapping lives in code, not in a second prompt."""
    assert scorer._score_for({"correctness": "correct", "depth_achieved": "deep"}) == 10
    assert (
        scorer._score_for({"correctness": "partial", "depth_achieved": "surface"}) == 4
    )
    assert (
        scorer._score_for({"correctness": "incorrect", "depth_achieved": "surface"})
        == 1
    )
    # A usable model score wins, and is clamped into range.
    assert scorer._score_for({"score": 7}) == 7
    assert scorer._score_for({"score": 99}) == 10
    assert (
        scorer._score_for(
            {
                "score": "nonsense",
                "correctness": "correct",
                "depth_achieved": "adequate",
            }
        )
        == 8
    )


def test_long_transcript_keeps_the_output_format_block(monkeypatch):
    """A long transcript must never push the JSON schema out of the prompt."""
    seen: dict[str, str] = {}

    def fake_chat(prompt, max_tokens=1200, temperature=0.1):
        if "## Scoring scale" in prompt:
            seen["analyze"] = prompt
            return "[]"
        return "summary"

    monkeypatch.setattr(scorer, "_chat", fake_chat)

    huge = "x" * 5000  # each answer alone dwarfs the old 7000-char prompt cap
    scorer.run_scoring_agent(
        "SQL",
        ["joins"],
        _questions(8),
        [{"question_id": i, "answer_text": huge} for i in range(1, 9)],
    )

    prompt = seen["analyze"]
    assert "## Output format" in prompt, "truncation ate the schema again"
    assert '"question_id"' in prompt and '"score"' in prompt
    assert prompt.rstrip().endswith("Return ONLY the JSON array.")


def test_chat_does_not_truncate_the_assembled_prompt():
    """Bound the transcript, never the rendered prompt (the comment may still cite the old line)."""
    import inspect

    code = [
        ln.split("#")[0]
        for ln in inspect.getsource(scorer).splitlines()
        if not ln.lstrip().startswith("#")
    ]
    assert not any("prompt = prompt[:" in ln for ln in code)
