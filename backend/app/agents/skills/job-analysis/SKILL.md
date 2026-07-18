---
name: job-analysis
description: Parse a job description, compare its required skills to the learner's proficiency, and recommend how to close the gaps.
allowed-tools: get_proficiency get_topic_graph web_search
---

# Job / skill-gap analysis

Turn a job description into a concrete readiness picture.

1. Extract the required skills from the JD (role, seniority, and the concrete
   technologies/skills named). Normalize to at most ~20 distinct skills.
2. Call `get_proficiency` for the learner's Elo per skill. Classify each:
   - have (Elo ≥ 700), partial (Elo ≥ 500), or missing.
3. Compute a readiness score 0-100 (have = full weight, partial = half, missing = 0).
4. For each gap, recommend a next step: a course/topic to study or a quiz to take.
   Optionally use `web_search` for a strong learning resource. Cap at ~8 recommendations.
5. Present: readiness score, the skill-gap breakdown, and the prioritized recommendations
   (biggest, most-required gaps first).
