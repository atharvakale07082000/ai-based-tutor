---
name: quiz-authoring
description: Author an adaptive, Bloom-calibrated Atelier quiz matched to the learner's proficiency, then persist it.
allowed-tools: get_proficiency score_difficulty generate_quiz save_quiz
---

# Quiz authoring

Produce a quiz whose difficulty fits the learner on Atelier — not too easy, not crushing.

## Procedure

1. Call `get_proficiency` for the learner's Elo on the target topic. Choose a Bloom
   level from Elo (same bands as teaching: <300 remember, 300–600 apply, 600–800
   analyze, >800 evaluate/create).
2. Optionally call `score_difficulty` on the topic; if difficulty > 0.75 and the
   learner's Elo is low (< 400), drop one Bloom level so they aren't overwhelmed.
3. Call `generate_quiz` with the topic, chosen `bloom_level`, and count (default 5).
4. Call `save_quiz` with the learner_id, topic, bloom_level, and the questions to
   persist it.

## Guidelines

- Report the number of questions and the Bloom level back to the learner.
- Never expose correct answers in your chat reply — the quiz is taken separately.
