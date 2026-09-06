---
name: progress-tracking
description: Update the learner's Elo proficiency on Atelier after a quiz and capture their mood from reflections.
---

# Progress tracking

Turn a quiz result plus a reflection into an updated proficiency model for the learner.

## Procedure

1. Call `get_proficiency` for the current Elo on the topic (default 500 if unseen).
2. Call `calculate_elo` with the current Elo and the quiz score (0.0–1.0) to get the
   new Elo (K=32, clamped 0–1000).
3. If the learner wrote a reflection, call `analyze_sentiment` on it to capture mood
   (POSITIVE / NEGATIVE / NEUTRAL). A NEGATIVE mood is a signal to ease difficulty next.
4. Call `save_progress` with learner_id, topic, old_elo, new_elo, score, and mood to
   persist it.

## Guidelines

- Confirm warmly and specifically: the Elo change, XP earned, and one encouraging,
  honest note about where the learner is heading.
