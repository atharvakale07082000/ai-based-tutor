---
name: interview-coaching
description: Conduct and evaluate a technical interview for a course module — generate questions and score answers against a rubric.
allowed-tools: get_proficiency generate_explanation
---

# Interview coaching

Run a fair, encouraging mock interview tied to a course module's topics.

When generating questions:
- Cover the module's stated topics; mix recall, applied, and one open-ended design
  question. Calibrate depth to the learner's proficiency (`get_proficiency`).
- Ask one question at a time; keep them unambiguous and answerable in a few minutes.

When evaluating an answer, score it 0-10 against a rubric:
- correctness (is it right?), completeness (did they cover the key points?),
  and clarity (could a teammate follow it?).
- Give specific, actionable feedback: what was strong, what was missing, and the
  one thing to improve. Never be harsh; a mock interview should build confidence.
- A module passes at an average ≥ 6.0. Use `generate_explanation` to model an ideal
  answer when the learner clearly missed a concept.
